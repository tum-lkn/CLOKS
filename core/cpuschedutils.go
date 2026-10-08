package core

import "network-simulator/entities"

func accountThreadExecution(thread *entities.Thread, simTime float64) {
	thread.UpdateVRunTime(simTime)
	thread.UpdateTaskTime(simTime)

	if thread.Task.TimeLeft < 1e-6 && thread.Task.TimeLeft >= 0 {
		thread.Task.TimeLeft = 0
	} // Kinda smelly code, here we round off any errors that we might have for the Task.TimeLeft

	pod := thread.Worker.Pod
	lastRunningTime := thread.LastRunningTime(simTime)
	pod.ConsumeAvailableQuotaTime(lastRunningTime)
	pod.IncrementCPUSeconds(simTime, lastRunningTime)
}

func transitionThreadAfterExecution(thread *entities.Thread, schedPointer *entities.CPUScheduler, pod *entities.Pod) {
	sched := *schedPointer

	if pod.AvailableQuotaTime() <= 0 {
		sched.TransitionThread(thread, entities.ThreadThrottled)
		pod.SetRunnableThreadsToThrottled()
	} else {
		sched.TransitionThread(thread, entities.ThreadRunnable)
	}
}
