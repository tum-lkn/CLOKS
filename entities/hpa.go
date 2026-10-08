package entities

import (
	"math"
)

type HPAAction string

const (
	HPAScaleOut  HPAAction = "ScaleOut"  // Increase the number of Pods
	HPADoNothing HPAAction = "DoNothing" // Do Nothing
	HPAScaleIn   HPAAction = "ScaleIn"   // Decrease the number of Pods
)

type HPA interface {
	GetSyncPeriod() float64
	GetScalingAction(simTime float64) (HPAAction, int)
	GetCPULoadMeasurements() []float64
	GetMeanCPUUtilization() float64
	GetDeployment() *Deployment
}

type OriginalHPA struct {
	Deployment          *Deployment
	MetricsServer       *MetricsServer
	deploymentName      string
	cpuThreshold        float64
	syncPeriod          float64
	gracePeriodScaleIn  float64 // default 300
	gracePeriodScaleOut float64 // default 15
	tolerance           float64 // Default 0.1
	timeLastScale       float64

	desiredNumRunningPodsQueue []desiredNumRunningPodsMeasurement
}

type desiredNumRunningPodsMeasurement struct {
	time                  float64
	desiredNumRunningPods int
}

func NewOriginalHPA(d *Deployment, m *MetricsServer, cpuThreshold, scaleIn, scaleOut, syncPeriod float64) *OriginalHPA {
	return &OriginalHPA{
		Deployment:     d,
		MetricsServer:  m,
		deploymentName: d.Name,
		cpuThreshold:   cpuThreshold,
		syncPeriod:     syncPeriod,

		gracePeriodScaleIn:  scaleIn,
		gracePeriodScaleOut: scaleOut,
		tolerance:           0.1, // Default 10% tolerance
	}
}

func (h *OriginalHPA) GetDeployment() *Deployment {
	return h.Deployment
}

func (h *OriginalHPA) GetSyncPeriod() float64 {
	return h.syncPeriod
}

func (h *OriginalHPA) GetScalingAction(simTime float64) (HPAAction, int) {
	scaleFactor := h.getScaleFactor()
	if scaleFactor <= 0 {
		// No usable CPU measurements yet, so there is nothing to scale
		return HPADoNothing, 0
	}

	// currentNumRunningPods := h.Deployment.GetNumRunningPods()
	currentNumActivePods := h.Deployment.GetNumActivePods()
	desiredNumRunningPods := int(math.Ceil(scaleFactor * float64(currentNumActivePods)))

	// Add current measurement to the stabilization window queue
	h.desiredNumRunningPodsQueue = append(h.desiredNumRunningPodsQueue,
		desiredNumRunningPodsMeasurement{
			time:                  simTime,
			desiredNumRunningPods: desiredNumRunningPods,
		},
	)

	// Remove measurements outside the scale-in window
	lastOutOfRangeIndex := -1
	for i, measurement := range h.desiredNumRunningPodsQueue {
		if simTime-measurement.time > h.gracePeriodScaleIn {
			lastOutOfRangeIndex = i
		} else {
			break
		}
	}
	h.desiredNumRunningPodsQueue = h.desiredNumRunningPodsQueue[lastOutOfRangeIndex+1:]

	// Scale out logic
	if scaleFactor > 1+h.tolerance {
		if simTime-h.timeLastScale < h.gracePeriodScaleOut {
			return HPADoNothing, 0
		}

		// Calculate maximum scale out size (matches Kubernetes default: max(4, 100% of current))
		// maxScaleUpAmount := max(4, currentNumActivePods)
		maxScaleUpAmount := max(4, currentNumActivePods)
		proposedNumPods := min(
			h.Deployment.MaxPods,
			currentNumActivePods+maxScaleUpAmount,
			desiredNumRunningPods,
		)

		if proposedNumPods > currentNumActivePods {
			h.timeLastScale = simTime
			return HPAScaleOut, proposedNumPods - currentNumActivePods
		}
		return HPADoNothing, 0
	}

	// Scale in logic
	if scaleFactor < 1-h.tolerance {
		// Find the highest recommendation in the stabilization window
		maxDesiredPods := 0
		for _, measurement := range h.desiredNumRunningPodsQueue {
			if measurement.desiredNumRunningPods > maxDesiredPods {
				maxDesiredPods = measurement.desiredNumRunningPods
			}
		}

		// Ensure we respect min/max bounds
		proposedNumPods := max(
			h.Deployment.MinPods,
			min(
				h.Deployment.MaxPods,
				maxDesiredPods,
			),
		)

		if proposedNumPods < currentNumActivePods {
			return HPAScaleIn, currentNumActivePods - proposedNumPods
		}
	}

	return HPADoNothing, 0
}

func (h *OriginalHPA) GetCPULoadMeasurements() []float64 {
	var cpuMeasurements []float64
	runningPods := h.Deployment.GetRunningPods()

	for _, pod := range runningPods {
		cpuMeasurements = append(cpuMeasurements, h.MetricsServer.GetCPULoad(pod))
	}
	return cpuMeasurements
}

func (h *OriginalHPA) GetMeanCPUUtilization() float64 {
	runningPods := h.Deployment.GetRunningPods()
	if len(runningPods) == 0 {
		return 0
	}

	cpuMeasurements := h.GetCPULoadMeasurements()
	sum := 0.0

	// Calculate CPU utilization percentage for each pod (cpuUsed / cpuReques)
	for i, pod := range runningPods {
		cpuUsed := cpuMeasurements[i]
		cpuRequest := pod.CPURequest

		// Normalize CPU usage by the pod's CPU request to get utilization percentage
		if cpuRequest > 0 {
			cpuUtilization := cpuUsed / cpuRequest
			sum += cpuUtilization
		}
	}

	// Mean CPU utilization across all pods (as percentage of their respective cpuRequests)
	// But we normalize by how many ACTIVE Pods are there (either PodScheduled or PodRunning)
	numActivePods := h.Deployment.GetNumActivePods()
	meanCpuUtilization := sum / float64(numActivePods)
	return meanCpuUtilization
}

func (h *OriginalHPA) getScaleFactor() float64 {
	runningPods := h.Deployment.GetRunningPods()
	if len(runningPods) == 0 {
		return -1
	}

	meanCpuUtilization := h.GetMeanCPUUtilization()

	// Scale factor is the ratio of actual utilization to target utilization
	scaleFactor := meanCpuUtilization / h.cpuThreshold
	return scaleFactor
}
