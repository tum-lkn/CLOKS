package entities

import (
	"fmt"
	"network-simulator/simrand"
)

// Worker represents a worker process with its own thread pool
// Mirrors the Gunicorn model where each worker is a separate process

type WorkerID string
type Worker struct {
	ID  WorkerID
	CPU *CPU
	Pod *Pod

	numThreads   int // Number of threads in this worker
	threads      []*Thread
	node         *Node
	pendingTasks []*Task
}

// NewWorker creates a new worker with the specified number of threads
func NewWorker(index int, numThreads int, cpu *CPU, pod *Pod) *Worker {

	workerID := WorkerID(fmt.Sprintf("%s_worker-%d", pod.Name, index))

	w := &Worker{
		ID:           workerID,
		numThreads:   numThreads,
		threads:      nil,
		CPU:          cpu,
		Pod:          pod,
		node:         pod.Node,
		pendingTasks: make([]*Task, 0),
	}

	// Create the threads and add them to the corresponding worker
	// and to the corresponding CPUScheduler
	threads := make([]*Thread, numThreads)
	for i := 0; i < numThreads; i++ {
		threads[i] = NewThread(i, w)
		w.CPU.Scheduler.AddThread(threads[i])
	}

	w.threads = threads

	return w
}

// HasQueuedTasks returns true if worker has tasks waiting in queue
func (w *Worker) HasQueuedTasks() bool {
	return len(w.pendingTasks) > 0
}

func (w *Worker) HasAvailableThreads() bool {
	for _, t := range w.threads {
		if t.IsIdle() {
			return true
		}
	}
	return false
}

// RandomAvailableThread returns one random idle thread from this worker.
// It returns nil if no thread is currently available.
func (w *Worker) RandomAvailableThread() *Thread {
	available := make([]*Thread, 0)

	for _, t := range w.threads {
		if t.IsIdle() {
			available = append(available, t)
		}
	}

	if len(available) == 0 {
		return nil
	}

	return available[simrand.Intn(len(available))]
}

func (w *Worker) IsIdle() bool {
	// Added Newly
	if len(w.pendingTasks) != 0 {
		return false
	}

	for _, t := range w.threads {
		if !t.IsIdle() {
			return false
		}
	}
	return true
}

func (w *Worker) EnqueueTask(t *Task) {
	w.pendingTasks = append(w.pendingTasks, t)
}

func (w *Worker) PopTask() *Task {
	t := w.pendingTasks[0]
	w.pendingTasks = w.pendingTasks[1:]
	return t
}

func (w *Worker) PendingTasks() []*Task {
	return w.pendingTasks
}

func (w *Worker) Threads() []*Thread {
	return w.threads
}
