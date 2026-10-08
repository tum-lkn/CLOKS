package podscheduler

import (
	"fmt"
	"network-simulator/entities"
	"strings"
)

// SchedulingResult represents the outcome of a scheduling decision
type SchedulingResult struct {
	SelectedNode     *entities.Node
	FilterResults    map[string]map[string]string // node -> plugin -> result
	ScoreResults     map[string]map[string]int64  // node -> plugin -> score
	FinalScores      map[string]int64             // node -> final weighted score
	SchedulingStatus string                       // "Success", "Unschedulable", "Error"
	Reason           string                       // Reason for the scheduling decision
}

// NewSchedulingResult creates a new SchedulingResult with initialized maps
func NewSchedulingResult() *SchedulingResult {
	return &SchedulingResult{
		FilterResults: make(map[string]map[string]string),
		ScoreResults:  make(map[string]map[string]int64),
		FinalScores:   make(map[string]int64),
	}
}

// FormatSchedulingResult formats the scheduling result for logging/debugging
func FormatSchedulingResult(result *SchedulingResult) string {
	if result == nil {
		return "No scheduling result"
	}

	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("Status: %s\n", result.SchedulingStatus))
	sb.WriteString(fmt.Sprintf("Reason: %s\n", result.Reason))

	if result.SelectedNode != nil {
		sb.WriteString(fmt.Sprintf("Selected Node: %s\n", result.SelectedNode.Name))
	}

	// Filter results
	if len(result.FilterResults) > 0 {
		sb.WriteString("Filter Results:\n")
		for nodeName, pluginResults := range result.FilterResults {
			sb.WriteString(fmt.Sprintf("  %s: ", nodeName))
			for plugin, result := range pluginResults {
				sb.WriteString(fmt.Sprintf("%s=%s ", plugin, result))
			}
			sb.WriteString("\n")
		}
	}

	// Final scores
	if len(result.FinalScores) > 0 {
		sb.WriteString("Final Scores:\n")
		for nodeName, score := range result.FinalScores {
			sb.WriteString(fmt.Sprintf("  %s: %d\n", nodeName, score))
		}
	}

	return sb.String()
}
