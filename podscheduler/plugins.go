package podscheduler

import "network-simulator/entities"

// SchedulingPlugin defines the interface for individual scheduling plugins
type SchedulingPlugin interface {
	Name() string
	Filter(pod *entities.Pod, node *entities.Node) (bool, string) // returns (passed, reason)
	Score(pod *entities.Pod, node *entities.Node) int64           // returns score (0-100)
	Weight() int64                                                // plugin weight for final scoring
}

// PodScheduler defines the interface for pod scheduling policies
type PodScheduler interface {
	SchedulePod(pod *entities.Pod, nodes []*entities.Node) *SchedulingResult
}
