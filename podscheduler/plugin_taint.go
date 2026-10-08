package podscheduler

import (
	"fmt"

	"network-simulator/entities"
)

// TaintTolerationPlugin handles node taints and pod tolerations
type TaintTolerationPlugin struct{}

func (p *TaintTolerationPlugin) Name() string {
	return "TaintToleration"
}

func (p *TaintTolerationPlugin) Weight() int64 {
	return 3 // High weight for taint toleration
}

func (p *TaintTolerationPlugin) Filter(pod *entities.Pod, node *entities.Node) (bool, string) {
	// Simplified: check node status
	if node.Status != entities.NodeRunning {
		return false, fmt.Sprintf("Node is not in Running state: %s", node.Status)
	}
	return true, ""
}

func (p *TaintTolerationPlugin) Score(pod *entities.Pod, node *entities.Node) int64 {
	// Higher score for healthy running nodes
	if node.Status == entities.NodeRunning {
		return 100
	}
	return 0
}
