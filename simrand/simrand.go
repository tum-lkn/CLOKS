package simrand

import (
	"math"
	"math/rand"
	"sync"
)

var (
	mu  sync.Mutex
	rng = rand.New(rand.NewSource(1))
)

// SetSeed resets the simulator RNG with a deterministic seed.
func SetSeed(seed int64) {
	mu.Lock()
	defer mu.Unlock()
	rng = rand.New(rand.NewSource(seed))
}

func Intn(n int) int {
	mu.Lock()
	defer mu.Unlock()
	return rng.Intn(n)
}

func Float64() float64 {
	mu.Lock()
	defer mu.Unlock()
	return rng.Float64()
}

func Perm(n int) []int {
	mu.Lock()
	defer mu.Unlock()
	return rng.Perm(n)
}

// Exponential samples from an exponential distribution with rate parameter lambda.
func Exponential(lambda float64) float64 {
	mu.Lock()
	defer mu.Unlock()

	u := rng.Float64()
	for u == 0 {
		u = rng.Float64()
	}

	return -math.Log(u) / lambda
}

// Gaussian samples from a normal distribution with the provided mean and variance.
func Gaussian(mean, variance float64) float64 {
	mu.Lock()
	defer mu.Unlock()

	if variance <= 0 {
		return mean
	}

	u1 := rng.Float64()
	for u1 == 0 {
		u1 = rng.Float64()
	}
	u2 := rng.Float64()

	z := math.Sqrt(-2*math.Log(u1)) * math.Cos(2*math.Pi*u2)
	return mean + z*math.Sqrt(variance)
}
