package core

import "network-simulator/events"

// EventQueue implements a priority queue for events
type EventQueue []events.Event

func (eq EventQueue) Len() int            { return len(eq) }
func (eq EventQueue) Less(i, j int) bool  { return eq[i].GetTime() < eq[j].GetTime() }
func (eq EventQueue) Swap(i, j int)       { eq[i], eq[j] = eq[j], eq[i] }
func (eq *EventQueue) Push(x interface{}) { *eq = append(*eq, x.(events.Event)) }
func (eq *EventQueue) Pop() interface{} {
	old := *eq
	n := len(old)
	item := old[n-1]
	old[n-1] = nil
	*eq = old[0 : n-1]
	return item
}
