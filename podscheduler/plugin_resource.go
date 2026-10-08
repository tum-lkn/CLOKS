package podscheduler

import (
	"network-simulator/entities"
)

// NodeResourcesFitPlugin checks if the node has enough resources for the pod
type NodeResourcesFitPlugin struct{}

func (p *NodeResourcesFitPlugin) Name() string {
	return "NodeResourcesFit"
}

func (p *NodeResourcesFitPlugin) Weight() int64 {
	return 1
}

func (p *NodeResourcesFitPlugin) Filter(pod *entities.Pod, node *entities.Node) (bool, string) {
	// Check if node has enough available CPU capacity
	if node.AvailableCPUCapacity < pod.CPURequest {
		return false, "Insufficient CPU resources"
	}
	return true, "Sufficient CPU resources"

}

func (p *NodeResourcesFitPlugin) Score(pod *entities.Pod, node *entities.Node) int64 {
	// This is just a filtering plugin
	return 0
}

type HighestCPUAvailabilityPlugin struct{}

func (p *HighestCPUAvailabilityPlugin) Name() string {
	return "HighestCPUAvailability"
}

func (p *HighestCPUAvailabilityPlugin) Weight() int64 {
	return 1
}

func (p *HighestCPUAvailabilityPlugin) Filter(pod *entities.Pod, node *entities.Node) (bool, string) {
	// Check if node has enough available CPU capacity
	if node.AvailableCPUCapacity < pod.CPURequest {
		return false, "Insufficient CPU resources"
	}
	return true, "Sufficient CPU resources"
}

func (p *HighestCPUAvailabilityPlugin) Score(pod *entities.Pod, node *entities.Node) int64 {
	// This is a filtering and scoring plugin
	availablePercentage := node.AvailableCPUCapacity / node.TotalCPUCapacity
	return int64(availablePercentage * 100)
}
