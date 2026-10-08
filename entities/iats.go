package entities

import (
	"math"
	"network-simulator/simrand"

	"github.com/google/uuid"
)

// Constants
const (
	SmallConstant = 1e-10
	BigConstant   = math.MaxFloat64
)

type IATDistribution string

const (
	IATUniform     IATDistribution = "uniform"
	IATExponential IATDistribution = "exponential"
)

// InterArrivalTime struct
type InterArrivalTime struct {
	rates        []float64
	changePoints []float64
	SeviceName   string
	ProfileName  string
	Distribution IATDistribution
	IATJitterS   float64
	RequestIndex int
	idx          int
}

// NewInterArrivalTime constructor
func NewInterArrivalTime(rates []float64, changePoints []float64, serviceName, profileName string, distribution string, iatJitterMs float64) *InterArrivalTime {
	// Replace zeros in rates with SmallConstant
	for i, rate := range rates {
		if rate == 0 {
			rates[i] = SmallConstant
		}
	}

	// Append BigConstant if rates and changePoints mismatch
	if len(rates) == len(changePoints)+1 {
		changePoints = append(changePoints, BigConstant)
	}

	return &InterArrivalTime{
		rates:        rates,
		changePoints: changePoints,
		SeviceName:   serviceName,
		ProfileName:  profileName,
		Distribution: IATDistribution(distribution),
		IATJitterS:   iatJitterMs / 1000.0,
		idx:          0,
		RequestIndex: 1, // Start from index 1 because the first request is already Request 0
	}
}

// Call method to calculate the inter-arrival time
func (i *InterArrivalTime) Call(simTime float64) (float64, int) {

	if simTime >= i.changePoints[i.idx] {
		i.idx++
	}

	currIndex := i.RequestIndex
	i.RequestIndex++

	rate := i.rates[i.idx]
	baseIAT := 1.0 / rate
	if i.Distribution == IATExponential { // Exponential
		baseIAT = simrand.Exponential(rate)
	}

	if i.IATJitterS > 0 {
		jitter := (simrand.Float64()*2.0 - 1.0) * i.IATJitterS
		baseIAT += jitter
	}

	if baseIAT <= 0 {
		baseIAT = SmallConstant
	}

	return baseIAT, currIndex
}

// GetUUID generates a random UUID
func (i *InterArrivalTime) GetUUID() string {
	return uuid.New().String()
}
