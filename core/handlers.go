package core

import (
	"fmt"
	"network-simulator/entities"
	"network-simulator/events"
	"network-simulator/logger"
	"reflect"
	"time"

	"github.com/sirupsen/logrus"
)

// Handleevents.Event routes the event to the appropriate handler
func HandleEvent(event events.Event, sim SimulatorInterface) error {

	// logger.GetLogger(sim.GetSimTime()).Trace(
	// 	fmt.Sprintf("Event %s", reflect.TypeOf(event)),
	// )

	switch eventTyped := event.(type) {
	case *events.RequestLBArrivalEvent:
		return handleRequestLBArrival(eventTyped, sim)
	case *events.RequestPodArrivalEvent:
		return handleRequestPodArrival(eventTyped, sim)
	case *events.RequestPodDepartureEvent:
		return handleRequestPodDeparture(eventTyped, sim)
	case *events.RequestLBDepartureEvent:
		return handleRequestLBDeparture(eventTyped, sim)
	case *events.RequestLBTimeoutEvent:
		return handleRequestLBTimeout(eventTyped, sim)
	case *events.RequestUpstreamEvent:
		return handleRequestUpstream(eventTyped, sim)
	case *events.RequestUpstreamCompletionEvent:
		return handleRequestUpstreamCompletion(eventTyped, sim)

	case *events.PodCreationEvent:
		return handlePodCreationEvent(eventTyped, sim)
	case *events.PodTerminationEvent:
		return handlePodTerminationEvent(eventTyped, sim)
	case *events.PodKillEvent:
		return handlePodKillEvent(eventTyped, sim)
	case *events.PodReadyEvent:
		return handlePodReadyEvent(eventTyped, sim)
	case *events.KubeletCollectionEvent:
		return handleKubeletCollectionEvent(eventTyped, sim)
	case *events.MetricsCollectionEvent:
		return handleMetricsCollectionEvent(eventTyped, sim)
	case *events.HPAEvent:
		return handleHPAEvent(eventTyped, sim)

	case *events.SimPerfEvent:
		return handleSimPerfEvent(eventTyped, sim)
	case *events.SimStartEvent:
		return handleSimStartEvent(eventTyped, sim)
	case *events.SimPauseEvent:
		return handleSimPauseEvent(eventTyped, sim)

	case *events.CounterEvent:
		return handleCounterEvent(eventTyped, sim)
	// case *events.UpstreamTriggerCheckEvent:
	// 	return handleUpstreamTriggerCheckEvent(eventTyped, sim)

	case *events.ThreadWakeupEvent:
		return handleThreadWakeupEvent(eventTyped, sim)
	case *events.ThreadScheduleEvent:
		return handleThreadScheduleEvent(eventTyped, sim)
	case *events.QuotaReplenishEvent:
		return handleQuotaReplenishEvent(eventTyped, sim)

	case *events.TaskCreateEvent:
		return handleTaskCreateEvent(eventTyped, sim)
	case *events.TaskCompleteEvent:
		return handleTaskCompleteEvent(eventTyped, sim)
	case *events.TaskErrorEvent:
		return handleTaskErrorEvent(eventTyped, sim)

	default:
		// log.Warning("unknown event type:", reflect.TypeOf(event))
		panic(
			fmt.Sprintf("unknown event type: %s\n", reflect.TypeOf(event)),
		)
		// return nil
	}
}

// Handlers for different event types

// handlePodCreationEvent handles the creation of a new pod for a given deployment.
func handlePodCreationEvent(event *events.PodCreationEvent, sim SimulatorInterface) error {
	// Get the current simulation time from the simulator.
	simTime := sim.GetSimTime()
	deployment := event.Deployment

	// Log the details of the event, including deployment name, current number of pods,
	// and the index of the new pod being created.
	logger.GetLogger(simTime).
		WithField("serviceName", deployment.Name).
		WithField("currPodsNum", deployment.GetNumPods()).
		WithField("currPodsRunningNum", deployment.GetNumRunningPods()).
		WithField("newPodIndex", deployment.GetLastIndex()).
		WithField("numPodsChange", 1).
		WithField("tag", "trackNumPodsChange").
		Info(reflect.TypeOf(event))

	writeInfluxMetricsAsync(sim, map[string]float64{
		"pods_total":   float64(deployment.GetNumPods()),
		"pods_running": float64(deployment.GetNumRunningPods()),
		"pod_change":   1,
	}, map[string]string{
		"deployment": deployment.Name,
	}, simTime) // simTime is also the timestamp here

	newPod := deployment.CreatePod(simTime)
	if newPod == nil {
		return nil // We can't create any more pods, we are at the upper limit
	}

	// Use the PodScheduler to get the recommendation for scheduling
	podSched := sim.GetPodScheduler()
	schedulingResult := podSched.SchedulePod(newPod, sim.GetNodes())

	if schedulingResult.SelectedNode != nil { // If scheduling was successful
		schedulingResult.SelectedNode.AddPodToNode(newPod)

		newPodReadyEvent := events.NewPodReadyEvent(
			simTime+deployment.PodReadyDelay,
			newPod,
		)

		sim.ScheduleEvent(newPodReadyEvent)
	}

	// Log scheduling result for debugging
	if schedulingResult.SchedulingStatus != "Success" {
		logger.GetLogger(simTime).
			WithField("podID", newPod.ID).
			WithField("deploymentName", event.Deployment.Name).
			WithField("schedulingStatus", schedulingResult.SchedulingStatus).
			WithField("reason", schedulingResult.Reason).
			Warning("Pod scheduling failed")
	} else {
		logger.GetLogger(simTime).
			WithField("podID", newPod.ID).
			WithField("deploymentName", event.Deployment.Name).
			WithField("selectedNode", schedulingResult.SelectedNode.Name).
			WithField("schedulingStatus", schedulingResult.SchedulingStatus).
			Debug("Pod scheduling succeeded")
	}

	return nil
}

// handlePodReadyEvent is called when a pod's containers are ready and the pod transitions to Running.
func handlePodReadyEvent(event *events.PodReadyEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()
	logger.GetLogger(simTime).Info(reflect.TypeOf(event))

	// Here we actually start the Pod
	pod := event.Pod
	pod.StartPod()

	return nil
}

// handlePodTerminationEvent handles the deletion of a pod for a given deployment.
func handlePodTerminationEvent(event *events.PodTerminationEvent, sim SimulatorInterface) error {
	// Get the current simulation time from the simulator.
	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		WithField("serviceName", event.Deployment.Name).
		WithField("v", event.Deployment.GetNumPods()).
		WithField("currPodsRunningNum", event.Deployment.GetNumRunningPods()).
		WithField("numPodsChange", -1).
		WithField("tag", "trackNumPodsChange").
		Info(reflect.TypeOf(event))

	writeInfluxMetricsAsync(sim, map[string]float64{
		"pods_total":   float64(event.Deployment.GetNumPods()),
		"pods_running": float64(event.Deployment.GetNumRunningPods()),
		"pod_change":   -1,
	}, map[string]string{
		"deployment": event.Deployment.Name,
	}, simTime) // simTime is also the timestamp here

	// Delete the pod from the deployment immediately.
	// Requests still outstanding on this pod are not drained before it is deleted.

	podToBeDeleted := event.Deployment.GetPodForTermination()
	if podToBeDeleted == nil {
		logger.GetLogger(simTime).
			WithField("deploymentName", event.Deployment.Name).
			Warn("No pod available for termination")
		return nil
	}
	podToBeDeleted.Phase = entities.PodShuttingDown

	podKill := events.NewPodKillEvent(simTime+event.Deployment.PodDeletionGracePeriod, event.Deployment, podToBeDeleted)
	sim.ScheduleEvent(podKill)

	// event.Deployment.DeletePod(simTime)

	return nil
}

func handlePodKillEvent(event *events.PodKillEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	podToBeKilled := event.Pod
	deployment := podToBeKilled.Deployment

	if !deployment.HasPod(podToBeKilled) {
		logger.GetLogger(simTime).WithField("podID", podToBeKilled.ID).Warn("podKilledAgain")
		return nil // Pod has already been removed
	} // This is already handling the case when the Pod has already been killed in the past

	logger.GetLogger(simTime).
		WithField("deploymentName", event.Deployment.Name).
		WithField("podID", event.Pod.ID).
		WithField("tag", "trackPodKill").
		Info(reflect.TypeOf(event))

	// If pod is not idle, mark pod-level queued tasks as errors.
	if !podToBeKilled.IsIdle() {
		for _, task := range podToBeKilled.PendingTasks() {
			newTaskErrorEvent := events.NewTaskErrorEvent(simTime, task)
			sim.ScheduleEvent(newTaskErrorEvent)
		}
	}

	// Common cleanup for all workers/threads, regardless of pod idle state.
	for _, w := range podToBeKilled.Workers {
		for _, task := range w.PendingTasks() {

			newTaskErrorEvent := events.NewTaskErrorEvent(simTime, task)
			sim.ScheduleEvent(newTaskErrorEvent)
		}

		for _, t := range w.Threads() {
			sched := t.Worker.CPU.Scheduler

			// If the thread has a Task, we shoud call the corresponding TaskErrorEvent
			if t.Task != nil {
				newTaskErrorEvent := events.NewTaskErrorEvent(simTime, t.Task)
				sim.ScheduleEvent(newTaskErrorEvent)
			}

			sched.TransitionThread(t, entities.ThreadStopped)
		}
	}

	podToBeKilled.Workers = nil

	// Remove the Pod from the Deployment
	event.Deployment.KillPod(simTime, podToBeKilled)

	// A pod removal can free node resources; retry scheduling pending pods immediately.
	trySchedulePendingPods(simTime, sim)

	return nil
}

func trySchedulePendingPods(simTime float64, sim SimulatorInterface) {
	for _, pod := range sim.GetPods() {
		if pod.Phase != entities.PodPending {
			continue
		}

		schedulingResult := sim.GetPodScheduler().SchedulePod(pod, sim.GetNodes())
		if schedulingResult.SchedulingStatus != "Success" {
			logger.GetLogger(simTime).
				WithField("podID", pod.ID).
				WithField("deploymentName", pod.Deployment.Name).
				WithField("schedulingStatus", schedulingResult.SchedulingStatus).
				WithField("reason", schedulingResult.Reason).
				Debug("Pending pod scheduling retry failed")
			continue
		}

		logger.GetLogger(simTime).
			WithField("podID", pod.ID).
			WithField("deploymentName", pod.Deployment.Name).
			WithField("selectedNode", schedulingResult.SelectedNode.Name).
			Info("Pending pod scheduled after pod kill")
	}
}

func handleKubeletCollectionEvent(event *events.KubeletCollectionEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		WithField("kubeletMeasurements", event.Kubelet.GetAllPodMeasurementsToJson()).
		Debug(reflect.TypeOf(event))

	event.Kubelet.RecordAllPodMeasurements(simTime)

	newKubeletCollectionEvent := events.NewKubeletCollectionEvent(
		simTime+event.Kubelet.GetSamplingPeriod(),
		event.Kubelet,
	)

	sim.ScheduleEvent(newKubeletCollectionEvent)

	return nil

}

func handleMetricsCollectionEvent(event *events.MetricsCollectionEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	event.MetricsServer.RecordAllPodMeasurements(simTime)

	newMetricsCollectionEvent := events.NewMetricsCollectionEvent(
		simTime+event.MetricsServer.GetSamplingPeriod(),
		event.MetricsServer,
	)

	sim.ScheduleEvent(newMetricsCollectionEvent)

	logger.GetLogger(simTime).
		WithField("metricsServerMeasurements", event.MetricsServer.GetAllPodMeasurementsToJson()).
		Debug(reflect.TypeOf(event))

	return nil
}

func handleHPAEvent(event *events.HPAEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		WithField("cpuLoadMeasurements", event.HPA.GetCPULoadMeasurements()).
		WithField("meanCpuUtilization", event.HPA.GetMeanCPUUtilization()).
		WithField("deploymentLastIndex", event.HPA.GetDeployment().GetLastIndex()).
		WithField("deploymentFirstIndex", event.HPA.GetDeployment().GetFirstIndex()).
		WithField("deploymentName", event.HPA.GetDeployment().Name).
		Info(reflect.TypeOf(event))

	scalingAction, amountPods := event.HPA.GetScalingAction(simTime)
	switch scalingAction {
	case entities.HPADoNothing:
		break
	case entities.HPAScaleIn:
		// Handle decreasing the number of pods by amountPods
		for range amountPods {
			PodTerminationEvent := events.NewPodTerminationEvent(
				simTime+0.01, // shortly after the scaling decision
				event.HPA.GetDeployment(),
			)
			sim.ScheduleEvent(PodTerminationEvent)
		}
	case entities.HPAScaleOut:
		// Handle increasing the number of pods by amountPods
		for range amountPods {
			// The PodCreationEvent deals mostly with finding on which Node the Pod should run,
			// blocking the node resources (decreasing the availability) and preparing the workers
			// but not yet assigning any tasks to the workers.
			podCreationEvent := events.NewPodCreationEvent(
				simTime+2,
				event.HPA.GetDeployment(),
			)
			sim.ScheduleEvent(podCreationEvent)
		}
	}

	newHPAEvent := events.NewHPAEvent(
		simTime+event.HPA.GetSyncPeriod(),
		event.HPA,
	)

	sim.ScheduleEvent(newHPAEvent)

	return nil
}

func handleSimPerfEvent(event *events.SimPerfEvent, sim SimulatorInterface) error {

	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		WithField("speedUpFactor", event.SpeedUpFactor).
		Info(reflect.TypeOf(event))

	evQueue := *sim.GetEventQueue()

	fields := logrus.Fields{}
	nrEvents := make(map[string]int)

	for _, ev := range evQueue {
		nrEvents[reflect.TypeOf(ev).String()] += 1
	}

	for k, v := range nrEvents {
		fields[k] = v
	}

	// logger.GetLogger(simTime).WithFields(fields).Debug("MockEvQueueLength")

	newSimPerfEvent := events.NewSimPerfEvent(
		simTime+event.SamplingPeriod,
		event.WallClockTime,
		simTime,
		event.SamplingPeriod,
	)
	sim.ScheduleEvent(newSimPerfEvent)

	return nil
}

func handleCounterEvent(event *events.CounterEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	// Flush returns one completed statistics window at a time; log windows until none is left
	stats, statsTime, _ := event.Counter.Flush(simTime)

	for stats != nil {
		fields := logrus.Fields{}

		// for k, v := range stats {
		// 	fields[k] = v
		// }

		// Only these statistics are written to the log
		for k, v := range stats {
			if k == "mean" ||
				k == "p50" ||
				k == "p90" ||
				k == "p95" ||
				k == "min" ||
				k == "max" ||
				k == "nrReq" ||
				k == "nrReqTimeout" ||
				k == "nrReqError" {
				fields[k] = v
			}
		}

		// FOR Debugging Purposes
		runningPods := 0
		totalThreads := 0
		totalNumberThreadsPerCPUScheduler := make(map[entities.CPUID]int)
		requestsPerPod := make(map[string]int)
		tasksPerPod := make(map[string]int)

		for _, pod := range sim.GetPods() {
			if pod.Deployment.Name != event.Counter.ServiceName {
				continue
			}

			if pod.Phase == entities.PodRunning {
				runningPods++
			}
			requestsPerPod[pod.Name] = pod.GetNumRequests()

			// Count tasks by state per pod
			podTasksTotal := 0

			// Count pending tasks in pod queue
			podTasksTotal += len(pod.PendingTasks())

			// Count tasks in workers and assigned to threads
			for _, worker := range pod.Workers {
				// Count pending tasks in worker queue
				podTasksTotal += len(worker.PendingTasks())

				// Count tasks assigned to threads
				for _, thread := range worker.Threads() {
					if thread == nil {
						continue
					}
					totalThreads++

					if thread.Task != nil {
						podTasksTotal++
					}
				}
			}

			tasksPerPod[pod.Name] = podTasksTotal
		}

		for _, node := range sim.GetNodes() {
			for _, cpu := range node.CPUs {
				totalNumberThreadsPerCPUScheduler[cpu.ID] = cpu.Scheduler.TotalNumberOfThreads()
			}
		}

		fields["podsRunning"] = runningPods
		fields["threadsTotal"] = totalThreads
		fields["requestsPerPod"] = requestsPerPod
		fields["tasksPerPod"] = tasksPerPod
		// fields["totalNumberThreadsPerCPUScheduler"] = totalNumberThreadsPerCPUScheduler

		logger.GetLogger(simTime).
			WithFields(fields).
			WithField("statsTime", statsTime).
			WithField("serviceName", event.Counter.ServiceName).
			Info(reflect.TypeOf(event))

		// InfluxDB Export
		writeInfluxMetricsAsync(sim, stats, map[string]string{
			"service": event.Counter.ServiceName,
		}, statsTime) // statsTime, because simTime is the current time, not the time of the stats

		stats, statsTime, _ = event.Counter.Flush(simTime)
	}

	newCounterEvent := events.NewCounterEvent(
		simTime+event.Counter.FlushingPeriod,
		event.Counter,
	)

	sim.ScheduleEvent(newCounterEvent)

	return nil
}

func handleSimStartEvent(event *events.SimStartEvent, sim SimulatorInterface) error {

	// *********** Initialize Simulation ***********

	// Schedule initial pods using the pod scheduler
	for _, pod := range sim.GetPods() {
		schedulingResult := sim.GetPodScheduler().SchedulePod(pod, sim.GetNodes())

		if schedulingResult.SchedulingStatus != "Success" {
			logger.GetLogger(0).
				WithField("podID", pod.ID).
				WithField("schedulingStatus", schedulingResult.SchedulingStatus).
				WithField("reason", schedulingResult.Reason).
				Warning("Initial pod scheduling failed")
		}

		if schedulingResult.SelectedNode != nil {
			// If scheduling was successful, do the actual scheduling
			schedulingResult.SelectedNode.AddPodToNode(pod)

			// And start the Pod immediately
			pod.StartPod()
		}

		// And we assume that upon SimStart these pods are already running
	}

	// Start the Kubelet MetricCollectionEvent chain
	for _, kubelet := range sim.GetKubelets() {
		kMetricCollectionEvent := events.NewKubeletCollectionEvent(0, kubelet)
		sim.ScheduleEvent(kMetricCollectionEvent)
	}

	// Start the MetricsServer MetricCollectionEvent chain
	mMetricsCollectionEvent := events.NewMetricsCollectionEvent(0, sim.GetMetricsServer())
	sim.ScheduleEvent(mMetricsCollectionEvent)

	// Start the HPAs in the simulator
	for _, hpa := range sim.GetHPAs() {
		newHPAEvent := events.NewHPAEvent(0, hpa)
		sim.ScheduleEvent(newHPAEvent)
	}

	// Schedule for every Node the periodic QuotaReplenishEvent
	for _, n := range sim.GetNodes() {
		quotaReplenishEvent := events.NewQuotaReplenishEvent(0, n)
		sim.ScheduleEvent(quotaReplenishEvent)
	}

	// First Request Arrival
	for profileName, IATProfile := range sim.GetProfiles() {
		serviceName := IATProfile.SeviceName
		requestDurationS := sim.GetDeployment(serviceName).RequestDurationForProfileS(profileName)
		if requestDurationS <= 0 {
			panic("missing request duration for profile '" + profileName + "' in service '" + serviceName + "'")
		}
		reqArrival := events.NewRequestLBArrivalEvent(
			0,
			entities.NewRequest(
				serviceName,
				profileName,
				requestDurationS,
			),
		)
		sim.ScheduleEvent(reqArrival)
	}

	// Counter Events
	for _, counter := range sim.GetCounters() {
		counterEvent := events.NewCounterEvent(
			0,
			counter,
		)
		sim.ScheduleEvent(counterEvent)
	}

	// SimPerfEvents
	simPerfSamplingPeriod := 60.0
	simPerfEvent := events.NewSimPerfEvent(
		0,
		float64(time.Now().UnixMilli())-1000,
		-1,
		simPerfSamplingPeriod,
	)
	sim.ScheduleEvent(simPerfEvent)

	return nil
}

func handleSimPauseEvent(event *events.SimPauseEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	logger.GetLogger(simTime).
		Info(reflect.TypeOf(event))

	sim.Pause()

	return nil
}

// Add this helper function near the top of handlers.go after the imports
func writeInfluxMetricsAsync(sim SimulatorInterface, metrics map[string]float64, tags map[string]string, timestamp float64) {
	if exporter := sim.GetInfluxExporter(); exporter != nil {
		go func() {
			if err := exporter.WriteMultipleMetrics(metrics, tags, timestamp); err != nil {
				logger.GetLogger(timestamp).WithError(err).Error("Failed to write metrics to InfluxDB")
			}
		}()
	}
}
