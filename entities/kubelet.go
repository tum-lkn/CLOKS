package entities

type Kubelet struct {
	node                      *Node
	secondLastMeasurements    map[*Pod]*PodMeasurement
	firstLastMeasurements     map[*Pod]*PodMeasurement // This is the more recent one
	secondLastMeasurementTime float64
	firstLastMeasurementTime  float64
	samplingPeriod            float64
}

// NewKubelet creates and returns a new Kubelet object.
func NewKubelet(node *Node, samplingPeriod float64) *Kubelet {
	return &Kubelet{
		node:                      node,
		secondLastMeasurements:    make(map[*Pod]*PodMeasurement), // Initialize the measurements map
		firstLastMeasurements:     make(map[*Pod]*PodMeasurement), // Initialize the measurements map
		secondLastMeasurementTime: 0,                              // Default to 0
		firstLastMeasurementTime:  0,                              // Default to 0
		samplingPeriod:            samplingPeriod,                 // Use the provided sampling period
	}
}

func (k *Kubelet) GetSamplingPeriod() float64 {
	return k.samplingPeriod
}

func (k *Kubelet) GetAllPodMeasurements() map[*Pod]*PodMeasurement {
	return k.firstLastMeasurements
}

func (k *Kubelet) GetAllPodMeasurementsToJson() map[string]float64 {
	measurements := make(map[string]float64)

	for pod, meas := range k.firstLastMeasurements {
		measurements[pod.Name] = meas.podSeconds
	}

	return measurements

}

func (k *Kubelet) RecordAllPodMeasurements(simTime float64) {
	for _, p := range k.node.GetRunningPods() {
		k.RecordPodMeasurement(p, simTime)
	}

	k.secondLastMeasurementTime = k.firstLastMeasurementTime
	k.firstLastMeasurementTime = simTime
}

// RecordPodMeasurement records a new measurement for a specific Pod in the Kubelet.
func (k *Kubelet) RecordPodMeasurement(p *Pod, simTime float64) {
	// Initialize the measurement slice for the Pod if it doesn't exist

	newMeasurement := NewPodMeasurement(
		simTime, p.Measure())

	k.secondLastMeasurements[p] = k.firstLastMeasurements[p]
	k.firstLastMeasurements[p] = newMeasurement
}
