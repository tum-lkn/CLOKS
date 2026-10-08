package entities

import "fmt"

// CPU represents a processor that can execute tasks

type CPUID string

type CPU struct {
	ID        CPUID
	Node      *Node        // The node this CPU belongs to
	Scheduler CPUScheduler // The scheduler assigned to this CPU
}

// NewCPU creates a new CPU instance
func NewCPU(index int, node *Node) *CPU {

	cpuID := CPUID(fmt.Sprintf("%s_cpu-%d", node.Name, index))

	cpu := &CPU{
		ID:        cpuID,
		Node:      node,
		Scheduler: nil,
	}

	cpuSched := NewCFSScheduler(cpu)
	cpu.Scheduler = cpuSched

	return cpu
}

func (c *CPU) IsIdle() bool {
	return c.Scheduler.IsIdle()
}
