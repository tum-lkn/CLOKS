package events

import "network-simulator/entities"

type PodCreationEvent struct {
	BaseEvent
	Deployment *entities.Deployment
}

func NewPodCreationEvent(time float64, d *entities.Deployment) *PodCreationEvent {
	return &PodCreationEvent{
		BaseEvent:  BaseEvent{Time: time},
		Deployment: d,
	}
}

type PodTerminationEvent struct {
	BaseEvent
	Deployment *entities.Deployment
}

func NewPodTerminationEvent(time float64, d *entities.Deployment) *PodTerminationEvent {
	return &PodTerminationEvent{
		BaseEvent:  BaseEvent{Time: time},
		Deployment: d,
	}
}

type PodKillEvent struct {
	BaseEvent
	Deployment *entities.Deployment
	Pod        *entities.Pod
}

func NewPodKillEvent(time float64, d *entities.Deployment, p *entities.Pod) *PodKillEvent {
	return &PodKillEvent{
		BaseEvent:  BaseEvent{Time: time},
		Deployment: d,
		Pod:        p,
	}
}

// Phase 3 — PodReadyEvent: represents "containers are ready, pod goes Running".
type PodReadyEvent struct {
	BaseEvent
	Pod *entities.Pod
}

func NewPodReadyEvent(time float64, p *entities.Pod) *PodReadyEvent {
	return &PodReadyEvent{
		BaseEvent: BaseEvent{Time: time},
		Pod:       p,
	}
}
