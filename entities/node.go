package entities

import "fmt"

// NodeStatus represents the Status of a Node.
type NodeStatus string

const (
	NodePending NodeStatus = "Pending"
	NodeRunning NodeStatus = "Running"
	NodeFailed  NodeStatus = "Failed"
	NodeStopped NodeStatus = "Stopped"
	NodeUnknown NodeStatus = "Unknown"
)

// Node represents a network node
type Node struct {
	ID     int
	Name   string
	Status NodeStatus // "active", "inactive", etc.
	NumCPU int

	TotalCPUCapacity     float64
	AvailableCPUCapacity float64

	CPUs       []*CPU // List of CPUs in the node
	activePods []*Pod

	lastCpuAssigned int

	lastQuotaReplenishTime float64
}

// NewNode creates a new Node
func NewNode(id int, numCpu int, cpuSchedulerType string) *Node {

	// First create the barebones Node, then we will add the CPUs accordingly
	node := &Node{
		ID:                     id,
		Name:                   fmt.Sprintf("node-%d", id),
		Status:                 NodeRunning,
		NumCPU:                 numCpu,
		TotalCPUCapacity:       float64(numCpu),
		AvailableCPUCapacity:   float64(numCpu),
		lastCpuAssigned:        -1,
		lastQuotaReplenishTime: 0,
	}

	cpus := make([]*CPU, numCpu)
	for i := range numCpu {
		cpus[i] = NewCPU(i, node)
	}

	node.CPUs = cpus

	return node
}

// In this function we also change the state of the pod to scheduled
func (n *Node) AddPodToNode(pod *Pod) {
	// Add the Pod to the activePods in the Node
	n.activePods = append(n.activePods, pod)

	// Decrease the AvailableCPUCapacity
	n.AvailableCPUCapacity -= pod.CPURequest

	// Now change the state of the Pod
	pod.Node = n
	pod.Phase = PodScheduled

	// Assign in Round-Robin the Workers of the Pod to the available CPUs on the Node
	// Create the Worker Threads when the Pod is added to the Node
	pod.Workers = make([]*Worker, pod.Deployment.cpuNumWorkers)

	for i := range pod.Deployment.cpuNumWorkers {
		// Round Robin for the Workers of a pod
		currentCpuToAssign := (n.lastCpuAssigned + 1) % n.NumCPU

		pod.Workers[i] = NewWorker(
			i,
			pod.Deployment.cpuNumThreads,
			n.CPUs[currentCpuToAssign],
			pod,
		)

		n.lastCpuAssigned = currentCpuToAssign
	}

}

func (n *Node) GetActivePods() []*Pod {
	return n.activePods
}

func (n *Node) GetRunningPods() []*Pod {
	var runningPods []*Pod
	for _, p := range n.activePods {
		if p.Phase == PodRunning {
			runningPods = append(runningPods, p)
		}
	}
	return runningPods
}

func (n *Node) GetNumActivePods() int {
	return len(n.activePods)
}

func (n *Node) RemovePodFromNode(pod *Pod) {
	if len(n.activePods) == 0 {
		return
	}

	for i, p := range n.activePods {
		if p == pod {
			// Increase the n.AvailableCPUCapacity
			n.AvailableCPUCapacity += p.Deployment.cpuRequest

			// Clear pod's parent node reference
			p.Node = nil
			p.Phase = PodShuttingDown

			// Remove the pod from activePods slice
			n.activePods = append(n.activePods[:i], n.activePods[i+1:]...)
			break
		}
	}
}

func (n *Node) NextQuotaReplenishTime() float64 {
	return n.lastQuotaReplenishTime + n.CPUs[0].Scheduler.CFSPeriod()
}

func (n *Node) LastQuotaReplenishTime() float64 {
	return n.lastQuotaReplenishTime
}

func (n *Node) SetLastQuotaReplenishTime(time float64) {
	n.lastQuotaReplenishTime = time
}
