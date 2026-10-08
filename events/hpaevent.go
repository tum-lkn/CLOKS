package events

import "network-simulator/entities"

type HPAEvent struct {
	BaseEvent
	HPA entities.HPA
}

func NewHPAEvent(time float64, h entities.HPA) *HPAEvent {
	return &HPAEvent{
		BaseEvent: BaseEvent{Time: time},
		HPA:       h,
	}
}
