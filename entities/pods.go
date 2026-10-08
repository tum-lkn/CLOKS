package entities

import (
	"fmt"
	"network-simulator/simrand"
)

// PodPhase represents the lifecycle phase of a Pod.
type PodPhase string

const (
	PodPending      PodPhase = "Pending"
	PodScheduled    PodPhase = "Scheduled"
	PodRunning      PodPhase = "Running"
	PodShuttingDown PodPhase = "ShuttingDown"
	PodKilled       PodPhase = "Killed"
)

type PodMeasurement struct {
	time       float64
	podSeconds float64
}

func NewPodMeasurement(time float64, podSeconds float64) *PodMeasurement {
	return &PodMeasurement{
		time:       time,
		podSeconds: podSeconds,
	}
}

// Pod represents a simulated Kubernetes Pod.
type Pod struct {
	ID         int
	Name       string
	Deployment *Deployment
	Namespace  string
	Service    string
	Node       *Node
	Phase      PodPhase
	CreatedAt  float64

	CPULimit   float64 // CPU limit as a fraction (e.g., 0.5 for 500m, 1.0 for 1000m, 2.0 for 2000m)
	CPURequest float64 // CPU request as a fraction (e.g., 0.5 for 500m, 1.0 for 1000m, 2.0 for 2000m)

	Workers []*Worker

	// PRIVATE
	requests                 []*Request
	pendingTasks             []*Task
	numArrivedRequests       int
	numProcessedRequests     int
	timeFirstReceivedRequest float64

	cpuSeconds              float64
	timeLastPodSecondUpdate float64

	// This is a variable to keep the defaultAvailableQuotaTime (to be used
	// as reference in ReplenishAvailableQuotaTime)
	defaultAvailableQuotaTime float64

	// This is the variable to keep the currentlyAvailableQuotaTime
	// (which is reduced every time a Thread from this pod gets TaskCompleted or scheduled out)
	curentlyAvailableQuotaTime float64
}

// NewPod initializes and returns a new Pod instance.
func NewPod(ID int, namespace string, createdAt float64, deployment *Deployment) *Pod {

	return &Pod{
		ID:                         ID,
		Name:                       fmt.Sprintf("pod_%s_%05d", namespace, ID),
		Deployment:                 deployment,
		Namespace:                  namespace,
		Phase:                      PodPending,
		CreatedAt:                  createdAt,
		CPULimit:                   deployment.cpuLimit,
		CPURequest:                 deployment.cpuRequest,
		numArrivedRequests:         0,
		timeLastPodSecondUpdate:    0,
		timeFirstReceivedRequest:   -1,
		defaultAvailableQuotaTime:  -1,
		curentlyAvailableQuotaTime: 0, // Upon NewPod, we don't set its availableQuotaTime
	}

}

func (p *Pod) StartPod() {
	if p.Phase != PodScheduled {
		panic("Trying to start a Pod that hasn't been scheduled yet")
	}

	p.Phase = PodRunning

	// Here we also set the defaultAvailableQuotaTime for this Pod (as we know on which Node it's running)
	// We set it according to the Deployment and to the Scheduler of the Scheduler of the first CPU
	// of the Node.
	node := p.Node
	p.defaultAvailableQuotaTime = node.CPUs[0].Scheduler.CFSPeriod() * p.Deployment.cpuLimit

	// After that, we replenish it
	p.ReplenishAvailableQuotaTime() // We call this
}

// Add Request to Pod's queue
func (p *Pod) AddRequest(r *Request, simTime float64) {
	p.numArrivedRequests++
	p.requests = append(p.requests, r)
}

func (p *Pod) AddTask(t *Task) bool {
	assignmentToThreadSuccessful := false
	if p.IsSyncMode() { // sync, in sync mode there is only one thread per worker
		if p.HasAvailableWorkers() {
			w := p.RandomAvailableWorker()
			w.threads[0].Task = t
			t.Thread = w.threads[0]
			assignmentToThreadSuccessful = true
		} else {
			p.EnqueueTask(t)
		}
	} else { //gthread
		// Randomly select a worker
		// We bypass the check whether the pod has available workers
		w := p.RandomWorker()

		// Now check if the worker has any available Thread, if it has pick one randomly.
		if w.HasAvailableThreads() {
			thread := w.RandomAvailableThread()
			thread.Task = t
			t.Thread = thread
			assignmentToThreadSuccessful = true
		} else {
			w.EnqueueTask(t)
		}
	}
	return assignmentToThreadSuccessful
}

// CompleteTask dispatches one pending pod task after completion frees capacity
func (p *Pod) CompleteTask(t *Task) {
	completedThread := t.Thread
	sched := completedThread.Worker.CPU.Scheduler

	t.SetStatus(TaskCompleted)

	t.Thread = nil

	if p.IsSyncMode() {
		if p.HasQueuedTasks() {
			newTask := p.PopTask()

			newTask.Thread = completedThread

			completedThread.Task = newTask
			sched.TransitionThread(completedThread, ThreadRunnable)
		} else {
			completedThread.Task = nil
			sched.TransitionThread(completedThread, ThreadIdle)
		}
	} else {
		newlyAvailableWorker := completedThread.Worker
		if newlyAvailableWorker.HasQueuedTasks() {
			newTask := newlyAvailableWorker.PopTask()

			completedThread.Task = newTask
			sched.TransitionThread(completedThread, ThreadRunnable)

			newTask.Thread = completedThread
		} else {
			completedThread.Task = nil
			sched.TransitionThread(completedThread, ThreadIdle)
		}
	}
}

// Remove completed Request from Pod's queue
func (p *Pod) RemoveRequest(r *Request, simTime float64) {
	p.numProcessedRequests++

	for i, req := range p.requests {
		if req == r {
			p.requests = append(p.requests[:i], p.requests[i+1:]...)
			break
		}
	}
}

func (p *Pod) Measure() float64 {
	return p.cpuSeconds
}

func (p *Pod) GetNumRequests() int {
	return len(p.requests)
}

// GetRequests returns the list of requests currently in the pod
func (p *Pod) GetRequests() []*Request {
	return p.requests
}

func (p *Pod) IncrementCPUSeconds(simTime, increment float64) error {
	p.timeLastPodSecondUpdate = simTime
	p.cpuSeconds += increment
	return nil
}

// IsSyncMode returns true if worker is in sync mode (single thread)
// Otherwise, it is in the Gthread mode
func (p *Pod) IsSyncMode() bool {
	return p.Deployment.cpuNumThreads == 1
}

// RandomWorker returns a uniformly random worker from the pod, or nil if none exist.
func (p *Pod) RandomWorker() *Worker {
	if len(p.Workers) == 0 {
		return nil
	}

	return p.Workers[simrand.Intn(len(p.Workers))]
}

func (p *Pod) RandomAvailableWorker() *Worker {
	available := make([]*Worker, 0)

	for _, w := range p.Workers {
		if w.IsIdle() {
			available = append(available, w)
		}
	}

	if len(available) == 0 {
		return nil
	}

	return available[simrand.Intn(len(available))]
}

func (p *Pod) HasAvailableWorkers() bool {
	for _, w := range p.Workers {
		if w.IsIdle() {
			return true
		}
	}
	return false
}

func (p *Pod) EnqueueTask(t *Task) {
	p.pendingTasks = append(p.pendingTasks, t)
}

func (p *Pod) PopTask() *Task {
	t := p.pendingTasks[0]
	p.pendingTasks = p.pendingTasks[1:]
	return t
}

func (p *Pod) HasQueuedTasks() bool {
	return len(p.pendingTasks) > 0
}

func (p *Pod) AvailableQuotaTime() float64 {
	return p.curentlyAvailableQuotaTime
}

func (p *Pod) ConsumeAvailableQuotaTime(runningTime float64) {
	p.curentlyAvailableQuotaTime -= runningTime
}

func (p *Pod) ReplenishAvailableQuotaTime() {
	// Carry over overshoot (negative quota) into the next period so pods cannot gain
	// extra CPU time due to coarse scheduling granularity.
	if p.curentlyAvailableQuotaTime < 0 {
		p.curentlyAvailableQuotaTime = p.defaultAvailableQuotaTime + p.curentlyAvailableQuotaTime
	} else {
		p.curentlyAvailableQuotaTime = p.defaultAvailableQuotaTime
	}

}

func (p *Pod) SetThrottledThreadsToRunnable() {
	for _, w := range p.Workers {
		sched := w.CPU.Scheduler
		for _, t := range w.threads {
			if t.Status() == ThreadThrottled {
				sched.TransitionThread(t, ThreadRunnable)
			}
		}
	}
}

func (p *Pod) SetRunnableThreadsToThrottled() {
	for _, w := range p.Workers {
		sched := w.CPU.Scheduler
		for _, t := range w.threads {
			if t.Status() == ThreadRunnable {
				sched.TransitionThread(t, ThreadThrottled)
			}
		}
	}
}

func (p *Pod) IsThrottled() bool {
	return p.AvailableQuotaTime() <= 0
}

func (p *Pod) IsIdle() bool {
	if len(p.pendingTasks) != 0 {
		return false
	}

	for _, w := range p.Workers {
		if !w.IsIdle() {
			return false
		}
	}

	return true
}

func (p *Pod) PendingTasks() []*Task {
	return p.pendingTasks
}

// TryDiscardPodPendingTask removes a task from the pod's pending task queue.
// Returns true if the task was found and removed, false otherwise.
func (p *Pod) TryDiscardPodPendingTask(task *Task) bool {
	for i, t := range p.pendingTasks {
		if t == task {
			p.pendingTasks = append(p.pendingTasks[:i], p.pendingTasks[i+1:]...)
			return true
		}
	}
	return false
}

// TryDiscardWorkerPendingTask removes a task from any worker's pending task queue in this pod.
// Returns true if the task was found and removed from a worker, false otherwise.
func (p *Pod) TryDiscardWorkerPendingTask(task *Task) bool {
	for _, w := range p.Workers {
		for i, t := range w.pendingTasks {
			if t == task {
				w.pendingTasks = append(w.pendingTasks[:i], w.pendingTasks[i+1:]...)
				return true
			}
		}
	}
	return false
}

func (p *Pod) DiscardAllPendingTasks() {
	p.pendingTasks = p.pendingTasks[:0]
}

func (p *Pod) DiscardWorkers() {
	p.Workers = p.Workers[:0]
}
