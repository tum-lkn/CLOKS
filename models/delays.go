package models

import (
	"math"
	"network-simulator/simrand"
)

// DelayModel defines the interface for delay models.
type DelayModel interface {
	// Delay returns a simulated delay in seconds as float64.
	Delay() float64
}

// ConstantDelay represents a constant delay model.
type ConstantDelay struct {
	delayS float64
}

// NewConstantDelay creates a new ConstantDelay instance.
func NewConstantDelay(delayS float64) *ConstantDelay {
	return &ConstantDelay{delayS: delayS}
}

// Delay returns the constant delay.
func (c *ConstantDelay) Delay() float64 {
	return c.delayS
}

// GaussianDelay represents a Gaussian delay model.
type GaussianDelay struct {
	meanS   float64
	stdDevS float64
}

// NewGaussianDelay creates a new GaussianDelay instance.
func NewGaussianDelay(meanS, stdDevS float64) *GaussianDelay {
	return &GaussianDelay{
		meanS:   meanS,
		stdDevS: stdDevS,
	}
}

// Delay returns a delay based on a Gaussian distribution.
func (g *GaussianDelay) Delay() float64 {
	u1 := simrand.Float64()
	u2 := simrand.Float64()
	gaussian := math.Sqrt(-2*math.Log(u1)) * math.Cos(2*math.Pi*u2)
	delay := g.meanS + gaussian*g.stdDevS
	if delay < 0 {
		delay = 0 // Ensure no negative delay
	}
	return delay
}
