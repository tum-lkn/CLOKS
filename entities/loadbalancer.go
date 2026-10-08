package entities

import (
	"math"
	"network-simulator/simrand"
	"sort"
)

type LoadBalancer interface {
	NextPod(r *Request, simTime float64) *Pod // Method to get the next pod
	UpdateState(r *Request, p *Pod, simTime float64)
	GetNodeID() int // Method to get the node ID where the load balancer is assigned
}

type RoundRobinLB struct {
	deployment *Deployment
	index      int
	nodeID     int // Load balancer is logically assigned to node 0 for ease of debugging
}

// NewRoundRobinLB creates a new Round Robin Load Balancer
// The load balancer is logically assigned to node 0 for ease of debugging
func NewRoundRobinLB(d *Deployment) *RoundRobinLB {
	return &RoundRobinLB{
		deployment: d,
		index:      0,
		nodeID:     0, // Always assign load balancer to node 0
	}
}

func (rr *RoundRobinLB) NextPod(r *Request, simTime float64) *Pod {
	pods := rr.deployment.pods
	n := len(pods)
	if n == 0 {
		return nil
	}

	// Keep index bounded even if pod list size changed.
	rr.index = rr.index % n

	// Scan each pod at most once in circular order.
	for i := 0; i < n; i++ {
		idx := (rr.index + i) % n
		pod := pods[idx]
		if pod != nil && pod.Phase == PodRunning {
			rr.index = (idx + 1) % n
			return pod
		}
	}

	return nil
}

func (rr *RoundRobinLB) UpdateState(r *Request, p *Pod, simTime float64) {}

// GetNodeID returns the node ID where the load balancer is logically assigned
func (rr *RoundRobinLB) GetNodeID() int {
	return rr.nodeID
}

// ********** EWMA LOAD BALANCING **********
type EwmaLB struct {
	deployment      *Deployment
	ewmaScores      map[*Pod]float64
	lastUpdateTimes map[*Pod]float64
	nodeID          int // Load balancer is logically assigned to node 0 for ease of debugging

	// Constannts
	ewmaDecayTime       float64
	slowStartEnabled    bool
	bigNegativeConstant float64
	seed                int64
	pickSetSize         int
}

func NewEwmaLB(d *Deployment) *EwmaLB {
	ewmaScores := make(map[*Pod]float64)
	lastUpdateTimes := make(map[*Pod]float64)

	return &EwmaLB{
		deployment:      d,
		ewmaScores:      ewmaScores,
		lastUpdateTimes: lastUpdateTimes,
		nodeID:          0, // Always assign load balancer to node 0 for ease of debugging

		// Constants
		ewmaDecayTime:       10.0,
		slowStartEnabled:    true,
		bigNegativeConstant: -1e6,
		seed:                42,
		pickSetSize:         2,
	}
}

func (ewmaLB *EwmaLB) getAverageEwmaScore() float64 {
	if len(ewmaLB.ewmaScores) == 0 {
		return 0
	}

	var sum float64
	var count float64
	for pod, ewmaScore := range ewmaLB.ewmaScores {
		if pod.Phase != PodRunning {
			continue
		}
		sum += ewmaScore
		count++
	}

	if count > 0 {
		return sum / count
	}

	return 0
}

func (ewmaLB *EwmaLB) decayEwma(ewma, lastTouchedAt, rtt, now float64) float64 {
	td := now - lastTouchedAt
	if td < 0 {
		td = 0
	}

	weight := math.Exp(-td / ewmaLB.ewmaDecayTime)
	ewma = ewma*weight + rtt*(1.0-weight)

	return ewma
}

func (ewmaLB *EwmaLB) NextPod(r *Request, simTime float64) *Pod {
	var availablePods []*Pod

	for _, pod := range ewmaLB.deployment.pods {
		if pod.Phase == PodRunning {
			availablePods = append(availablePods, pod)
		}
	}

	for _, pod := range availablePods {
		if _, exists := ewmaLB.ewmaScores[pod]; !exists {
			// Initialize the EWMA_SCORES accordingly
			if !ewmaLB.slowStartEnabled {
				ewmaLB.ewmaScores[pod] = ewmaLB.getAverageEwmaScore()
			} else {
				ewmaLB.ewmaScores[pod] = 0
			}
			ewmaLB.lastUpdateTimes[pod] = ewmaLB.bigNegativeConstant
		}
	}

	if len(availablePods) == 1 {
		return availablePods[0]
	}

	randomIndices := simrand.Perm(len(availablePods))[:ewmaLB.pickSetSize]
	podsSubset := make([]*Pod, ewmaLB.pickSetSize)
	for i, idx := range randomIndices {
		podsSubset[i] = availablePods[idx]
	}

	ewmaTmpScores := make(map[*Pod]float64)

	for _, pod := range podsSubset {
		ewmaTmpScores[pod] = ewmaLB.decayEwma(
			ewmaLB.ewmaScores[pod],
			ewmaLB.lastUpdateTimes[pod],
			0,
			simTime,
		)
	}

	// Sort podsSubset by their scores
	sort.Slice(podsSubset, func(i, j int) bool {
		return ewmaTmpScores[podsSubset[i]] < ewmaTmpScores[podsSubset[j]]
		// return score(podsSubset[i], simulationTime) < score(podsSubset[j], simulationTime)
	})

	// Choose the pod with the best score
	chosenPod := podsSubset[0]

	return chosenPod
}

// UpdateState updates the state of the EWMA (Exponentially Weighted Moving Average) load balancer.
// It recalculates the EWMA score for a given pod based on the new RTT (Round-Trip Time)
// and updates the last update time for that pod.
func (ewmaLB *EwmaLB) UpdateState(r *Request, p *Pod, simTime float64) {
	// Calculate the RTT (Round-Trip Time) as the difference between the time the request
	// left the load balancer and the time it arrived at the load balancer.
	rtt := r.TimeLBDeparture - r.TimeLBArrival

	// Compute the new EWMA score for the pod by decaying the current EWMA score
	// using the time since the last update and the current RTT.
	newEwma := ewmaLB.decayEwma(
		ewmaLB.ewmaScores[p],      // Current EWMA score for the pod.
		ewmaLB.lastUpdateTimes[p], // Last update time for the pod.
		rtt,                       // Current RTT value.
		simTime,                   // Current simulation time.
	)

	// Update the EWMA score for the pod with the newly calculated value.
	ewmaLB.ewmaScores[p] = newEwma

	// Update the last update time for the pod to the current simulation time.
	ewmaLB.lastUpdateTimes[p] = simTime

	// print(newEwma)
}

// GetNodeID returns the node ID where the load balancer is logically assigned
func (ewmaLB *EwmaLB) GetNodeID() int {
	return ewmaLB.nodeID
}

// ********** LEAST REQUESTS (P2C) LOAD BALANCING **********
// Implements Power of Two Choices (Mitzenmacher et al.): picks choiceCount
// random available pods and routes to the one with fewest active requests.
// This gives O(choiceCount) selection with near-optimal load distribution
// and resistance to herding behaviour.
type LeastRequestsLB struct {
	deployment     *Deployment
	activeRequests map[*Pod]int
	nodeID         int
	choiceCount    int // number of random candidates to sample (default 2)
}

func NewLeastRequestsLB(d *Deployment) *LeastRequestsLB {
	return &LeastRequestsLB{
		deployment:     d,
		activeRequests: make(map[*Pod]int),
		nodeID:         0,
		choiceCount:    2,
	}
}

func (lb *LeastRequestsLB) NextPod(r *Request, simTime float64) *Pod {
	var available []*Pod
	for _, pod := range lb.deployment.pods {
		if pod != nil && pod.Phase == PodRunning {
			available = append(available, pod)
		}
	}

	n := len(available)
	if n == 0 {
		return nil
	}

	// Sample min(choiceCount, n) distinct candidates via a partial Fisher-Yates shuffle.
	k := lb.choiceCount
	if k > n {
		k = n
	}
	indices := simrand.Perm(n)[:k]

	chosen := available[indices[0]]
	minReqs := lb.activeRequests[chosen]
	for _, idx := range indices[1:] {
		pod := available[idx]
		if count := lb.activeRequests[pod]; count < minReqs {
			chosen = pod
			minReqs = count
		}
	}

	lb.activeRequests[chosen]++
	return chosen
}

func (lb *LeastRequestsLB) UpdateState(r *Request, p *Pod, simTime float64) {
	if lb.activeRequests[p] > 0 {
		lb.activeRequests[p]--
	}
}

func (lb *LeastRequestsLB) GetNodeID() int {
	return lb.nodeID
}

// ********** RANDOM LOAD BALANCING **********
type RandomLB struct {
	deployment *Deployment
	nodeID     int
}

func NewRandomLB(d *Deployment) *RandomLB {
	return &RandomLB{deployment: d, nodeID: 0}
}

func (lb *RandomLB) NextPod(r *Request, simTime float64) *Pod {
	var available []*Pod
	for _, pod := range lb.deployment.pods {
		if pod != nil && pod.Phase == PodRunning {
			available = append(available, pod)
		}
	}
	if len(available) == 0 {
		return nil
	}
	return available[simrand.Intn(len(available))]
}

func (lb *RandomLB) UpdateState(r *Request, p *Pod, simTime float64) {}

func (lb *RandomLB) GetNodeID() int { return lb.nodeID }
