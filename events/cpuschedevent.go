package events

import "network-simulator/entities"

// TaskCreateEvent represents the creation of a new task
type TaskCreateEvent struct {
	BaseEvent
	Task *entities.Task
	Pod  *entities.Pod
}

// NewTaskCreateEvent creates a new task creation event
func NewTaskCreateEvent(time float64, task *entities.Task, pod *entities.Pod) *TaskCreateEvent {
	return &TaskCreateEvent{
		BaseEvent: BaseEvent{Time: time},
		Task:      task,
		Pod:       pod,
	}
}

// TaskWakeupEvent represents a task becoming runnable again
type ThreadWakeupEvent struct {
	BaseEvent
	Thread *entities.Thread
}

// NewTaskWakeupEvent creates a new task wakeup event
func NewThreadWakeupEvent(time float64, thread *entities.Thread) *ThreadWakeupEvent {
	return &ThreadWakeupEvent{
		BaseEvent: BaseEvent{Time: time},
		Thread:    thread,
	}
}

// TaskScheduleEvent represents a task being selected to run
type ThreadScheduleEvent struct {
	BaseEvent
	CPUScheduler *entities.CPUScheduler
}

// NewTaskScheduleEvent creates a new task schedule event
func NewThreadScheduleEvent(time float64, cpuScheduler *entities.CPUScheduler) *ThreadScheduleEvent {
	return &ThreadScheduleEvent{
		BaseEvent:    BaseEvent{Time: time},
		CPUScheduler: cpuScheduler,
	}
}

// TaskCompleteEvent represents a task completing execution
type TaskCompleteEvent struct {
	BaseEvent
	Task *entities.Task
}

// NewTaskCompleteEvent creates a new task completion event
func NewTaskCompleteEvent(time float64, task *entities.Task) *TaskCompleteEvent {
	return &TaskCompleteEvent{
		BaseEvent: BaseEvent{Time: time},
		Task:      task,
	}
}

type TaskErrorEvent struct {
	BaseEvent
	Task *entities.Task
}

func NewTaskErrorEvent(time float64, task *entities.Task) *TaskErrorEvent {
	return &TaskErrorEvent{
		BaseEvent: BaseEvent{Time: time},
		Task:      task,
	}
}

// The QuotaReplenishEvent is used in the case when
type QuotaReplenishEvent struct {
	BaseEvent
	Node *entities.Node
}

func NewQuotaReplenishEvent(time float64, node *entities.Node) *QuotaReplenishEvent {
	return &QuotaReplenishEvent{
		BaseEvent: BaseEvent{Time: time},
		Node:      node,
	}
}
