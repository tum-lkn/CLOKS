package entities

type TaskStatus string

const (
	TaskStarted   TaskStatus = "Started"
	TaskCompleted TaskStatus = "Completed"
)

// Task represents a computational task that needs to be scheduled on a CPU
type Task struct {
	ID           int
	CreationTime float64
	BurstTime    float64  // Total CPU time needed
	TimeLeft     float64  // Remaining CPU time needed
	Pod          *Pod     // The pod this task belongs to
	Request      *Request // The request that created this task
	Priority     int      // Task priority for scheduling
	Thread       *Thread

	status      TaskStatus
	completedAt float64
}

// NewTask creates a new task with the given parameters
func NewTask(id int, request *Request, creationTime float64, burstTime float64, pod *Pod) *Task {
	return &Task{
		ID:           id,
		CreationTime: creationTime,
		BurstTime:    burstTime,
		TimeLeft:     burstTime,
		Pod:          pod,
		Request:      request, // Will be set when the task is created from a request
		Priority:     0,
		Thread:       nil,

		status:      TaskStarted,
		completedAt: -1,
	}
}

func (task *Task) IsUnassigned() bool          { return task.Thread == nil }
func (task *Task) Status() TaskStatus          { return task.status }
func (task *Task) SetStatus(status TaskStatus) { task.status = status }

func (task *Task) CompletedAt() float64               { return task.completedAt }
func (task *Task) SetCompletedAt(completedAt float64) { task.completedAt = completedAt }
