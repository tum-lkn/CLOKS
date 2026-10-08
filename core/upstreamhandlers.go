package core

import (
	"network-simulator/entities"
	"network-simulator/events"
	"network-simulator/logger"
	"network-simulator/simrand"
	"reflect"

	"github.com/sirupsen/logrus"
)

func requestProgress(task *entities.Task) float64 {
	if task == nil || task.BurstTime <= 0 {
		return 0
	}

	progress := (task.BurstTime - task.TimeLeft) / task.BurstTime

	// Clipping
	if progress < 0 {
		panic("Issues with progress tracking: Progress is < 0")
	}
	if progress > 1 {
		panic("Issues with progress tracking: Progress is > 1")
	}

	return progress
}

func isRequestCompleted(req *entities.Request) bool {
	if req == nil {
		panic("Passed a nil Request to isRequestCompleted")
	}

	// Requests that ended with entities.RequestError are not treated as completed here
	status := req.Status()
	return status == entities.RequestCompleted || status == entities.RequestTimeout
}

func upstreamConfigForTriggeredRequest(deployment *entities.Deployment, upstreamReq *entities.Request) (entities.UpstreamServiceConfig, bool) {

	idx := upstreamReq.TriggeredUpstreamCfgIdx()
	if idx < 0 || idx >= len(deployment.UpstreamServices) {
		panic("Error")
	}

	return deployment.UpstreamServices[idx], true
}

// Returns true if any already-triggered upstream is still pending and this task
// has reached that upstream's block_at progress threshold.
func shouldBlockForPendingUpstreams(task *entities.Task, sim SimulatorInterface) bool {
	if task == nil || task.Request == nil {
		return false
	}

	req := task.Request
	deployment := sim.GetDeployment(req.ServiceName)
	if deployment == nil {
		return false
	}

	progress := requestProgress(task)
	for _, upstreamReq := range req.UpstreamRequests() {
		if isRequestCompleted(upstreamReq) {
			continue
		}

		cfg, ok := upstreamConfigForTriggeredRequest(deployment, upstreamReq)
		if !ok {
			continue
		}

		if progress >= cfg.BlockAt {
			return true
		}
	}

	return false
}

// handleRequestUpstreamEvent handles an upstream call trigger by scheduling the child request
// into the normal request flow (starting from LB arrival).
func handleRequestUpstream(event *events.RequestUpstreamEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	parentReq := event.ParentRequest
	upstreamReq := event.Request
	if parentReq == nil || upstreamReq == nil {
		return nil
	}

	upstreamReq.SetDownstreamRequest(parentReq)
	if parentReq.OriginRequest() != nil {
		upstreamReq.SetOriginRequest(parentReq.OriginRequest())
	} else {
		upstreamReq.SetOriginRequest(parentReq)
	}
	upstreamReq.Depth = parentReq.Depth + 1
	parentReq.AppendUpstreamRequest(upstreamReq)

	if logger.GetLogger(simTime).Logger.IsLevelEnabled(logrus.DebugLevel) { // Guard clause for optimization
		logger.GetLogger(simTime).
			WithField("parentRequestID", parentReq.ID).
			WithField("upstreamRequestID", upstreamReq.ID).
			WithField("parentService", parentReq.ServiceName).
			WithField("upstreamService", upstreamReq.ServiceName).
			Debug(reflect.TypeOf(event))
	}
	sim.ScheduleEvent(events.NewRequestLBArrivalEvent(simTime, upstreamReq))

	return nil
}

// handleRequestUpstreamCompletion handles completion notification for upstream requests.
func handleRequestUpstreamCompletion(event *events.RequestUpstreamCompletionEvent, sim SimulatorInterface) error {
	simTime := sim.GetSimTime()

	parentReq := event.ParentRequest
	upstreamReq := event.Request

	if parentReq == nil {
		panic("There is no parent request anymore")
	}

	if logger.GetLogger(simTime).Logger.IsLevelEnabled(logrus.DebugLevel) {
		logger.GetLogger(simTime).
			WithField("parentRequestID", parentReq.ID).
			WithField("upstreamRequestID", upstreamReq.ID).
			WithField("parentService", parentReq.ServiceName).
			WithField("upstreamService", upstreamReq.ServiceName).
			Debug(reflect.TypeOf(event))
	}
	// If the parent request has timed out, we do nothing
	if parentReq.Status() == entities.RequestTimeout {
		return nil
	}

	if parentReq.Status() == entities.RequestCompleted {
		return nil
	}

	parentTask := parentReq.Task

	parentThread := parentTask.Thread
	if parentThread == nil {
		panic("Here")
	}
	if parentThread.Status() != entities.ThreadBlocked {
		// If the upstream event is not Blocked, then we don't care so much
		return nil
	}

	if shouldBlockForPendingUpstreams(parentTask, sim) {
		return nil
	}

	sim.ScheduleEvent(events.NewThreadWakeupEvent(simTime, parentThread))

	return nil
}

// maybeTriggerUpstreamRequest is a skeleton helper called from scheduling points.
// It checks trigger/probability and emits RequestUpstreamEvent when criteria are met.
func checkAndTriggerUpstreamRequest(task *entities.Task, sim SimulatorInterface) *entities.UpstreamServiceConfig {
	if task == nil || task.Request == nil {
		return nil
	}

	req := task.Request
	deployment := sim.GetDeployment(req.ServiceName)

	if deployment == nil {
		panic("There can't be that a request doesn't have a deployment associated to it")
	}

	if len(deployment.UpstreamServices) == 0 {
		return nil
	}

	if req.NextUpstreamIdx >= len(deployment.UpstreamServices) {
		return nil
	}

	upstreamCfgIdx := req.NextUpstreamIdx
	upstreamCfg := deployment.UpstreamServices[upstreamCfgIdx]
	progress := requestProgress(task)

	if progress < upstreamCfg.TriggerAt {
		return nil
	}

	// Mark this upstream as evaluated so we don't re-check it forever.
	req.NextUpstreamIdx++

	if simrand.Float64() > upstreamCfg.Probability {
		return nil
	}

	upstreamDeployment := sim.GetDeployment(upstreamCfg.UpstreamServiceName)
	if upstreamDeployment == nil {
		return nil
	}
	requestDurationS := upstreamDeployment.RequestDurationForProfileS(upstreamCfg.UpstreamProfileName)

	upstreamReq := entities.NewRequest(
		upstreamCfg.UpstreamServiceName,
		upstreamCfg.UpstreamProfileName,
		requestDurationS,
	)
	upstreamReq.ID = req.ID
	upstreamReq.SetTriggeredUpstreamCfgIdx(upstreamCfgIdx)

	sim.ScheduleEvent(events.NewRequestUpstreamEvent(sim.GetSimTime(), req, upstreamReq))

	return &upstreamCfg
}
