package entities

import "network-simulator/simrand"

type MetricsServer struct {
	kubelets               []*Kubelet
	samplingPeriod         float64
	secondLastMeasurements map[*Pod]*PodMeasurement
	firstLastMeasurements  map[*Pod]*PodMeasurement // This is the more recent one
}

func NewMetricsServer(kubelets []*Kubelet, samplingPeriod float64) *MetricsServer {
	return &MetricsServer{
		kubelets:               kubelets,
		samplingPeriod:         samplingPeriod,
		secondLastMeasurements: make(map[*Pod]*PodMeasurement),
		firstLastMeasurements:  make(map[*Pod]*PodMeasurement),
	}
}

func (m *MetricsServer) GetAllPodMeasurements() map[*Pod]*PodMeasurement {
	return m.firstLastMeasurements
}

func (m *MetricsServer) GetAllPodMeasurementsToJson() map[string]float64 {
	measurements := make(map[string]float64)

	for pod, meas := range m.firstLastMeasurements {
		measurements[pod.Name] = meas.podSeconds
	}

	return measurements
}

func (m *MetricsServer) GetCPULoad(p *Pod) float64 {

	// TOOD We might need to do a check to see if the Pod is being tracked by
	// the MetricsServer

	// kubeletSamplingPeriod := m.kubelets[0].samplingPeriod

	if _, exists := m.firstLastMeasurements[p]; !exists {
		return 0
	}

	if _, exists := m.secondLastMeasurements[p]; !exists {
		return m.firstLastMeasurements[p].podSeconds / m.firstLastMeasurements[p].time
	}

	return (m.firstLastMeasurements[p].podSeconds - m.secondLastMeasurements[p].podSeconds) / (m.firstLastMeasurements[p].time - m.secondLastMeasurements[p].time)

}

func (m *MetricsServer) GetSamplingPeriod() float64 {

	// Add a jitter to the Sampling period of the Metrics Server
	jitter := simrand.Float64() * 3
	// jitter := 0.0

	return m.samplingPeriod + jitter
}

// func (m *MetricsServer) RecordAllPodMeasurements(simTime float64) {

// 	for _, kubelet := range m.kubelets {
// 		metrics := kubelet.GetAllPodMeasurements()

// 		for pod, newMeasurement := range metrics {
// 			// Update second last and first last measurements
// 			if prev, exists := m.firstLastMeasurements[pod]; exists {
// 				m.secondLastMeasurements[pod] = prev
// 			}
// 			m.firstLastMeasurements[pod] = newMeasurement
// 		}
// 	}
// }

func (m *MetricsServer) RecordAllPodMeasurements(simTime float64) {
	for _, kubelet := range m.kubelets {
		metrics := kubelet.GetAllPodMeasurements()

		for pod, newMeasurement := range metrics {
			if prev, exists := m.firstLastMeasurements[pod]; exists {
				if newMeasurement.time != prev.time {
					m.secondLastMeasurements[pod] = prev
					m.firstLastMeasurements[pod] = newMeasurement
				}
				// If the time is the same, do not update measurements
			} else {
				m.firstLastMeasurements[pod] = newMeasurement
			}
		}
	}
}
