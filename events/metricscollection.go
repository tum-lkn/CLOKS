package events

import "network-simulator/entities"

type MetricsCollectionEvent struct {
	BaseEvent
	MetricsServer *entities.MetricsServer
}

func NewMetricsCollectionEvent(time float64, m *entities.MetricsServer) *MetricsCollectionEvent {
	return &MetricsCollectionEvent{
		BaseEvent:     BaseEvent{Time: time},
		MetricsServer: m,
	}
}

type KubeletCollectionEvent struct {
	BaseEvent
	Kubelet *entities.Kubelet
}

func NewKubeletCollectionEvent(time float64, k *entities.Kubelet) *KubeletCollectionEvent {
	return &KubeletCollectionEvent{
		BaseEvent: BaseEvent{Time: time},
		Kubelet:   k,
	}
}
