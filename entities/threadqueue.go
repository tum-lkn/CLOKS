package entities

// ThreadQueue implements a priority queue of threads ordered by vruntime
type ThreadQueue []*Thread

func (tq ThreadQueue) Len() int { return len(tq) }

func (tq ThreadQueue) Less(i, j int) bool {
	// Lower vruntime has higher priority (runs first)
	return tq[i].VRunTime() < tq[j].VRunTime()
}

func (tq ThreadQueue) Swap(i, j int) {
	tq[i], tq[j] = tq[j], tq[i]
}

func (tq *ThreadQueue) Push(x interface{}) {
	*tq = append(*tq, x.(*Thread))
}

func (tq *ThreadQueue) Pop() interface{} {
	if tq.IsEmpty() {
		return nil
	}
	old := *tq
	n := len(old)
	thread := old[n-1]
	*tq = old[0 : n-1]
	return thread
}

// Peek returns the first element in the queue without removing it.
// Returns nil if queue is empty.
func (tq ThreadQueue) Peek() *Thread {
	if tq.IsEmpty() {
		return nil
	}
	return tq[0]
}

// MinVRunTime returns the minimum vruntime in the queue
// Returns -1 if queue is empty
func (tq ThreadQueue) MinVRunTime() float64 {
	if tq.IsEmpty() {
		return 0
	}
	return tq[0].VRunTime()
}

func (tq ThreadQueue) IsEmpty() bool {
	return len(tq) == 0
}
