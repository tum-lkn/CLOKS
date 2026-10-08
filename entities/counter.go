package entities

import (
	"fmt"
	"math"
	"sort"
)

type RCTMeasurement struct {
	arrivalTime   float64
	departureTime float64
	rct           float64
	completed     bool
	timeout       bool
	errored       bool
}

type RCTCounter struct {
	ServiceName    string
	FlushingPeriod float64

	lastCollectionStartTime float64
	percentiles             []float64

	measurements map[int]*RCTMeasurement
}

func NewRCTCounter(serviceName string, flushingPeriod float64) *RCTCounter {
	// Initialize percentiles from 0 to 100 in 5% intervals
	percentiles := make([]float64, 21)
	for i := 0; i <= 20; i++ {
		percentiles[i] = float64(i) * 5
	}

	return &RCTCounter{
		ServiceName:             serviceName,
		FlushingPeriod:          flushingPeriod,
		measurements:            make(map[int]*RCTMeasurement),
		lastCollectionStartTime: 0,
		percentiles:             percentiles,
	}
}

func (r *RCTCounter) Observe(requestID int, departureTime, rct float64, timeout, errored bool) {
	// Record the measurement when the request completes
	r.measurements[requestID] = &RCTMeasurement{
		arrivalTime:   0, // Not needed anymore, but kept for backward compatibility
		departureTime: departureTime,
		rct:           rct,
		completed:     true,
		timeout:       timeout,
		errored:       errored,
	}
}

func (r *RCTCounter) getStatistics(data map[int]*RCTMeasurement) (map[string]float64, error) {
	// Check if the input slice is empty
	n := len(data)
	if n == 0 {
		return nil, fmt.Errorf("empty slice provided")
	}

	// Extract rct values into a separate slice
	rctValues := make([]float64, n)
	i := 0
	nrReqTimeout := 0
	nrReqError := 0
	for _, measurement := range data {
		rctValues[i] = measurement.rct
		if measurement.timeout {
			nrReqTimeout++
		}
		if measurement.errored {
			nrReqError++
		}
		i++
	}

	// Sort the rct values for percentile calculation
	sort.Float64s(rctValues)

	// Calculate min and max
	min := rctValues[0]
	max := rctValues[n-1]

	// Calculate mean
	sum := 0.0
	for _, value := range rctValues {
		sum += value
	}
	mean := sum / float64(n)

	// Calculate all percentiles
	percentileValues := make(map[string]float64)
	for _, percentile := range r.percentiles {
		pos := percentile / 100.0 * float64(n-1) // Position in the sorted array
		lowerIndex := int(math.Floor(pos))
		upperIndex := int(math.Ceil(pos))

		var percentileValue float64
		if lowerIndex == upperIndex {
			// Exact position, no interpolation needed
			percentileValue = rctValues[lowerIndex]
		} else {
			// Interpolate between the two closest values
			lowerValue := rctValues[lowerIndex]
			upperValue := rctValues[upperIndex]
			weight := pos - float64(lowerIndex)
			percentileValue = lowerValue*(1-weight) + upperValue*weight
		}
		percentileValues[fmt.Sprintf("p%.0f", percentile)] = percentileValue
	}

	// Aggregate the results in a map
	stats := map[string]float64{
		"min":          min,
		"max":          max,
		"mean":         mean,
		"nrReq":        float64(n),
		"nrReqTimeout": float64(nrReqTimeout),
		"nrReqError":   float64(nrReqError),
	}

	// Add all percentile values to the stats map
	for k, v := range percentileValues {
		stats[k] = v
	}

	return stats, nil
}

func (r *RCTCounter) Flush(simTime float64) (stats map[string]float64, lastCollectionStart float64, err error) {
	if r.nextCollectionTime() > simTime {
		return nil, r.lastCollectionStartTime, nil
	}

	// Bucket requests by departure time in the current period
	currentPeriodMeasurements := make(map[int]*RCTMeasurement)
	for requestID, measurement := range r.measurements {
		if measurement.departureTime >= r.lastCollectionStartTime &&
			measurement.departureTime < r.nextCollectionTime() {
			currentPeriodMeasurements[requestID] = measurement
		}
	}

	// Report stats only if we have measurements in this period
	if len(currentPeriodMeasurements) == 0 {
		lastCollectionStartTime := r.lastCollectionStartTime
		r.lastCollectionStartTime = r.nextCollectionTime()
		return nil, lastCollectionStartTime, nil
	}

	// Calculate statistics for this period
	stats, err = r.getStatistics(currentPeriodMeasurements)

	lastCollectionStartTime := r.lastCollectionStartTime
	r.lastCollectionStartTime = r.nextCollectionTime()

	// Clean up measurements that were reported in this period
	for requestID := range currentPeriodMeasurements {
		delete(r.measurements, requestID)
	}

	return stats, lastCollectionStartTime, err
}

func (r *RCTCounter) nextCollectionTime() float64 {
	return r.lastCollectionStartTime + r.FlushingPeriod
}

func (r *RCTCounter) GetLastCollectionStartTime() float64 { return r.lastCollectionStartTime }
