package events

import (
	"network-simulator/entities"
)

type requestAbsArrivalEvent struct {
	BaseEvent
	Request *entities.Request
	Node    *entities.Node // The ID of the node receiving the request
}

// RequestLBArrivalEvent represents a request arriving at a node
type RequestNodeArrivalEvent requestAbsArrivalEvent

// NewRequestLBArrivalEvent creates a new request arrival event
func NewRequestNodeArrivalEvent(time float64, request *entities.Request, node *entities.Node) *RequestNodeArrivalEvent {
	return &RequestNodeArrivalEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
		Node:      node,
	}
}

// RequestLBArrivalEvent represents a request arriving at the LB
type RequestLBArrivalEvent requestAbsArrivalEvent

// NewRequestLBArrivalEvent creates a new request arrival event
func NewRequestLBArrivalEvent(time float64, request *entities.Request) *RequestLBArrivalEvent {
	return &RequestLBArrivalEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
	}
}

// RequestPodArrivalEvent represents a request arriving at a Pod
type RequestPodArrivalEvent struct {
	BaseEvent
	Request *entities.Request
	Pod     *entities.Pod // The ID of the pod receiving the request
}

// NewRequestLBArrivalEvent creates a new request arrival event
func NewRequestPodArrivalEvent(time float64, request *entities.Request, pod *entities.Pod) *RequestPodArrivalEvent {
	return &RequestPodArrivalEvent{
		BaseEvent: BaseEvent{Time: time},
		Request:   request,
		Pod:       pod,
	}
}

// RequestUpstreamEvent represents a trigger to generate an upstream request.
type RequestUpstreamEvent struct {
	BaseEvent
	ParentRequest *entities.Request
	Request       *entities.Request
}

func NewRequestUpstreamEvent(time float64, parentRequest *entities.Request, request *entities.Request) *RequestUpstreamEvent {
	return &RequestUpstreamEvent{
		BaseEvent:     BaseEvent{Time: time},
		ParentRequest: parentRequest,
		Request:       request,
	}
}
