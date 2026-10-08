package events

import (
	"time"
)

type SimPerfEvent struct {
	BaseEvent
	WallClockTime  float64
	SpeedUpFactor  float64
	SamplingPeriod float64
}

func NewSimPerfEvent(simTime float64, prevWallClockTime, prevSimTime, samplingPeriod float64) *SimPerfEvent {
	wallClockTime := float64(time.Now().UnixMilli())

	speedUpFactor := (simTime - prevSimTime) / (wallClockTime - prevWallClockTime) * 1000

	return &SimPerfEvent{
		BaseEvent:      BaseEvent{Time: simTime},
		WallClockTime:  wallClockTime,
		SpeedUpFactor:  speedUpFactor,
		SamplingPeriod: samplingPeriod,
	}
}

type SimStartEvent struct {
	BaseEvent
}

func NewSimStartEvent(simTime float64) *SimStartEvent {
	return &SimStartEvent{
		BaseEvent: BaseEvent{Time: simTime},
	}
}

type SimStopEvent struct {
	BaseEvent
}

func NewSimStopEvent(simTime float64) *SimStopEvent {
	return &SimStopEvent{
		BaseEvent: BaseEvent{Time: simTime},
	}
}

type SimPauseEvent struct {
	BaseEvent
}

func NewSimPauseEvent(simTime float64) *SimPauseEvent {
	return &SimPauseEvent{
		BaseEvent: BaseEvent{Time: simTime},
	}
}
