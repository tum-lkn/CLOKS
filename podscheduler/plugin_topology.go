package podscheduler

import (
	"math"

	"network-simulator/entities"
)

// PodTopologySpreadPlugin ensures pods are spread across nodes
type PodTopologySpreadPlugin struct{}

func (p *PodTopologySpreadPlugin) Name() string {
	return "PodTopologySpread"
}

func (p *PodTopologySpreadPlugin) Weight() int64 {
	return 2 // Higher weight for topology spread
}

func (p *PodTopologySpreadPlugin) Filter(pod *entities.Pod, node *entities.Node) (bool, string) {
	// This plugin only scores, doesn't filter
	return true, ""
}

func (p *PodTopologySpreadPlugin) Score(pod *entities.Pod, node *entities.Node) int64 {
	// Score based on how many pods from the same deployment are already on this node
	// Favor nodes with fewer pods from the same deployment
	podsFromSameDeployment := 0
	for _, activePod := range node.GetActivePods() {
		if activePod.Deployment != nil && pod.Deployment != nil &&
			activePod.Deployment.Name == pod.Deployment.Name {
			podsFromSameDeployment++
		}
	}

	// Higher score for nodes with fewer pods from the same deployment
	score := math.Max(0, 100-float64(podsFromSameDeployment)*20)
	return int64(score)
}

// PodConsolidationPlugin prefers to consolidate pods on fewer nodes
// This is the opposite of PodTopologySpreadPlugin - it favors nodes that already have pods
// to minimize the number of nodes in use and maximize resource consolidation
type PodConsolidationPlugin struct{}

func (p *PodConsolidationPlugin) Name() string {
	return "PodConsolidation"
}

func (p *PodConsolidationPlugin) Weight() int64 {
	return 2 // Same weight as topology spread for balanced consideration
}

func (p *PodConsolidationPlugin) Filter(pod *entities.Pod, node *entities.Node) (bool, string) {
	// This plugin only scores, doesn't filter
	return true, ""
}

func (p *PodConsolidationPlugin) Score(pod *entities.Pod, node *entities.Node) int64 {
	// Score based on how many pods are already on this node
	// Higher score for nodes with more existing pods (consolidation)
	totalPodsOnNode := node.GetNumActivePods()

	// Also consider pods from the same deployment for even better consolidation
	podsFromSameDeployment := 0
	for _, activePod := range node.GetActivePods() {
		if activePod.Deployment != nil && pod.Deployment != nil &&
			activePod.Deployment.Name == pod.Deployment.Name {
			podsFromSameDeployment++
		}
	}

	// Base score increases with total pods on node (consolidation preference)
	baseScore := float64(totalPodsOnNode * 10)

	// Bonus for having pods from the same deployment (affinity)
	affinityBonus := float64(podsFromSameDeployment * 15)

	// Cap the score at 100
	finalScore := math.Min(100, baseScore+affinityBonus)

	return int64(finalScore)
}
