package core

import (
	"container/heap"
	"fmt"
	"log"
	"network-simulator/entities"
	"network-simulator/events"
	"network-simulator/logger"
	"network-simulator/metrics"
	"network-simulator/models"
	"network-simulator/podscheduler"
	"network-simulator/simrand"
	"os"
	"sync"

	"github.com/knadh/koanf/parsers/yaml"
	"github.com/knadh/koanf/providers/file"
	"github.com/knadh/koanf/v2"

	"github.com/chigopher/pathlib"
)

// SimulatorInterface is an interface for interacting with the simulator
type SimulatorInterface interface {
	ScheduleEvent(event events.Event)
	GetSimTime() float64

	Pause()
	Resume()
	Run()

	IsPaused() bool

	GetNodes() []*entities.Node
	GetKubelets() map[*entities.Node]*entities.Kubelet
	GetMetricsServer() *entities.MetricsServer
	GetHPAs() map[string]entities.HPA
	GetProfiles() map[string]*entities.InterArrivalTime
	GetCounters() map[string]*entities.RCTCounter

	// Component Specific Functions
	GetLBDelay() float64 // Assume Symmetric Delay between Load Balancer and Pod
	GetLB(profileName string) entities.LoadBalancer
	GetLBByService(serviceName string) entities.LoadBalancer // Get LoadBalancer by service name
	GetInternodeDelay(fromNodeID, toNodeID int) float64      // Get inter-node delay between two nodes

	// Deployments
	GetDeployment(serviceName string) *entities.Deployment // Get deployment by service name

	// Pods
	GetPods() []*entities.Pod

	// Profiles
	GetProfile(profileName string) *entities.InterArrivalTime

	// Counters
	GetCounter(profileName string) *entities.RCTCounter

	// Pod Scheduler
	GetPodScheduler() podscheduler.PodScheduler

	GetEventQueue() *EventQueue // ONLY for Debugging

	GetInfluxExporter() *metrics.InfluxExporter
}

// Simulator manages the discrete event simulation
type Simulator struct {
	SimTime    float64
	MaxTime    float64
	EventQueue EventQueue

	// Infrastructure Configuration
	InfraCfg InfraConfig

	// Node Related Components
	Nodes         []*entities.Node
	Kubelets      map[*entities.Node]*entities.Kubelet
	MetricsServer *entities.MetricsServer

	// Load Balancer Related Components
	LoadBalancers          map[string]entities.LoadBalancer
	LoadBalancerDelayModel models.DelayModel

	// Deployments
	Deployments map[string]*entities.Deployment
	HPAs        map[string]entities.HPA

	// Pod Related Components
	PodScheduler podscheduler.PodScheduler

	// Request Related Components
	Profiles map[string]*entities.InterArrivalTime

	// Counters
	RCTCounters map[string]*entities.RCTCounter

	// optional: mu to protect isPaused if Pause/Resume can be called concurrently
	mu        sync.Mutex
	isPaused  bool
	pauseCond *sync.Cond

	// Exporters
	influxExporter *metrics.InfluxExporter
}

// NewSimulator initializes the simulator
// *************** ONLY THIS FUNCTION AND main.go CAN HAVE HARDCODED VARIABLES ***************
func NewSimulator(configPath string) *Simulator {

	// ********** CONFIG **********
	var k = koanf.New(".")

	// Load the main configuration file
	if err := k.Load(file.Provider(configPath), yaml.Parser()); err != nil {
		fmt.Printf("Error loading configuration file: %v\n", err)
	}
	randomSeed := k.Int64("seed")
	simrand.SetSeed(randomSeed)
	kubeletSamplingPeriod := k.Float64("sampling_periods.kubelet")
	metricsServerSamplingPeriod := k.Float64("sampling_periods.metrics_server")
	counterSamplingPeriod := k.Float64("sampling_periods.counter")
	startImmediately := k.Bool("start_immediately")

	baseCfgPath := pathlib.NewPath(configPath).Parent()

	// ********** Initialize the InfluxDB exporter **********
	exporterKey := k.String("exporter")
	influxCfg, err := loadAndUnmarshal[InfluxConfig](baseCfgPath, exporterKey, "exporter")
	if err != nil {
		log.Fatalf("Failed to load InfluxDB configuration: %v", err)
	}

	// Read the InfluxDB token from a file if specified (only needed when the exporter is enabled)
	var influxCfgToken string

	if influxCfg.Enabled && influxCfg.TokenFile != "" {
		tokenFilePath := baseCfgPath.Join("exporter").Join(influxCfg.TokenFile).String()
		tokenBytes, err := os.ReadFile(tokenFilePath)
		if err != nil {
			log.Fatalf("Failed to read InfluxDB token from file: %v", err)
		}
		influxCfgToken = string(tokenBytes)
	}

	var influxExporter *metrics.InfluxExporter
	if influxCfg.Enabled {
		influxExporter, err = metrics.NewInfluxExporter(influxCfg.ServerURL, influxCfgToken, influxCfg.Database)
		if err != nil {
			log.Fatalf("Failed to initialize InfluxDB exporter: %v", err)
		}
		influxExporter.TestConnection()
	}
	// ************************************

	// ********** Load the sub-configuration files **********
	// ********** Infra **********
	infraKey := k.String("infra")
	infraCfg, err := loadAndUnmarshal[InfraConfig](baseCfgPath, infraKey, "infra")
	if err != nil {
		log.Fatalf("Failed to load infrastructure configuration: %v", err)
	}

	// Transform the inter-node latency from milliseconds to seconds
	for i := range infraCfg.InterNodeLatency {
		for j := range infraCfg.InterNodeLatency[i] {
			infraCfg.InterNodeLatency[i][j] = infraCfg.InterNodeLatency[i][j] / 1000.0
		}
	}
	log.Default().Printf("infraCfg.InterNodeLatency: %+v\n", infraCfg.InterNodeLatency)

	// Validate the inter-node latency matrix
	if err := infraCfg.ValidateInterNodeLatency(); err != nil {
		log.Fatalf("Invalid inter-node latency matrix: %v", err)
	}

	// Load VM templates
	templatesPath := baseCfgPath.Join("infra", "vm_templates.yaml").String()
	vmTemplates, err := LoadVMTemplates(templatesPath)
	if err != nil {
		log.Fatalf("Failed to load VM templates: %v", err)
	}
	log.Default().Printf("Loaded %d VM templates\n", len(vmTemplates))

	// Validate the node configurations
	if err := infraCfg.ValidateNodeConfigs(vmTemplates); err != nil {
		log.Fatalf("Invalid node configuration: %v", err)
	}

	// Load and unmarshal requests configuration
	requestsKey := k.String("requests")
	requestsCfg, err := loadAndUnmarshal[RequestsConfig](baseCfgPath, requestsKey, "requests")
	if err != nil {
		log.Fatalf("Failed to load requests configuration: %v", err)
	}

	// Load and unmarshal services configuration
	servicesKey := k.String("services")
	servicesCfg, err := loadAndUnmarshal[ServicesConfig](baseCfgPath, servicesKey, "services")
	if err != nil {
		log.Fatalf("Failed to load services configuration: %v", err)
	}

	// Validate service DAG (no cycles, valid upstream references)
	if err := servicesCfg.ValidateServicesDAG(); err != nil {
		log.Fatalf("Invalid service configuration: %v", err)
	}

	// Load and unmarshal HPAs configuration
	hpasKey := k.String("hpa")
	hpasCfg, err := loadAndUnmarshal[HPAConfig](baseCfgPath, hpasKey, "hpa")
	if err != nil {
		log.Fatalf("Failed to load HPA configuration: %v", err)
	}

	// Load and unmarshal Pod Scheduler configuration
	podSchedulerKey := k.String("pod_scheduler")
	podSchedulerCfg, err := loadAndUnmarshal[PodSchedulerConfig](baseCfgPath, podSchedulerKey, "pod_scheduler")
	if err != nil {
		log.Fatalf("Failed to load pod scheduler configuration: %v", err)
	}

	// ********** Nodes **********
	// ******** and CPUs *********
	var nodes []*entities.Node
	for i := range infraCfg.NumNodes {
		cpuCount := infraCfg.GetNodeCPUCount(i, vmTemplates)
		nodes = append(nodes, entities.NewNode(i,
			cpuCount,
			infraCfg.CPU.SchedulingAlgorithm))
	}

	// ********** KUBELETS **********
	kubeletsMap := make(map[*entities.Node]*entities.Kubelet)

	// Loop through the list of nodes and create a Kubelet for each
	for _, node := range nodes {
		kubeletsMap[node] = entities.NewKubelet(node, kubeletSamplingPeriod)
	}

	// ********** METRICS SERVER **********
	var kubeletSlice []*entities.Kubelet
	for _, kubelet := range kubeletsMap {
		kubeletSlice = append(kubeletSlice, kubelet)
	}

	metricsServer := entities.NewMetricsServer(kubeletSlice, metricsServerSamplingPeriod)

	// ********** Services **********
	loadBalancerDelayModel := models.NewConstantDelay(0.0)
	// loadBalancerDelayModel := models.NewGaussianDelay(0.01, 0.001)

	// Services == Deployment
	deployments := make(map[string]*entities.Deployment)
	for _, svc := range servicesCfg.Services {
		deployments[svc.Name] = entities.NewDeployment(
			svc.Name,
			svc.MinReplicas,
			svc.MaxReplicas,
			svc.CpuNumWorkers,
			svc.CpuNumThreads,
			float64(svc.CpuLimit)/1000.0,
			float64(svc.CpuRequest)/1000.0,
			svc.PodReadyDelay,
			svc.PodDeletionGracePeriod,
			svc.RequestTimeoutLimit,
			svc.RequestProfiles,
			svc.Upstream,
			0,
		)
	}

	// Initialize the HPAs
	hpas := make(map[string]entities.HPA)
	for _, hpa := range hpasCfg.HPA {
		deployment, exists := deployments[hpa.ServiceName]
		if !exists {
			log.Fatalf("HPA references unknown service '%s'", hpa.ServiceName)
		}

		switch hpa.Mode {
		case "remote":
			if hpa.Endpoint == "" {
				log.Fatalf("HPA for service '%s' has mode 'remote' but no endpoint configured", hpa.ServiceName)
			}
			hpas[hpa.ServiceName] = entities.NewRemoteHPA(
				deployment,
				hpa.Endpoint,
				hpa.SynchPeriod,
				hpa.RemoteTimeoutSeconds,
			)
		default: // "original" or unset
			hpas[hpa.ServiceName] = entities.NewOriginalHPA(
				deployment,
				metricsServer,
				hpa.Threshold,
				hpa.GracePeriodScaleIn,
				hpa.GracePeriodScaleOut,
				hpa.SynchPeriod,
			)
		}
	}

	// ********** Request Profiles **********
	profiles := make(map[string]*entities.InterArrivalTime)
	for _, p := range requestsCfg.IAT.Profiles {
		deployment, exists := deployments[p.ServiceName]
		if !exists {
			log.Fatalf("Request profile '%s' references unknown service '%s'", p.Name, p.ServiceName)
		}

		if p.IATJitterMs == nil {
			log.Fatalf("Request profile '%s' is missing required field 'iat_jitter_ms'", p.Name)
		}

		if *p.IATJitterMs < 0 {
			log.Fatalf("Request profile '%s' has invalid 'iat_jitter_ms' value %f. Expected >= 0", p.Name, *p.IATJitterMs)
		}

		if !deployment.HasRequestProfile(p.Name) {
			log.Fatalf("Request profile '%s' is not defined in service '%s' request_profiles", p.Name, p.ServiceName)
		}

		profiles[p.Name] = entities.NewInterArrivalTime(
			p.Rates,
			p.ChangePoints,
			p.ServiceName,
			p.Name,
			p.Distribution,
			*p.IATJitterMs,
		)
	}

	// ********** Counters **********
	rctCounters := make(map[string]*entities.RCTCounter)
	for _, svc := range servicesCfg.Services {
		rctCounters[svc.Name] = entities.NewRCTCounter(
			svc.Name,
			counterSamplingPeriod, // FlushingPeriod
		)
	}

	simMaxTime := requestsCfg.IAT.EndTime

	// ********** LOAD BALANCERS **********
	// Create load balancers for all services dynamically
	loadBalancers := make(map[string]entities.LoadBalancer)
	for _, svc := range servicesCfg.Services {
		switch svc.LBPolicy {
		case "ewma":
			loadBalancers[svc.Name] = entities.NewEwmaLB(deployments[svc.Name])
		case "least_requests":
			loadBalancers[svc.Name] = entities.NewLeastRequestsLB(deployments[svc.Name])
		case "random":
			loadBalancers[svc.Name] = entities.NewRandomLB(deployments[svc.Name])
		case "round_robin":
			loadBalancers[svc.Name] = entities.NewRoundRobinLB(deployments[svc.Name])
		default:
			log.Fatalf("Invalid load balancer policy '%s' for service '%s'. Expected 'ewma', 'least_requests', 'random', or 'round_robin'", svc.LBPolicy, svc.Name)
		}
	}

	// ********** POD SCHEDULER **********
	var podScheduler podscheduler.PodScheduler

	switch podSchedulerCfg.Mode {
	case "remote":
		if podSchedulerCfg.Endpoint == "" {
			log.Fatalf("Pod scheduler mode 'remote' requires endpoint configuration")
		}
		if podSchedulerCfg.RemoteTimeoutSeconds <= 0 {
			log.Fatalf("Pod scheduler mode 'remote' requires remote_timeout_seconds > 0")
		}
		podScheduler = podscheduler.NewRemotePodScheduler(
			podSchedulerCfg.Endpoint,
			podSchedulerCfg.RemoteTimeoutSeconds,
		)
	case "local": // "local" or unset
		// Create local scheduler based on scheduling policy
		switch podSchedulerCfg.SchedulingPolicy {
		case "consolidation":
			podScheduler = podscheduler.NewKubernetesConsolidationScheduler()
		case "highest_cpu":
			podScheduler = podscheduler.NewHighestCPUAvailabilityScheduler()
		default:
			podScheduler = podscheduler.NewKubernetesScheduler()
		}
	default:
		log.Fatalf("Invalid pod scheduler mode '%s'. Expected 'local' or 'remote'", podSchedulerCfg.Mode)
	}

	return &Simulator{
		SimTime:                0,
		MaxTime:                simMaxTime,
		EventQueue:             EventQueue{},
		InfraCfg:               infraCfg,
		LoadBalancers:          loadBalancers,
		LoadBalancerDelayModel: loadBalancerDelayModel,
		Deployments:            deployments,
		HPAs:                   hpas,
		Nodes:                  nodes,
		Kubelets:               kubeletsMap,
		MetricsServer:          metricsServer,
		PodScheduler:           podScheduler,
		Profiles:               profiles,
		RCTCounters:            rctCounters,
		isPaused:               !startImmediately,
		influxExporter:         influxExporter,
	}
}

// ScheduleEvent adds an event to the queue
func (s *Simulator) ScheduleEvent(event events.Event) {
	heap.Push(&s.EventQueue, event)
}

// ScheduleEvent adds an event to the queue
func (s *Simulator) GetSimTime() float64 {
	return s.SimTime
}

// Get the Delay introduced by the Load Balancer
func (s *Simulator) GetLBDelay() float64 {
	return s.LoadBalancerDelayModel.Delay()
}

// Get the inter-node delay between two nodes
func (s *Simulator) GetInternodeDelay(fromNodeID, toNodeID int) float64 {
	// If we have only one node, return 0 delay
	if s.InfraCfg.NumNodes == 1 {
		return 0.0
	}

	// Validate node IDs
	if fromNodeID < 0 || fromNodeID >= s.InfraCfg.NumNodes ||
		toNodeID < 0 || toNodeID >= s.InfraCfg.NumNodes {
		return 0.0 // Return 0 for invalid node IDs
	}

	// Return the latency from the matrix (already converted to seconds)
	return s.InfraCfg.InterNodeLatency[fromNodeID][toNodeID]
}

// Get the Delay introduced by the Load Balancer
func (s *Simulator) GetPods() []*entities.Pod {
	var res []*entities.Pod
	for _, d := range s.Deployments {
		res = append(res, d.GetPods()...)
	}
	return res
}

// Get the Delay introduced by the Load Balancer
func (s *Simulator) GetNodes() []*entities.Node {
	return s.Nodes
}

// Get the Delay introduced by the Load Balancer
func (s *Simulator) GetLB(profileName string) entities.LoadBalancer {
	return s.LoadBalancers[profileName]
}

func (s *Simulator) GetLBByService(serviceName string) entities.LoadBalancer {
	return s.LoadBalancers[serviceName]
}

func (s *Simulator) GetDeployment(serviceName string) *entities.Deployment {
	return s.Deployments[serviceName]
}

// Get the Profile of the Incoming Request Pattern
func (s *Simulator) GetProfile(profileName string) *entities.InterArrivalTime {
	return s.Profiles[profileName]
}

// Get the Counter for a specific service
func (s *Simulator) GetCounter(serviceName string) *entities.RCTCounter {
	return s.RCTCounters[serviceName]
}

func (s *Simulator) GetInfluxExporter() *metrics.InfluxExporter {
	return s.influxExporter
}

// // Get the Delay introduced at the  the Load Balancer
// func (s *Simulator) GetLBDelay() float64 {
// 	return s.LoadBalancerDelayModel.Delay()
// }

// Run starts the simulation
func (s *Simulator) Run() {

	logger.GetLogger(s.GetSimTime()).Info("Simulation started")

	heap.Init(&s.EventQueue)

	event := heap.Pop(&s.EventQueue).(events.Event)

	s.pauseCond = sync.NewCond(&s.mu)

	for event != nil {

		s.waitForResume()

		if event.GetTime() >= s.MaxTime {
			break
		}
		if event.GetTime() < s.SimTime {
			panic("Wrong Simulation! A past event was generated")
		}

		s.SimTime = event.GetTime()
		HandleEvent(event, s)

		event = heap.Pop(&s.EventQueue).(events.Event)
	}

	logger.GetLogger(s.GetSimTime()).Info("Simulation complete")
}

func (s *Simulator) GetEventQueue() *EventQueue {
	return &s.EventQueue
}

func (s *Simulator) GetKubelets() map[*entities.Node]*entities.Kubelet {
	return s.Kubelets
}

func (s *Simulator) GetMetricsServer() *entities.MetricsServer {
	return s.MetricsServer
}

func (s *Simulator) GetHPAs() map[string]entities.HPA {
	return s.HPAs
}

func (s *Simulator) GetProfiles() map[string]*entities.InterArrivalTime {
	return s.Profiles
}

// Get the Profile of the Incoming Request Pattern
func (s *Simulator) GetCounters() map[string]*entities.RCTCounter {
	return s.RCTCounters
}

func (s *Simulator) GetPodScheduler() podscheduler.PodScheduler {
	return s.PodScheduler
}

func (s *Simulator) Pause() {
	s.mu.Lock()
	s.isPaused = true
	s.mu.Unlock()
}

func (s *Simulator) Resume() {
	s.mu.Lock()
	s.isPaused = false
	s.mu.Unlock()
	s.pauseCond.Broadcast()
}

func (s *Simulator) waitForResume() {
	s.mu.Lock()
	for s.isPaused {
		s.pauseCond.Wait()
	}
	s.mu.Unlock()
}

func (s *Simulator) IsPaused() bool {
	return s.isPaused
}

// Load and unmarshal configuration files based on provided keys
// Utility function
func loadAndUnmarshal[T any](basePath *pathlib.Path, key string, cfgPath string) (T, error) {
	cfg := koanf.New(".")
	err := cfg.Load(file.Provider(basePath.Join(cfgPath).Join(key).String()), yaml.Parser())
	if err != nil {
		return *new(T), err
	}

	var unpackedConfig T
	err = cfg.Unmarshal("", &unpackedConfig)
	if err != nil {
		return *new(T), err
	}

	return unpackedConfig, nil
}
