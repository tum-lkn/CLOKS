package entities

import (
	"container/heap"
)

// CPUScheduler defines the interface that all CPU scheduling policies must implement
type CPUScheduler interface {

	// AddThread adds a new task to the scheduler's queue
	AddThread(thread *Thread)

	IsIdle() bool

	MinVRunTime() float64

	CFSPeriod() float64
	SchedLatency() float64
	SchedMinGranularity() float64
	SchedVRuntimeDelta() float64

	RunningThread() *Thread

	SetRunningThread(thread *Thread)
	HasRunningThread() bool

	PickNextThread() *Thread
	CalculateTimeSlice() float64

	TotalNumberOfThreads() int

	TransitionThread(t *Thread, nextStatus ThreadStatus) error
}

// *********************
// CFS SCHEDULER
// *********************

// RoundRobinScheduler implements round-robin CPU scheduling with worker/thread hierarchy
type CFSScheduler struct {
	cpu *CPU

	runQueue ThreadQueue // Priority queue of runnable threads

	// This list will contain threads that are throttled, but NOT necessarily ALL threads that are throttled
	// We just use it in case a PickNextQueue() pops a Throttled Thread. If this is the case, then we
	// put the popped thread to the throttledList and then we move on to find a Runnable Thread
	idleList      map[*Thread]struct{}
	blockedList   map[*Thread]struct{}
	throttledList map[*Thread]struct{}

	runningThread *Thread

	cfs_period_s            float64
	sched_latency_s         float64
	sched_min_granularity_s float64
	sched_vruntime_delta_s  float64
}

func NewCFSScheduler(cpu *CPU) *CFSScheduler {
	scheduler := &CFSScheduler{
		runQueue:      make(ThreadQueue, 0),
		idleList:      make(map[*Thread]struct{}, 0),
		throttledList: make(map[*Thread]struct{}, 0),
		blockedList:   make(map[*Thread]struct{}, 0),
		cpu:           cpu,

		// cfs_period_s: 0.1,
		cfs_period_s: 0.05,

		sched_min_granularity_s: 0.003, // Reducing this increases the accuracy of the throttling.
		// sched_min_granularity_s: 0.0001, // Reducing this increases the accuracy of the throttling.
		sched_latency_s:        0.024,
		sched_vruntime_delta_s: 0,
	}
	heap.Init(&scheduler.runQueue)
	return scheduler
}

func (cfs *CFSScheduler) AddThread(t *Thread) {
	// When adding a new thread to the CFS Scheduler, first set its vRunTime to
	// the minimum of the ThreadQueue + the sched_vruntime_delta_s
	t.SetVRunTime(cfs.MinVRunTime() + cfs.sched_vruntime_delta_s)

	//And now add the thread to the idleList
	cfs.addToList(t, cfs.idleList)

}

func (cfs *CFSScheduler) IsIdle() bool { return cfs.runningThread == nil }

func (cfs *CFSScheduler) PickNextThread() *Thread {

	var next *Thread
	if cfs.runQueue.Len() > 0 {
		// next = heap.Pop(&cfs.runQueue).(*Thread)
		next = cfs.runQueue.Peek()

		if next.Status() != ThreadRunnable {
			panic("Thread picked by CPU scheduler must be runnable")
		}

	}
	return next

}

func (cfs *CFSScheduler) CalculateTimeSlice() float64 {
	return cfs.sched_min_granularity_s

	// OLD IMPLEMENTATION
	// n := cfs.runQueue.Len()
	// if cfs.runningThread != nil {
	// 	n += 1 // also count the running thread if there is one
	// }

	// if n == 0 {
	// 	return cfs.sched_latency_s
	// }

	// return max(
	// 	cfs.sched_latency_s/float64(n),
	// 	cfs.sched_min_granularity_s,
	// )
}

func (cfs *CFSScheduler) HasRunningThread() bool  { return cfs.runningThread != nil }
func (cfs *CFSScheduler) HasRunnableThread() bool { return cfs.runQueue.Len() > 0 }

func (cfs *CFSScheduler) MinVRunTime() float64 {
	queueMin := cfs.runQueue.MinVRunTime() // 0 if empty
	hasQueue := !cfs.runQueue.IsEmpty()

	if cfs.runningThread == nil {
		return queueMin
	}

	runningV := cfs.runningThread.VRunTime()

	if !hasQueue {
		return runningV
	}

	return min(queueMin, runningV)
}

func (cfs *CFSScheduler) RunningThread() *Thread     { return cfs.runningThread }
func (cfs *CFSScheduler) SetRunningThread(t *Thread) { cfs.runningThread = t }
func (cfs *CFSScheduler) TotalNumberOfThreads() int {
	additional := 0
	if cfs.HasRunningThread() {
		additional = 1
	}
	return len(cfs.runQueue) + len(cfs.blockedList) + len(cfs.throttledList) + additional
}

func (cfs *CFSScheduler) CFSPeriod() float64           { return cfs.cfs_period_s }
func (cfs *CFSScheduler) SchedLatency() float64        { return cfs.sched_latency_s }
func (cfs *CFSScheduler) SchedMinGranularity() float64 { return cfs.sched_min_granularity_s }
func (cfs *CFSScheduler) SchedVRuntimeDelta() float64  { return cfs.sched_vruntime_delta_s }

func (cfs *CFSScheduler) removeFromList(thread *Thread, list map[*Thread]struct{}) {
	if _, ok := list[thread]; !ok {
		panic("Thread not found in list")
	}
	delete(list, thread)
}

func (cfs *CFSScheduler) removeFromRunQueue(thread *Thread) {
	// Returns success
	for i := 0; i < len(cfs.runQueue); i++ {
		if cfs.runQueue[i] == thread {
			heap.Remove(&cfs.runQueue, i)
			return
		}
	}
	panic("We should never reach a situation where we are removing from a list, in which the Thread is not")
}

func (cfs *CFSScheduler) addToList(thread *Thread, list map[*Thread]struct{}) {
	if _, ok := list[thread]; ok {
		panic("Thread already in list")
	}
	list[thread] = struct{}{}
}

func (cfs *CFSScheduler) addToRunQueue(t *Thread) {
	if t == nil {
		panic("The thread we are trying to add to the runqueue should not be nil")
	}

	heap.Push(&cfs.runQueue, t)
}

func (cfs *CFSScheduler) TransitionThread(t *Thread, nextStatus ThreadStatus) error {
	prevStatus := t.Status()

	// First remove the Thread from the list where it was
	switch prevStatus {
	case ThreadIdle:
		cfs.removeFromList(t, cfs.idleList)
	case ThreadBlocked:
		cfs.removeFromList(t, cfs.blockedList)
	case ThreadRunnable:
		cfs.removeFromRunQueue(t)
	case ThreadRunning:
		cfs.runningThread = nil
	case ThreadThrottled:
		cfs.removeFromList(t, cfs.throttledList)
	}

	t.SetStatus(nextStatus)

	// Now add the thread where it is due
	switch nextStatus {
	case ThreadIdle:
		cfs.addToList(t, cfs.idleList)
	case ThreadBlocked:
		cfs.addToList(t, cfs.blockedList)
	case ThreadRunnable:
		cfs.addToRunQueue(t)
	case ThreadRunning:
		cfs.runningThread = t
	case ThreadThrottled:
		cfs.addToList(t, cfs.throttledList)
	case ThreadStopped:
		// In the case when the Thread is Stopped, we do nothing
		// The thread removal happens naturally
	}

	return nil

}
