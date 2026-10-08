package events

import "network-simulator/entities"

type CounterEvent struct {
	BaseEvent
	Counter *entities.RCTCounter
}

func NewCounterEvent(time float64, c *entities.RCTCounter) *CounterEvent {
	return &CounterEvent{
		BaseEvent: BaseEvent{Time: time},
		Counter:   c,
	}
}
