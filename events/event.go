package events

// Event defines the interface for all simulation events
type Event interface {
	GetTime() float64 // Returns the scheduled time for the event
}

// BaseEvent provides a common structure for all events
type BaseEvent struct {
	Time     float64 // The simulation time at which the event occurs
	Priority int     // The priority of the Event, used for add
}

// GetTime returns the event time
func (e *BaseEvent) GetTime() float64 {
	return e.Time
}

// GetPriority returns the event time
func (e *BaseEvent) GetPriority() int {
	return e.Priority
}
