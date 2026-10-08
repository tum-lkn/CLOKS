package core

import (
	"fmt"
	"network-simulator/entities"
	"network-simulator/events"
	"network-simulator/logger"
	"reflect"

	"github.com/sirupsen/logrus"
)

func handleRequestLBArrival(event *events.RequestLBArrivalEvent, sim SimulatorInterface) error {
	// We can use `event.Request.Status = "Arrived at LB"` to track the Request
	simTime := sim.GetSimTime()

	req := event.Request

	req.TimeLBArrival = simTime
	serviceName := req.ServiceName
	profileName := req.ProfileName

	nextPod := sim.GetLB(serviceName).NextPod(
		req,
		simTime,
	)

	if nextPod == nil {
		// No running pods available - drop the request
		logger.GetLogger(simTime).
			WithField("serviceName", serviceName).
			WithField("requestID", event.Request.ID).
			Warn("No running pods available for service, dropping request")
		return nil
	}

	if nextPod.Phase != entities.PodRunning {
		panic(fmt.Sprintf("NextPod is not running: podID=%v, phase=%v", nextPod.ID, nextPod.Phase))
	}

	// Calculate internode delay if LB and Pod are on different nodes
	lbNodeID := sim.GetLB(serviceName).GetNodeID()
	var podNodeID int
	if nextPod.Node != nil {
		podNodeID = nextPod.Node.ID
	} else {
		// Pod removed from node (shutting down) - use 0 delay
		podNodeID = lbNodeID
	}
	internodeDelay := 0.0
	internodeDelay = sim.GetInternodeDelay(lbNodeID, podNodeID)

	event.Request.TimeLBArrival = simTime

	// logger.GetLogger(simTime).
	// 	WithField("requestID", event.Request.ID).
	// 	WithField("serviceName", event.Request.ServiceName).
	// 	WithField("profileName", event.Request.ProfileName).
	// 	WithField("podID", nextPod.ID).
	// 	WithField("lbNodeID", lbNodeID).
	// 	WithField("podNodeID", podNodeID).
	// 	WithField("internodeDelay", internodeDelay).
	// 	Warning(reflect.TypeOf(event))

	// Schedule the RequestLBTimeoutEvent
	if nextPod.Deployment.RequestCanTimeOut() {
		newRequestLBTimeoutEvent := events.NewRequestLBTimeoutEvent(
			simTime+sim.GetDeployment(serviceName).RequestTimeoutLimit(),
			req,
		)
		sim.ScheduleEvent(newRequestLBTimeoutEvent)
	}

	reqPodArrival := events.NewRequestPodArrivalEvent(
		simTime+sim.GetLBDelay()+internodeDelay,
		event.Request,
		nextPod,
	)
	// Forward the request to the Pod
	sim.ScheduleEvent(reqPodArrival)

	// Schedule the next LB arrival only for root requests (frontend), not upstream calls
	if event.Request.DownstreamRequest() == nil {
		iat, reqIndex := sim.GetProfile(profileName).Call(simTime)

		// Copy the Request
		newRequest := new(entities.Request)
		*newRequest = *event.Request
		newRequest.ID = reqIndex

		newLBArrival := events.NewRequestLBArrivalEvent(
			simTime+iat,
			newRequest,
		)

		sim.ScheduleEvent(newLBArrival)
	}

	return nil
}

func handleRequestPodArrival(event *events.RequestPodArrivalEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()

	req := event.Request
	pod := event.Pod

	if logger.GetLogger(simTime).Logger.IsLevelEnabled(logrus.DebugLevel) { // Guard clause for optimization
		logger.GetLogger(simTime).
			WithField("requestID", req.ID).
			WithField("serviceName", req.ServiceName).
			WithField("profileName", req.ProfileName).
			WithField("podID", pod.ID).
			Debug(reflect.TypeOf(event))
	}

	req.TimePodArrival = simTime

	// Calls the corresponding AddRequest function
	pod.AddRequest(req, simTime)

	task := entities.NewTask(
		req.ID,
		req,
		simTime,
		req.ProcessingTime,
		pod)

	// Set the Task Corresponding to the Event
	req.Task = task

	taskCreate := events.NewTaskCreateEvent(simTime, task, pod)
	sim.ScheduleEvent(taskCreate)

	return nil
}

func handleRequestPodDeparture(event *events.RequestPodDepartureEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()
	req := event.Request

	if logger.GetLogger(simTime).Logger.IsLevelEnabled(logrus.DebugLevel) { // Guard clause for optimization
		logger.GetLogger(simTime).
			WithField("requestID", req.ID).
			WithField("podID", event.Pod.ID).
			Debug(reflect.TypeOf(event))
	}

	event.Pod.RemoveRequest(event.Request, simTime)

	// TODD Not sure if there is a problem if a PodKillEvent generated this
	if event.Pod.GetNumRequests() == 0 && event.Pod.Phase == entities.PodShuttingDown {
		podKillEvent := events.NewPodKillEvent(simTime, event.Pod.Deployment, event.Pod)
		sim.ScheduleEvent(podKillEvent)

	}

	// Calculate internode delay before forwarding the request to the LB
	lbNodeID := sim.GetLB(req.ServiceName).GetNodeID()
	var podNodeID int
	if event.Pod.Node != nil {
		podNodeID = event.Pod.Node.ID
	} else {
		// Pod removed from node (killed) - use LB node to avoid nil pointer
		podNodeID = lbNodeID
	}
	internodeDelay := sim.GetInternodeDelay(podNodeID, lbNodeID)

	reqLBDeparture := events.NewRequestLBDepartureEvent(
		sim.GetSimTime()+sim.GetLBDelay()+internodeDelay,
		req,
		event.Pod,
	)

	sim.ScheduleEvent(reqLBDeparture)

	return nil
}

func handleRequestLBDeparture(event *events.RequestLBDepartureEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()

	req := event.Request

	req.TimeLBDeparture = simTime

	timedOut := req.TimedOut()
	errored := req.Errored()

	if !timedOut && !errored {
		req.SetStatus(entities.RequestCompleted)
	}

	sim.GetCounter(req.ServiceName).Observe(
		req.ID,
		req.TimeLBDeparture,
		req.TimeLBDeparture-req.TimeLBArrival,
		timedOut,
		errored,
	)

	if logger.GetLogger(simTime).Logger.IsLevelEnabled(logrus.DebugLevel) { // Guard clause for optimization
		logger.GetLogger(simTime).
			WithField("requestID", req.ID).
			WithField("requestCompletionTime", req.TimeLBDeparture-req.TimeLBArrival).
			WithField("podID", event.Pod.ID).
			WithField("requestArrivalTime", req.TimeLBArrival).
			WithField("serviceName", req.ServiceName).
			WithField("profileName", req.ProfileName).
			Debug(reflect.TypeOf(event))
	}
	// logger.GetLogger(simTime).
	// 	WithField("requestID", req.ID).
	// 	WithField("requestCompletionTime", req.TimeLBDeparture-req.TimeLBArrival).
	// 	WithField("podID", event.Pod.ID).
	// 	WithField("requestArrivalTime", req.TimeLBArrival).
	// 	WithField("serviceName", req.ServiceName).
	// 	WithField("profileName", req.ProfileName).
	// 	Info(reflect.TypeOf(event))

	requestName := req.ServiceName
	sim.GetLB(requestName).UpdateState(req, event.Pod, simTime)

	if req.DownstreamRequest() != nil {
		sim.ScheduleEvent(events.NewRequestUpstreamCompletionEvent(simTime, req.DownstreamRequest(), req))
	}

	return nil
}

func handleRequestLBTimeout(event *events.RequestLBTimeoutEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()
	req := event.Request
	task := req.Task
	p := task.Pod

	if task.Status() == entities.TaskCompleted {
		return nil
	}

	// Guard clause, if the reqeust has already been completed, then nothing happens
	if req.Status() == entities.RequestCompleted || req.Errored() {
		return nil
	}

	// Check if the Task is actually done, this might happen if the Timeout is exactly at the same time
	// as the request completion and we didn't manage to update the status of the request.
	// In this case we have to skip the Timeout

	if task.IsUnassigned() {
		// This means that the task is pending, we need to check if it is Pending at the Pod Level
		// or at the worker level

		removed := p.TryDiscardPodPendingTask(task) || p.TryDiscardWorkerPendingTask(task)

		if !removed {
			panic("We should never be able to reach this situation")
		}
	} else {
		thread := task.Thread
		previousThreadStatus := thread.Status()

		if thread == nil {
			panic("The thread of the task should not be nil here (as we checked it above it the Task was completed)")
		}

		// Account execution only if this timed-out task is the one currently running.
		if thread.Status() == entities.ThreadRunning && thread.Task == task {
			accountThreadExecution(thread, simTime)
		}

		// If the Task was already running the following line will remove the old task
		// and, if a new task is available, it will be used and then the thread Status is set to runnable
		// Otherwise, the threadStatus is set to Idle
		p.CompleteTask(task)
		task.SetCompletedAt(simTime)

		// However if the newly-set status is ThreadRunnable but the previous was ThreadThrottled,
		// we need to revert to ThreadThrottled
		if thread.Status() == entities.ThreadRunnable && previousThreadStatus == entities.ThreadThrottled {
			sched := thread.Worker.CPU.Scheduler
			sched.TransitionThread(thread, entities.ThreadThrottled)
		}

	}

	req.SetStatus(entities.RequestTimeout)

	// *** REMOVE REQUEST FROM POD ***
	p.RemoveRequest(req, simTime)

	newRequestLBDepartureEvent := events.NewRequestLBDepartureEvent(
		simTime,
		req,
		p,
	)
	sim.ScheduleEvent(newRequestLBDepartureEvent)

	return nil
}
