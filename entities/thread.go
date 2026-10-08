package entities

import "fmt"

// ThreadStatus represents the current state of a thread
type ThreadStatus string
type ThreadID string

const (
	ThreadIdle      ThreadStatus = "Idle"
	ThreadRunnable  ThreadStatus = "Runnable"
	ThreadRunning   ThreadStatus = "Running"
	ThreadBlocked   ThreadStatus = "Blocked" // Due to IO Blocking, including network possibly
	ThreadThrottled ThreadStatus = "Throttled"
	ThreadStopped   ThreadStatus = "Stopped"
)

type Thread struct {
	ID     ThreadID
	Task   *Task
	Worker *Worker

	status      ThreadStatus
	vRunTime    float64
	scheduledAt float64 // simTime when this thread last started running
}

// NewThread creates a new thread in the Idle state
func NewThread(index int, w *Worker) *Thread {

	threadID := ThreadID(fmt.Sprintf("%s_thread-%d", w.ID, index))

	return &Thread{
		ID:       threadID,
		status:   ThreadIdle,
		Task:     nil,
		Worker:   w,
		vRunTime: 0,
	}
}

func (t *Thread) Status() ThreadStatus          { return t.status }
func (t *Thread) SetStatus(status ThreadStatus) { t.status = status }

func (t *Thread) VRunTime() float64            { return t.vRunTime }
func (t *Thread) SetVRunTime(vRunTime float64) { t.vRunTime = vRunTime }

func (t *Thread) ScheduledAt() float64     { return t.scheduledAt }
func (t *Thread) SetScheduledAt(v float64) { t.scheduledAt = v }

func (t *Thread) IsIdle() bool { return t.status == ThreadIdle }

func (t *Thread) UpdateVRunTime(simTime float64)          { t.vRunTime += t.LastRunningTime(simTime) }
func (t *Thread) UpdateTaskTime(simTime float64)          { t.Task.TimeLeft -= t.LastRunningTime(simTime) }
func (t *Thread) LastRunningTime(simTime float64) float64 { return simTime - t.scheduledAt }

func (t *Thread) String() string {
	return fmt.Sprintf("Thread{id=%s, vruntime=%.3f, status=%v, workerId=%v,}",
		t.ID, t.vRunTime, t.status, t.Worker.ID)
}
