package entities

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type RemoteHPA struct {
	Deployment *Deployment
	httpClient *http.Client
	endpoint   string
	syncPeriod float64
}

func NewRemoteHPA(d *Deployment, endpoint string, syncPeriod float64, remoteTimeoutSeconds int) *RemoteHPA {
	if remoteTimeoutSeconds <= 0 {
		panic("RemoteHPA: remote_timeout_seconds must be set and greater than 0")
	}
	return &RemoteHPA{
		Deployment: d,
		httpClient: &http.Client{Timeout: time.Duration(remoteTimeoutSeconds) * time.Second},
		endpoint:   endpoint,
		syncPeriod: syncPeriod,
	}
}

func (h *RemoteHPA) GetDeployment() *Deployment {
	return h.Deployment
}

func (h *RemoteHPA) GetSyncPeriod() float64 {
	return h.syncPeriod
}

type remoteHPARequest struct {
	SimTime        float64 `json:"sim_time"`
	DeploymentName string  `json:"deployment_name"`
	NumActivePods  int     `json:"num_active_pods"`
	NumRunningPods int     `json:"num_running_pods"`
}

type remoteHPAResponse struct {
	DeploymentName string `json:"deployment_name"`
	Action         string `json:"action"`
	Pods           int    `json:"pods"`
}

func (h *RemoteHPA) GetScalingAction(simTime float64) (HPAAction, int) {
	payload := remoteHPARequest{
		SimTime:        simTime,
		DeploymentName: h.Deployment.Name,
		NumActivePods:  h.Deployment.GetNumActivePods(),
		NumRunningPods: h.Deployment.GetNumRunningPods(),
	}

	body, _ := json.Marshal(payload)

	resp, err := h.httpClient.Post(h.endpoint, "application/json", bytes.NewReader(body))
	if err != nil {
		panic(fmt.Sprintf("RemoteHPA: HTTP POST to %s failed: %v", h.endpoint, err))
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		panic(fmt.Sprintf("RemoteHPA: unexpected status %d from %s", resp.StatusCode, h.endpoint))
	}

	var result remoteHPAResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		panic(fmt.Sprintf("RemoteHPA: failed to decode response: %v", err))
	}

	switch HPAAction(result.Action) {
	case HPAScaleOut:
		return HPAScaleOut, result.Pods
	case HPAScaleIn:
		return HPAScaleIn, result.Pods
	default:
		return HPADoNothing, 0
	}
}

func (h *RemoteHPA) GetCPULoadMeasurements() []float64 {
	// STUB
	return nil
}

func (h *RemoteHPA) GetMeanCPUUtilization() float64 {
	// STUB
	return -1
}
