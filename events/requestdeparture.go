package events

import (
	"network-simulator/entities"
)

// RequestLBDepartureEvent represents a request leaving a node
type RequestLBDepartureEvent struct {
	BaseEvent
	Request *entities.Request
	Node    *entities.Node // The Node completing the request
	Pod     *entities.Pod  // The Pod completing the request
}

// NewRequestDepartureEvent creates a new request departure event
func NewRequestLBDepartureEvent(time float64, request *entities.Request, pod *entities.Pod) *RequestLBDepartureEvent {
	return &RequestLBDepartureEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
		Pod:       pod,
	}
}

// RequestPodDepartureEvent represents a request leaving a node
type RequestPodDepartureEvent struct {
	BaseEvent
	Request *entities.Request
	Node    *entities.Node // The Node completing the request
	Pod     *entities.Pod  // The Pod completing the request
}

// NewRequestDepartureEvent creates a new request departure event
func NewRequestPodDepartureEvent(time float64, request *entities.Request, pod *entities.Pod) *RequestPodDepartureEvent {
	return &RequestPodDepartureEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
		Pod:       pod,
	}
}

// The timeout happens at the Load Balancer
type RequestLBTimeoutEvent struct {
	BaseEvent
	Request *entities.Request
}

func NewRequestLBTimeoutEvent(time float64, request *entities.Request) *RequestLBTimeoutEvent {
	return &RequestLBTimeoutEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
	}
}

// RequestUpstreamCompletionEvent is emitted when an upstream request finishes.
type RequestUpstreamCompletionEvent struct {
	BaseEvent
	ParentRequest *entities.Request
	Request       *entities.Request
}

func NewRequestUpstreamCompletionEvent(time float64, parentRequest *entities.Request, request *entities.Request) *RequestUpstreamCompletionEvent {
	return &RequestUpstreamCompletionEvent{
		BaseEvent:     BaseEvent{Time: time},
		ParentRequest: parentRequest,
		Request:       request,
	}
}
