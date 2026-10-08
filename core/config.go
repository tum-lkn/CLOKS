package core

import (
	"fmt"
	"network-simulator/entities"
	"os"

	"github.com/knadh/koanf/parsers/yaml"
	"github.com/knadh/koanf/providers/file"
	"github.com/knadh/koanf/v2"
)

type RequestsConfig struct {
	IAT IATConfig `koanf:"iat"`
}

type IATConfig struct {
	EndTime  float64         `koanf:"end_time"`
	ID       string          `koanf:"id"`
	Profiles []ProfileConfig `koanf:"profiles"`
}

type ProfileConfig struct {
	Rates             []float64 `koanf:"rates"`
	ChangePoints      []float64 `koanf:"change_points"`
	Distribution      string    `koanf:"iat_distribution"`
	IATJitterMs       *float64  `koanf:"iat_jitter_ms"`
	RampUpPeriodInSec int       `koanf:"ramp_up_period_in_sec"`
	MemoryRequestMiB  int       `koanf:"memory_request_MiB"`
	Name              string    `koanf:"name"`
	ServiceName       string    `koanf:"service_name"`
}

type InfluxConfig struct {
	Enabled   bool   `koanf:"enabled"`
	ServerURL string `koanf:"server_url"`
	TokenFile string `koanf:"token_file"`
	Database  string `koanf:"database"`
}

type InfraConfig struct {
	NumNodes         int          `koanf:"num_nodes"`
	CPU              CPUConfig    `koanf:"cpu"`
	InterNodeLatency [][]float64  `koanf:"inter_node_latency,omitempty"`
	NodeConfigs      []NodeConfig `koanf:"node_configs,omitempty"` // Per-node configuration (required)
}

type NodeConfig struct {
	Name     string  `koanf:"name"`                // Descriptive name for the node group
	NodeIDs  []int   `koanf:"node_ids"`            // List of node IDs that use this configuration
	Template string  `koanf:"template,omitempty"`  // VM template name (e.g., "m5.large")
	NumCPUs  int     `koanf:"num_cpus,omitempty"`  // Number of CPUs (override template or direct specification)
	MemoryGB float64 `koanf:"memory_gb,omitempty"` // Memory in GB (override template or direct specification)
}

type VMTemplatesConfig struct {
	VMTemplates []VMTemplate `koanf:"vm_templates"`
}

type VMTemplate struct {
	Name        string  `koanf:"name"`
	Description string  `koanf:"description"`
	NumCPUs     int     `koanf:"num_cpus"`
	MemoryGB    float64 `koanf:"memory_gb"`
}

type CPUConfig struct {
	SchedulingAlgorithm string `koanf:"scheduling_algorithm"`
}

// LoadVMTemplates loads VM templates from a YAML file
func LoadVMTemplates(templatePath string) (map[string]VMTemplate, error) {
	templates := make(map[string]VMTemplate)

	// Check if template file exists
	if _, err := os.Stat(templatePath); os.IsNotExist(err) {
		// Template file doesn't exist, return empty map (not an error)
		return templates, nil
	}

	var templatesConfig VMTemplatesConfig
	k := koanf.New(".")

	if err := k.Load(file.Provider(templatePath), yaml.Parser()); err != nil {
		return nil, fmt.Errorf("failed to load VM templates from %s: %w", templatePath, err)
	}

	if err := k.Unmarshal("", &templatesConfig); err != nil {
		return nil, fmt.Errorf("failed to parse VM templates from %s: %w", templatePath, err)
	}

	// Convert slice to map for easier lookup
	for _, template := range templatesConfig.VMTemplates {
		templates[template.Name] = template
	}

	return templates, nil
}

// ValidateInterNodeLatency validates the inter-node latency matrix
func (cfg *InfraConfig) ValidateInterNodeLatency() error {
	// If we have only one node, no latency matrix is required
	if cfg.NumNodes == 1 {
		return nil
	}

	// For multiple nodes, latency matrix is required
	if cfg.InterNodeLatency == nil {
		return fmt.Errorf("inter_node_latency matrix is required when num_nodes > 1")
	}

	// Check matrix dimensions
	if len(cfg.InterNodeLatency) != cfg.NumNodes {
		return fmt.Errorf("inter_node_latency matrix must have %d rows, got %d", cfg.NumNodes, len(cfg.InterNodeLatency))
	}

	for i, row := range cfg.InterNodeLatency {
		if len(row) != cfg.NumNodes {
			return fmt.Errorf("inter_node_latency matrix row %d must have %d columns, got %d", i, cfg.NumNodes, len(row))
		}

		// Check that all entries are positive
		for j, latency := range row {
			if latency <= 0 {
				return fmt.Errorf("inter_node_latency[%d][%d] must be positive, got %f", i, j, latency)
			}
		}
	}

	return nil
}

// GetNodeCPUCount returns the number of CPUs for a specific node
func (cfg *InfraConfig) GetNodeCPUCount(nodeID int, vmTemplates map[string]VMTemplate) int {
	// If NodeConfigs is specified, use per-node configuration
	if len(cfg.NodeConfigs) > 0 {
		for _, nodeConfig := range cfg.NodeConfigs {
			// Check if this nodeID is in the NodeIDs list for this config
			for _, id := range nodeConfig.NodeIDs {
				if id == nodeID {
					// If Template is specified, use template values
					if nodeConfig.Template != "" {
						if template, exists := vmTemplates[nodeConfig.Template]; exists {
							// Override with explicit NumCPUs if specified
							if nodeConfig.NumCPUs > 0 {
								return nodeConfig.NumCPUs
							}
							return template.NumCPUs
						}
						// Template not found, fall back to explicit config
					}
					return nodeConfig.NumCPUs
				}
			}
		}
		// If node not found in configs, return 0 (error case)
		return 0
	}

	// NodeConfigs is required - return 0 to indicate misconfiguration
	return 0
}

// GetNodeMemoryGB returns the memory in GB for a specific node
func (cfg *InfraConfig) GetNodeMemoryGB(nodeID int, vmTemplates map[string]VMTemplate) float64 {
	// If NodeConfigs is specified, use per-node configuration
	if len(cfg.NodeConfigs) > 0 {
		for _, nodeConfig := range cfg.NodeConfigs {
			// Check if this nodeID is in the NodeIDs list for this config
			for _, id := range nodeConfig.NodeIDs {
				if id == nodeID {
					// If Template is specified, use template values
					if nodeConfig.Template != "" {
						if template, exists := vmTemplates[nodeConfig.Template]; exists {
							// Override with explicit MemoryGB if specified
							if nodeConfig.MemoryGB > 0 {
								return nodeConfig.MemoryGB
							}
							return template.MemoryGB
						}
						// Template not found, fall back to explicit config
					}
					return nodeConfig.MemoryGB
				}
			}
		}
		// If node not found in configs, return 0 (error case)
		return 0
	}

	// Fall back to legacy configuration (assuming a default value)
	return 4.0 // Default 4GB if not specified
}

// ValidateNodeConfigs validates the node configurations
func (cfg *InfraConfig) ValidateNodeConfigs(vmTemplates map[string]VMTemplate) error {
	// If NodeConfigs is specified, validate it
	if len(cfg.NodeConfigs) > 0 {
		nodeIDs := make(map[int]bool)
		totalNodesConfigured := 0

		for _, nodeConfig := range cfg.NodeConfigs {
			// Validate that name is provided
			if nodeConfig.Name == "" {
				return fmt.Errorf("node configuration must have a name")
			}

			// Validate that NodeIDs list is not empty
			if len(nodeConfig.NodeIDs) == 0 {
				return fmt.Errorf("node configuration '%s' must specify at least one node_id", nodeConfig.Name)
			}

			// Validate template if specified
			if nodeConfig.Template != "" {
				if _, exists := vmTemplates[nodeConfig.Template]; !exists {
					return fmt.Errorf("node configuration '%s' references unknown VM template '%s'", nodeConfig.Name, nodeConfig.Template)
				}
			}

			// Validate that we have either a template or explicit CPU configuration
			if nodeConfig.Template == "" && nodeConfig.NumCPUs <= 0 {
				return fmt.Errorf("node configuration '%s' must specify either a template or num_cpus > 0", nodeConfig.Name)
			}

			// If using template, CPU count validation will be done through template
			if nodeConfig.Template == "" {
				// Validate CPU count for explicit configuration
				if nodeConfig.NumCPUs <= 0 {
					return fmt.Errorf("node configuration '%s' must have at least 1 CPU, got %d", nodeConfig.Name, nodeConfig.NumCPUs)
				}
			}

			// Check each node ID in the list
			for _, nodeID := range nodeConfig.NodeIDs {
				// Check node ID range
				if nodeID < 0 || nodeID >= cfg.NumNodes {
					return fmt.Errorf("node_id %d in configuration '%s' is out of range [0, %d)", nodeID, nodeConfig.Name, cfg.NumNodes)
				}

				// Check for duplicates
				if nodeIDs[nodeID] {
					return fmt.Errorf("duplicate node_id %d found in configurations", nodeID)
				}
				nodeIDs[nodeID] = true
				totalNodesConfigured++
			}
		}

		// Check that all node IDs from 0 to NumNodes-1 are configured
		if totalNodesConfigured != cfg.NumNodes {
			return fmt.Errorf("expected configuration for %d nodes, but got %d", cfg.NumNodes, totalNodesConfigured)
		}

		for i := 0; i < cfg.NumNodes; i++ {
			if !nodeIDs[i] {
				return fmt.Errorf("missing configuration for node_id %d", i)
			}
		}
	} else {
		// NodeConfigs is required
		return fmt.Errorf("node_configs must be specified in infrastructure configuration")
	}

	return nil
}

type ServicesConfig struct {
	Services []ServiceConfig `koanf:"services"`
}

type ServiceConfig struct {
	Name                   string                           `koanf:"name"`
	LBPolicy               string                           `koanf:"lb_policy"`
	MinReplicas            int                              `koanf:"min_replicas"`
	MaxReplicas            int                              `koanf:"max_replicas"`
	Port                   int                              `koanf:"port"`
	PodReadyDelay          float64                          `koanf:"pod_ready_delay"`
	PodDeletionGracePeriod float64                          `koanf:"pod_deletion_grace_period"`
	RequestTimeoutLimit    float64                          `koanf:"request_timeout"`
	RequestProfiles        []entities.RequestProfileConfig  `koanf:"request_profiles"`
	CpuNumWorkers          int                              `koanf:"cpu_num_workers"` // Number of worker processes (Gunicorn-style)
	CpuNumThreads          int                              `koanf:"cpu_num_threads"` // Number of threads per worker
	CpuRequest             int                              `koanf:"cpu_request"`     // CPU limit in millicores (e.g., 500 = 0.5 CPU, 1000 = 1 CPU)
	CpuLimit               int                              `koanf:"cpu_limit"`       // CPU limit in millicores (e.g., 500 = 0.5 CPU, 1000 = 1 CPU)
	Upstream               []entities.UpstreamServiceConfig `koanf:"upstream"`
}

type HPAConfig struct {
	HPA []HPAServiceConfig `koanf:"hpa"`
}

type HPAServiceConfig struct {
	ServiceName          string  `koanf:"service_name"`
	Mode                 string  `koanf:"mode"`
	Endpoint             string  `koanf:"endpoint"`
	RemoteTimeoutSeconds int     `koanf:"remote_timeout_seconds"`
	Threshold            float64 `koanf:"threshold"`
	SynchPeriod          float64 `koanf:"synch_period"`
	GracePeriodScaleIn   float64 `koanf:"grace_period_scale_in"`
	GracePeriodScaleOut  float64 `koanf:"grace_period_scale_out"`
}

type PodSchedulerConfig struct {
	Mode                 string `koanf:"mode"`                   // "local" or "remote"
	SchedulingPolicy     string `koanf:"scheduling_policy"`      // "default", "consolidation", "highest_cpu"
	Endpoint             string `koanf:"endpoint"`               // For remote mode
	RemoteTimeoutSeconds int    `koanf:"remote_timeout_seconds"` // HTTP timeout for remote mode
}

// ValidateServicesDAG validates the service configuration for:
// 1. No missing service references
// 2. No circular dependencies (DAG property)
// 3. Valid upstream configuration parameters
func (cfg *ServicesConfig) ValidateServicesDAG() error {
	// Build service name set for validation
	serviceNames := make(map[string]bool)
	for _, svc := range cfg.Services {
		serviceNames[svc.Name] = true
	}

	// Validate each service's upstream configuration
	for _, svc := range cfg.Services {
		if len(svc.RequestProfiles) == 0 {
			return fmt.Errorf("service '%s': request_profiles must be specified and non-empty", svc.Name)
		}

		seenProfiles := make(map[string]bool)
		for i, profile := range svc.RequestProfiles {
			if profile.Name == "" {
				return fmt.Errorf("service '%s' request_profiles[%d]: name must be non-empty", svc.Name, i)
			}
			if profile.RequestDuration <= 0 {
				return fmt.Errorf("service '%s' request_profiles[%d]: request_duration must be > 0 (milliseconds), got %f", svc.Name, i, profile.RequestDuration)
			}
			if seenProfiles[profile.Name] {
				return fmt.Errorf("service '%s': duplicate request profile '%s'", svc.Name, profile.Name)
			}
			seenProfiles[profile.Name] = true
		}

		for i, upstream := range svc.Upstream {
			// Check that upstream service exists
			if !serviceNames[upstream.UpstreamServiceName] {
				return fmt.Errorf("service '%s' references unknown upstream service '%s'", svc.Name, upstream.UpstreamServiceName)
			}

			// Check for self-reference
			if upstream.UpstreamServiceName == svc.Name {
				return fmt.Errorf("service '%s' cannot reference itself as upstream", svc.Name)
			}

			// Validate trigger_at is in valid range
			if upstream.TriggerAt < 0.0 || upstream.TriggerAt > 1.0 {
				return fmt.Errorf("service '%s' upstream[%d]: trigger_at must be between 0.0 and 1.0, got %f", svc.Name, i, upstream.TriggerAt)
			}

			// Validate probability is in valid range
			if upstream.Probability < 0.0 || upstream.Probability > 1.0 {
				return fmt.Errorf("service '%s' upstream[%d]: probability must be between 0.0 and 1.0, got %f", svc.Name, i, upstream.Probability)
			}

			// Blocking upstream calls must block at the request start.
			if upstream.Blocking && upstream.BlockAt != 0.0 {
				return fmt.Errorf("service '%s' upstream[%d]: block_at must be 0.0 when blocking is true, got %f", svc.Name, i, upstream.BlockAt)
			}

		}
	}

	// Check for cycles using DFS
	visited := make(map[string]bool)
	recStack := make(map[string]bool)

	var hasCycle func(string) bool
	hasCycle = func(serviceName string) bool {
		visited[serviceName] = true
		recStack[serviceName] = true

		// Find the service config
		for _, svc := range cfg.Services {
			if svc.Name == serviceName {
				// Check all upstream dependencies
				for _, upstream := range svc.Upstream {
					if !visited[upstream.UpstreamServiceName] {
						if hasCycle(upstream.UpstreamServiceName) {
							return true
						}
					} else if recStack[upstream.UpstreamServiceName] {
						// Found a cycle
						return true
					}
				}
				break
			}
		}

		recStack[serviceName] = false
		return false
	}

	// Check for cycles starting from each service
	for _, svc := range cfg.Services {
		if !visited[svc.Name] {
			if hasCycle(svc.Name) {
				return fmt.Errorf("circular dependency detected in service configuration involving '%s'", svc.Name)
			}
		}
	}

	return nil
}
