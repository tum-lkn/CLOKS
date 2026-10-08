package podscheduler

import (
	"fmt"
	"sort"

	"network-simulator/entities"
)

// KubernetesScheduler implements the Kubernetes-style scheduling algorithm
// It follows the same phases as the real Kubernetes scheduler:
// 1. Filtering (eliminates unsuitable nodes)
// 2. Scoring (assigns scores to remaining nodes)
// 3. Selection (picks the best node)
type KubernetesScheduler struct {
	plugins []SchedulingPlugin
}

// RegisterPlugin adds a plugin to the scheduler
func (s *KubernetesScheduler) RegisterPlugin(plugin SchedulingPlugin) {
	s.plugins = append(s.plugins, plugin)
}

// SchedulePod implements the full Kubernetes scheduling algorithm
// The function SchedulePod only gives a recommendation for which node the pod should be running on,
// but doesn't actually do the assignment and the state transition.
// These things happen in the PodCreationEvent handler.
func (s *KubernetesScheduler) SchedulePod(pod *entities.Pod, nodes []*entities.Node) *SchedulingResult {
	result := NewSchedulingResult()

	if len(nodes) == 0 {
		result.SchedulingStatus = "Unschedulable"
		result.Reason = "No nodes available"
		return result
	}

	// Phase 1: Filtering
	feasibleNodes := s.filterPhase(pod, nodes, result)

	if len(feasibleNodes) == 0 {
		result.SchedulingStatus = "Unschedulable"
		result.Reason = "No nodes passed the filtering phase"
		return result
	}

	// Phase 2: Scoring
	s.scorePhase(pod, feasibleNodes, result)

	// Phase 3: Selection
	selectedNode := s.selectNode(feasibleNodes, result)

	if selectedNode == nil {
		result.SchedulingStatus = "Error"
		result.Reason = "Failed to select a node"
		return result
	}

	// Prepare the scheduling result for reporting
	result.SelectedNode = selectedNode
	result.SchedulingStatus = "Success"
	result.Reason = fmt.Sprintf("Successfully scheduled to %s", selectedNode.Name)

	return result
}

// filterPhase runs all filter plugins and returns nodes that pass all filters
func (s *KubernetesScheduler) filterPhase(pod *entities.Pod, nodes []*entities.Node, result *SchedulingResult) []*entities.Node {
	feasibleNodes := make([]*entities.Node, 0)

	for _, node := range nodes {
		result.FilterResults[node.Name] = make(map[string]string)
		passed := true

		for _, plugin := range s.plugins {
			pluginPassed, reason := plugin.Filter(pod, node)
			if pluginPassed {
				result.FilterResults[node.Name][plugin.Name()] = "passed"
			} else {
				result.FilterResults[node.Name][plugin.Name()] = reason
				passed = false
				break
			}
		}

		if passed {
			feasibleNodes = append(feasibleNodes, node)
		}
	}

	return feasibleNodes
}

// scorePhase runs all scoring plugins and calculates final weighted scores
func (s *KubernetesScheduler) scorePhase(pod *entities.Pod, nodes []*entities.Node, result *SchedulingResult) {
	for _, node := range nodes {
		result.ScoreResults[node.Name] = make(map[string]int64)
		var finalScore int64 = 0
		var totalWeight int64 = 0

		for _, plugin := range s.plugins {
			score := plugin.Score(pod, node)
			weight := plugin.Weight()

			result.ScoreResults[node.Name][plugin.Name()] = score
			finalScore += score * weight
			totalWeight += weight
		}

		// Normalize the final score
		if totalWeight > 0 {
			result.FinalScores[node.Name] = finalScore / totalWeight
		}
	}
}

// selectNode picks the node with the highest final score
func (s *KubernetesScheduler) selectNode(nodes []*entities.Node, result *SchedulingResult) *entities.Node {
	if len(nodes) == 0 {
		return nil
	}

	// Sort nodes by final score (descending)
	sort.Slice(nodes, func(i, j int) bool {
		return result.FinalScores[nodes[i].Name] > result.FinalScores[nodes[j].Name]
	})

	return nodes[0]
}

// NewKubernetesScheduler creates a new Kubernetes scheduler with default plugins
func NewKubernetesScheduler() *KubernetesScheduler {
	scheduler := &KubernetesScheduler{
		plugins: make([]SchedulingPlugin, 0),
	}

	// Register default plugins (similar to Kubernetes default scheduler)
	scheduler.RegisterPlugin(&NodeResourcesFitPlugin{})
	scheduler.RegisterPlugin(&PodTopologySpreadPlugin{})
	scheduler.RegisterPlugin(&TaintTolerationPlugin{})

	return scheduler
}

// NewKubernetesConsolidationScheduler creates a scheduler optimized for pod consolidation
func NewKubernetesConsolidationScheduler() *KubernetesScheduler {
	scheduler := &KubernetesScheduler{
		plugins: make([]SchedulingPlugin, 0),
	}

	// Register plugins with consolidation preference instead of topology spread
	scheduler.RegisterPlugin(&NodeResourcesFitPlugin{})
	scheduler.RegisterPlugin(&PodConsolidationPlugin{}) // Use consolidation instead of spread
	scheduler.RegisterPlugin(&TaintTolerationPlugin{})

	return scheduler
}

// NewHighestCPUAvailabilityScheduler creates a scheduler optimized for highest CPU availability
func NewHighestCPUAvailabilityScheduler() *KubernetesScheduler {
	scheduler := &KubernetesScheduler{
		plugins: make([]SchedulingPlugin, 0),
	}

	// Register plugins optimized for scheduling on nodes with highest CPU availability
	// This scheduler is ideal for:
	// - Clusters with heterogeneous node sizes (mixed small/large nodes)
	// - Workloads that may need to scale up and require substantial resources
	// - Scenarios where you want to maximize utilization of high-capacity nodes
	// - Performance-sensitive applications that benefit from resource headroom
	scheduler.RegisterPlugin(&NodeResourcesFitPlugin{})       // Basic resource filtering
	scheduler.RegisterPlugin(&HighestCPUAvailabilityPlugin{}) // Primary scheduling criterion (weight: 3)
	scheduler.RegisterPlugin(&TaintTolerationPlugin{})        // Node health check (weight: 3)

	return scheduler
}
