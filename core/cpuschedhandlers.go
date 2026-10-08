package core

import (
	"network-simulator/entities"
	"network-simulator/events"
	"network-simulator/logger"
	"reflect"
)

// Handles TaskCreationEvent
func handleTaskCreateEvent(event *events.TaskCreateEvent, sim SimulatorInterface) error {
	// Add the task to the pod, which will assign it to an available worker
	simTime := sim.GetSimTime()

	assignmentToThreadSuccessful := event.Pod.AddTask(event.Task)

	// logger.GetLogger(simTime).
	// 	WithField("requestID", event.Task.Request.ID).
	// 	WithField("serviceName", event.Task.Request.ServiceName).
	// 	WithField("profileName", event.Task.Request.ProfileName).
	// 	WithField("podID", event.Pod.ID).
	// 	WithField("nodeID", event.Pod.Node.ID).
	// 	Debug(reflect.TypeOf(event))

	// Here check if the Task has been assigned to a Thread (and implicitly to a worker)
	// If not, then we don't have to call any TaskWakeupEvent, because this means that the Task is in
	// the queue of the Pod (sync) -- this is actually the OS TCP backlog queue
	// or of the Worker (gthread) -- this is the Worker internal Queue

	if assignmentToThreadSuccessful {
		taskWakeUp := events.NewThreadWakeupEvent(simTime, event.Task.Thread)
		sim.ScheduleEvent(taskWakeUp)
	}

	return nil
}

func handleThreadWakeupEvent(event *events.ThreadWakeupEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		WithField("requestID", event.Thread.Task.Request.ID).
		WithField("serviceName", event.Thread.Task.Request.ServiceName).
		WithField("profileName", event.Thread.Task.Request.ProfileName).
		Debug(reflect.TypeOf(event))

	thread := event.Thread
	sched := thread.Worker.CPU.Scheduler
	pod := thread.Worker.Pod

	thread.SetVRunTime(sched.MinVRunTime())
	sched.TransitionThread(thread, entities.ThreadRunnable)

	// Guard Clause
	// If the pod is already throttled, put the woken up thread in the ThrottledState
	// And then add it to the ThrottledList
	if pod.IsThrottled() {
		sched.TransitionThread(thread, entities.ThreadThrottled)
		return nil
	}

	// Upon wakeup, if there is no running thread, then the thread that woke up should be running
	if !sched.HasRunningThread() {
		// If there is no running thread, then this thread will be scheduled directly with a very
		// HIGH probability. Therefore we schedule the corresponding event.
		threadScheduleEvent := events.NewThreadScheduleEvent(simTime, &sched)
		sim.ScheduleEvent(threadScheduleEvent)
	}

	return nil
}

func handleThreadScheduleEvent(event *events.ThreadScheduleEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()
	sched := *event.CPUScheduler

	// logger.GetLogger(simTime).Debug(reflect.TypeOf(event))

	// prevRunningTaskID := -1 // *** UNCOMMENT FOR LOGGING ***
	if sched.HasRunningThread() {
		prevRunningThread := sched.RunningThread()

		pod := prevRunningThread.Worker.Pod

		if prevRunningThread.Status() != entities.ThreadRunning {
			panic("The thread that is Running should have the ThreadRunning status")
		}

		// Account the Thread Execution
		// Update its vRunTime and also the available quota in the Pod
		accountThreadExecution(prevRunningThread, simTime)

		// Handle the upstream triggering logic
		triggeredUpstreamCfg := checkAndTriggerUpstreamRequest(prevRunningThread.Task, sim)
		if (triggeredUpstreamCfg != nil && triggeredUpstreamCfg.Blocking) ||
			shouldBlockForPendingUpstreams(prevRunningThread.Task, sim) {
			sched.TransitionThread(prevRunningThread, entities.ThreadBlocked)
		} else {
			// Here we do the CFS Bandwidth control Task
			// We calculate how long the current thread was running and we consume from its quota
			// The lastRunningTime represents how much time has elapsed since the last time when we
			transitionThreadAfterExecution(prevRunningThread, &sched, pod)
		}

	}

	nextRunningThread := sched.PickNextThread()

	// nextRunningTaskID := -1 // *** UNCOMMENT FOR LOGGING ***
	// nextRunningWorkerID := "N/A" // *** UNCOMMENT FOR LOGGING ***
	// nextRunningPodName := "N/A" // *** UNCOMMENT FOR LOGGING ***

	// if nextRunningThread != nil { // *** UNCOMMENT FOR LOGGING ***
	// 	nextRunningTaskID = nextRunningThread.Task.ID // *** UNCOMMENT FOR LOGGING ***
	// 	nextRunningWorkerID = nextRunningThread.Worker.ID // *** UNCOMMENT FOR LOGGING ***
	// 	nextRunningPodName = nextRunningThread.Task.Pod.Name // *** UNCOMMENT FOR LOGGING ***

	// } // *** UNCOMMENT FOR LOGGING ***

	// logger.GetLogger(simTime).
	// 	WithField("prevRunningTaskID", prevRunningTaskID).
	// 	WithField("nextRunningTaskID", nextRunningTaskID).
	// 	WithField("cpuID", sched.CPU().ID).
	// 	WithField("workerID", nextRunningWorkerID).
	// 	WithField("podName", nextRunningPodName).
	// 	Debug(reflect.TypeOf(event)) // *** UNCOMMENT FOR LOGGING ***

	// Guard Statement if there is no other threads to run, no need to schedule anything
	if nextRunningThread == nil {
		return nil
	}

	// Set the thread to Running, and remove it from the Blocked List
	// First change state of the thread
	nextRunningThread.SetScheduledAt(simTime)
	sched.TransitionThread(nextRunningThread, entities.ThreadRunning)

	timeslice := sched.CalculateTimeSlice()

	nextTask := nextRunningThread.Task

	if nextTask.Status() == entities.TaskCompleted {
		panic("Trying to schedule an already completed Task")
	}

	if nextTask.TimeLeft < timeslice {
		// schedule TaskComplete
		runFor := nextTask.TimeLeft
		if runFor < 0 {
			panic("We have an error somewhere that makes the TimeLeft negative.")
		}
		completeEvent := events.NewTaskCompleteEvent(simTime+runFor, nextTask)
		sim.ScheduleEvent(completeEvent)
	} else {
		schedEvent := events.NewThreadScheduleEvent(simTime+timeslice, &sched)
		sim.ScheduleEvent(schedEvent)
	}

	return nil
}

func handleTaskCompleteEvent(event *events.TaskCompleteEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	task := event.Task
	completedThread := task.Thread

	// Check for duplicate/stale events early
	if task.Status() == entities.TaskCompleted {
		if task.CompletedAt() <= simTime {
			// Just a duplicate Event
			// Sometimes due to RequestLBTimeout
			// Sometimes just because of the scheduling
			return nil
		}
	}

	// Check if the thread reference is stale (thread was already cleaned up)
	if completedThread == nil {
		// Task was already completed by timeout or another event
		return nil
	}

	// Check if this thread no longer has this task (was reassigned or cleaned up)
	if completedThread.Task != task {
		// Thread has moved on to another task or is idle - this is a stale event
		return nil
	}

	sched := completedThread.Worker.CPU.Scheduler
	pod := completedThread.Worker.Pod
	request := task.Request

	// *** Update vruntime and task time for final execution burst ***
	// We do this here as after that, the scheduler is EMPTY
	// We need to do the accounting threadwise and podwise

	logger.GetLogger(simTime).
		WithField("requestID", request.ID).
		WithField("threadID", completedThread.ID).
		WithField("cpuID", completedThread.Worker.CPU.ID).
		WithField("serviceName", request.ServiceName).
		WithField("profileName", request.ProfileName).
		Debug(reflect.TypeOf(event))

	accountThreadExecution(completedThread, simTime)

	// In the pod.CompleteTask the status of the thread will definitley change
	pod.CompleteTask(task)
	task.SetCompletedAt(simTime)

	// Afer pod.CompleteTask, the thread has a new status:
	// either Runnable or Idle. If runnable, we need to check if we should Throttle the thread.
	if completedThread.Status() == entities.ThreadRunnable {
		transitionThreadAfterExecution(completedThread, &sched, pod)
	}

	// Schedule the Pod Departure Event, when a task completes, its corresponding Task departs.
	newRequestPodDepartureEvent := events.NewRequestPodDepartureEvent(simTime, request, pod)
	sim.ScheduleEvent(newRequestPodDepartureEvent)

	// Check if the PodStatus is PodShuttingDown. If this is the case, then we check if the Pod is Idle
	// If this is the case, we trigger an immediate PodKillEvent
	if pod.Phase == entities.PodShuttingDown && pod.IsIdle() {
		newPodKillEvent := events.NewPodKillEvent(simTime, pod.Deployment, pod)
		sim.ScheduleEvent(newPodKillEvent)
	}

	schedEvent := events.NewThreadScheduleEvent(simTime, &sched)
	sim.ScheduleEvent(schedEvent)

	return nil
}

func handleTaskErrorEvent(event *events.TaskErrorEvent, sim SimulatorInterface) error {
	// Here we only need to set the status of the corresponding request to Error
	// And schedule immediately the corresponding RequestPodDepartures
	// Now, a TaskErrorEvent can only appear in the case of a PodKill, where there are still
	// The thread Management is momentarily already dealt with in the HandlePodKill, but later we
	// might need to change that

	simTime := sim.GetSimTime()
	request := event.Task.Request
	pod := event.Task.Pod

	request.SetStatus(entities.RequestError)

	newRequestPodDepartureEvent := events.NewRequestPodDepartureEvent(simTime, request, pod)
	sim.ScheduleEvent(newRequestPodDepartureEvent)

	return nil
}

func handleQuotaReplenishEvent(event *events.QuotaReplenishEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()
	node := event.Node
	// logger.GetLogger(simTime).
	// 	WithField("nodeID", node.ID).
	// 	WithField("activePods", len(node.GetActivePods())).
	// 	Debug("quotaReplenished")

	// Do the logic here: What needs to happen to the Pods?
	// Here we need to iterate
	// While we could in principle abstract out the logic here and move it to p.ReplenishAvailableQuota
	// We try to do as few Thread state changes in the Pod logic, and keep them mostly here
	for _, p := range node.GetRunningPods() {
		// Here we iterate through all the workers and through all the Threads of this pod and if they
		// were in the ThreadThrottled, we put them to ThreadRunnable
		p.ReplenishAvailableQuotaTime()
		if !p.IsThrottled() {
			p.SetThrottledThreadsToRunnable()
		}
	}

	for _, cpu := range node.CPUs {
		sched := cpu.Scheduler

		// If there is no running thread, call the CPUScheduling, similarly to what we do on
		// ThreadWakeupEvent
		// if !sched.HasRunningThread() && sched.HasRunnableThread() {
		if !sched.HasRunningThread() {
			threadScheduleEvent := events.NewThreadScheduleEvent(simTime, &sched)
			sim.ScheduleEvent(threadScheduleEvent)
		}

	}

	node.SetLastQuotaReplenishTime(simTime)
	nextQuotaReplenishTime := event.Node.NextQuotaReplenishTime()

	if nextQuotaReplenishTime < simTime {
		panic("Something went wrong, we are trying to set the nextQuotaReplenishTime in the past")
	}

	newQuotaReplenishEvent := events.NewQuotaReplenishEvent(nextQuotaReplenishTime, node)
	sim.ScheduleEvent(newQuotaReplenishEvent)

	return nil
}
