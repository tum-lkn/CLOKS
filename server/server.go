package server

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"network-simulator/core"
	"network-simulator/events"
)

type Server struct {
	simulator core.SimulatorInterface
}

type Response struct {
	Status  string `json:"status"`
	Message string `json:"message"`
}

func NewServer(sim core.SimulatorInterface) *Server {
	return &Server{
		simulator: sim,
	}
}

func (s *Server) pauseHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.simulator.Pause()

	response := Response{
		Status:  "success",
		Message: "Simulation paused",
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
	log.Println("Simulation paused")
}

func (s *Server) resumeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	s.simulator.Resume()

	response := Response{
		Status:  "success",
		Message: "Simulation resumed",
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
	log.Println("Simulation resumed")
}

func (s *Server) statusHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	paused := s.simulator.IsPaused()
	status := "running"
	if paused {
		status = "paused"
	}

	response := Response{
		Status:  status,
		Message: fmt.Sprintf("Simulation is currently %s", status),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *Server) timeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	currentTime := s.simulator.GetSimTime()

	response := Response{
		Status:  "success",
		Message: fmt.Sprintf("Current simulation time: %.6f", currentTime),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *Server) schedulePauseHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse JSON request body
	var requestBody struct {
		Time float64 `json:"time"`
	}

	if err := json.NewDecoder(r.Body).Decode(&requestBody); err != nil {
		http.Error(w, "Invalid JSON format", http.StatusBadRequest)
		return
	}

	pauseTime := requestBody.Time
	if pauseTime == 0 {
		http.Error(w, "Missing 'time' field", http.StatusBadRequest)
		return
	}

	// Check that the pause time is in the future
	currentTime := s.simulator.GetSimTime()
	if pauseTime <= currentTime {
		http.Error(w, fmt.Sprintf("Pause time (%.6f) must be greater than current time (%.6f)", pauseTime, currentTime), http.StatusBadRequest)
		return
	}

	// Schedule the pause event
	pauseEvent := events.NewSimPauseEvent(pauseTime)
	s.simulator.ScheduleEvent(pauseEvent)

	response := Response{
		Status:  "success",
		Message: fmt.Sprintf("Pause scheduled for simulation time %.6f", pauseTime),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
	log.Printf("Pause scheduled for simulation time %.6f", pauseTime)
}

func (s *Server) updateIATHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse JSON request body
	var requestBody struct {
		ProfileName  string    `json:"profile_name"`
		Rates        []float64 `json:"rates"`
		ChangePoints []float64 `json:"change_points"`
	}

	if err := json.NewDecoder(r.Body).Decode(&requestBody); err != nil {
		http.Error(w, "Invalid JSON format", http.StatusBadRequest)
		return
	}

	// Validate required fields
	if requestBody.ProfileName == "" {
		http.Error(w, "Missing 'profile_name' field", http.StatusBadRequest)
		return
	}

	if len(requestBody.Rates) == 0 {
		http.Error(w, "Missing or empty 'rates' field", http.StatusBadRequest)
		return
	}

	// Validate rates are positive
	for i, rate := range requestBody.Rates {
		if rate < 0 {
			http.Error(w, fmt.Sprintf("Rate at index %d must be non-negative, got %.6f", i, rate), http.StatusBadRequest)
			return
		}
	}

	// Validate change points if provided
	if len(requestBody.ChangePoints) > 0 {
		// Check that change points are in ascending order
		for i := 1; i < len(requestBody.ChangePoints); i++ {
			if requestBody.ChangePoints[i] <= requestBody.ChangePoints[i-1] {
				http.Error(w, fmt.Sprintf("Change points must be in ascending order. Point at index %d (%.6f) is not greater than previous point (%.6f)",
					i, requestBody.ChangePoints[i], requestBody.ChangePoints[i-1]), http.StatusBadRequest)
				return
			}
		}

		// Validate that change points are in the future
		currentTime := s.simulator.GetSimTime()
		if len(requestBody.ChangePoints) > 0 && requestBody.ChangePoints[0] <= currentTime {
			http.Error(w, fmt.Sprintf("First change point (%.6f) must be greater than current simulation time (%.6f)",
				requestBody.ChangePoints[0], currentTime), http.StatusBadRequest)
			return
		}
	}

	// Check if profile exists
	profile := s.simulator.GetProfile(requestBody.ProfileName)
	if profile == nil {
		http.Error(w, fmt.Sprintf("Profile '%s' not found", requestBody.ProfileName), http.StatusNotFound)
		return
	}

	// The request is validated and acknowledged; the running IAT profile is not changed

	response := Response{
		Status: "success",
		Message: fmt.Sprintf("IAT profile '%s' update request received with %d rates and %d change points",
			requestBody.ProfileName, len(requestBody.Rates), len(requestBody.ChangePoints)),
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
	log.Printf("IAT profile update requested for '%s' with %d rates and %d change points",
		requestBody.ProfileName, len(requestBody.Rates), len(requestBody.ChangePoints))
}

func (s *Server) Start(port string) error {
	http.HandleFunc("/pause", s.pauseHandler)
	http.HandleFunc("/resume", s.resumeHandler)
	http.HandleFunc("/status", s.statusHandler)
	http.HandleFunc("/time", s.timeHandler)
	http.HandleFunc("/schedule-pause", s.schedulePauseHandler)
	http.HandleFunc("/update-iat", s.updateIATHandler)

	// http.HandlerFunc("/pa", s.statusHandler)

	log.Printf("Server starting on port %s", port)
	return http.ListenAndServe(":"+port, nil)
}
