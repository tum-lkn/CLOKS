package entities

import "sort"

// UpstreamServiceConfig defines an upstream service dependency for runtime use
type UpstreamServiceConfig struct {
	UpstreamServiceName string  `koanf:"service"` // Name of the upstream service to call
	UpstreamProfileName string  `koanf:"profile_name"`
	TriggerAt           float64 `koanf:"trigger_at"`         // Percentage (0.0-1.0) of local processing time before triggering
	Blocking            bool    `koanf:"blocking"`           // If true, wait for upstream response
	Probability         float64 `koanf:"probability"`        // Probability (0.0-1.0) that this upstream call is made
	BlockAt             float64 `koanf:"block_at,omitempty"` // Probability (0.0-1.0) that this upstream call is made
}

type RequestProfileConfig struct {
	Name            string  `koanf:"name"`
	RequestDuration float64 `koanf:"request_duration"` // milliseconds
}

type Deployment struct {
	Name                   string // We consider Deployment Name == Service Name
	MinPods                int
	MaxPods                int
	CreatedAt              float64
	PodReadyDelay          float64 // The time until a new Pod becomes ready
	PodDeletionGracePeriod float64 // The time to wait before deleting a Pod

	lastIndex  int
	firstIndex int

	requestTimeoutLimit float64
	requestProfilesS    map[string]float64

	cpuNumWorkers int     // The number of worker processes per Pod (Gunicorn-style)
	cpuNumThreads int     // The number of threads per worker
	cpuLimit      float64 // CPU limit as a fraction (e.g., 0.5 for 500m, 1.0 for 1000m)
	cpuRequest    float64 // CPU request as a fraction (e.g., 0.5 for 500m, 1.0 for 1000m)

	// Multi-tier support
	UpstreamServices []UpstreamServiceConfig // Upstream service dependencies

	// Pods
	pods []*Pod
}

// NewNode creates a new Node
func NewDeployment(name string, minPods, maxPods int, cpuNumWorkers int, cpuNumThreads int, cpuLimit, cpuRequest float64, podReadyDelay, podDeletionGracePeriod, requestTimeoutLimit float64, requestProfiles []RequestProfileConfig, upstreamServices []UpstreamServiceConfig, createdAt float64) *Deployment {
	requestProfilesInSeconds := make(map[string]float64, len(requestProfiles))
	for _, profile := range requestProfiles {
		requestProfilesInSeconds[profile.Name] = profile.RequestDuration / 1000.0
	}

	d := &Deployment{
		Name:                   name,
		MinPods:                minPods,
		MaxPods:                maxPods,
		CreatedAt:              createdAt,
		PodReadyDelay:          podReadyDelay,
		PodDeletionGracePeriod: podDeletionGracePeriod, // Default value for Pod deletion grace period
		requestTimeoutLimit:    requestTimeoutLimit,
		requestProfilesS:       requestProfilesInSeconds,
		cpuNumWorkers:          cpuNumWorkers,
		cpuNumThreads:          cpuNumThreads,
		cpuLimit:               cpuLimit,
		cpuRequest:             cpuRequest,
		UpstreamServices:       sortUpstreamServices(upstreamServices),
	}

	for range minPods {
		p := NewPod(d.lastIndex, name, createdAt, d)
		d.pods = append(d.pods, p)
		d.lastIndex++
	}

	return d
}

func (d *Deployment) GetRunningPods() []*Pod {
	var runningPodsSlice []*Pod

	for _, p := range d.pods {
		if p.Phase == PodRunning {
			runningPodsSlice = append(runningPodsSlice, p)
		}
	}
	return runningPodsSlice
}

func (d *Deployment) GetNumRunningPods() int {
	return len(d.GetRunningPods())
}

func (d *Deployment) GetActivePods() []*Pod {
	var activePodsSlice []*Pod

	for _, p := range d.pods {
		if p.Phase == PodRunning || p.Phase == PodScheduled {
			activePodsSlice = append(activePodsSlice, p)
		}
	}
	return activePodsSlice
}

func (d *Deployment) GetNumActivePods() int {
	return len(d.GetActivePods())
}

func (d *Deployment) RequestTimeoutLimit() float64 {
	return d.requestTimeoutLimit
}

func (d *Deployment) HasRequestProfile(profileName string) bool {
	_, ok := d.requestProfilesS[profileName]
	return ok
}

func (d *Deployment) RequestDurationForProfileS(profileName string) float64 {
	return d.requestProfilesS[profileName]
}

func (d *Deployment) RequestCanTimeOut() bool {
	return d.RequestTimeoutLimit() > 0
}

// GetPods returns a slice of pointers to all the Pod instances
// associated with this Deployment.
func (d *Deployment) GetPods() []*Pod {
	return d.pods
}

func (d *Deployment) GetLastPod() *Pod {
	return d.pods[len(d.pods)-1]
}

// GetNumPods returns the total number of Pods currently associated
// with this Deployment.
func (d *Deployment) GetNumPods() int {
	return d.lastIndex - d.firstIndex
}

// GetLastIndex is a utility function that returns the index value
// which will be used for creating a new Pod.
func (d *Deployment) GetLastIndex() int {
	return d.lastIndex
}

func (d *Deployment) GetFirstIndex() int {
	return d.firstIndex
}

func (d *Deployment) GetPodFromID(ID int) *Pod {
	for _, p := range d.pods {
		if p.ID == ID {
			return p
		}
	}
	return nil
}

// CreatePod attempts to create a new Pod for the Deployment at the given simulation time.
// The function performs the following:
// - Ensures the number of Pods doesn't exceed the maximum allowed (MaxPods).
// - Creates a new Pod instance with the current lastIndex and associates it with this Deployment.
// - Immediately confirms the new Pod.
// - Adds the new Pod to the list of Pods managed by the Deployment.
// - Increments the lastIndex to prepare for the next Pod creation.
func (d *Deployment) CreatePod(simTime float64) *Pod {
	if d.GetNumPods() == d.MaxPods {
		// Do nothing if the maximum number of Pods has been reached.
		return nil
	}

	// Create a new Pod instance.
	p := NewPod(
		d.lastIndex, // Assign a unique index to the Pod.
		d.Name,      // Use the Deployment's name to identify the Pod.
		simTime,     // Set the creation time of the Pod.
		d)           // Associate the Pod with this Deployment.

	// Add the new Pod to the Deployment's list of Pods.
	d.pods = append(d.pods, p)

	// Increment the lastIndex to prepare for the next Pod creation.
	d.lastIndex++

	return p
}

// GetPodForTermination returns a pod candidate for scale-in.
// Priority: Pending pods first, otherwise the first Running pod.
// Returns nil if no pending/running pod exists.
func (d *Deployment) GetPodForTermination() *Pod {
	for _, p := range d.pods {
		if p.Phase == PodPending {
			return p
		}
	}

	runningPods := d.GetRunningPods()
	if len(runningPods) == 0 {
		return nil
	}

	return runningPods[0]
}

func (d *Deployment) KillPod(simTime float64, pod *Pod) {

	// Remove the pod from the deployment's pods slice
	for i, p := range d.pods {
		if p == pod {
			d.pods = append(d.pods[:i], d.pods[i+1:]...)
			d.firstIndex++
			break
		}
	}

	pod.DiscardAllPendingTasks()
	pod.DiscardWorkers()

	pod.Node.RemovePodFromNode(pod)
}

func (d *Deployment) HasPod(pod *Pod) bool {
	for _, p := range d.pods {
		if p == pod {
			return true
		}
	}
	return false
}

func sortUpstreamServices(upstreamServices []UpstreamServiceConfig) []UpstreamServiceConfig {
	sortedUpstreamServices := append([]UpstreamServiceConfig{}, upstreamServices...)

	// Normalize upstream evaluation order for deterministic runtime behavior:
	// 1) earlier trigger points run first (lower TriggerAt before higher TriggerAt),
	// 2) for the same TriggerAt, non-blocking calls are evaluated before blocking ones.
	sort.SliceStable(sortedUpstreamServices, func(i, j int) bool {
		left := sortedUpstreamServices[i]
		right := sortedUpstreamServices[j]

		if left.TriggerAt != right.TriggerAt {
			return left.TriggerAt < right.TriggerAt
		}

		if left.Blocking != right.Blocking {
			return !left.Blocking && right.Blocking
		}

		return false
	})

	return sortedUpstreamServices
}
