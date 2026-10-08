package events

import "network-simulator/entities"

// UpstreamTriggerCheckEvent represents a check for whether upstream calls should be triggered
// This event is scheduled during task processing to check trigger points
type UpstreamTriggerCheckEvent struct {
	BaseEvent
	Request *entities.Request // The request being processed
	Pod     *entities.Pod     // The pod processing the request
}

// NewUpstreamTriggerCheckEvent creates a new upstream trigger check event
func NewUpstreamTriggerCheckEvent(time float64, request *entities.Request, pod *entities.Pod) *UpstreamTriggerCheckEvent {
	return &UpstreamTriggerCheckEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
		Pod:       pod,
	}
}
