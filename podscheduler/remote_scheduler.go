package podscheduler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"network-simulator/entities"
	"network-simulator/logger"
)

type RemotePodScheduler struct {
	httpClient *http.Client
	endpoint   string
}

func NewRemotePodScheduler(endpoint string, remoteTimeoutSeconds int) *RemotePodScheduler {
	return &RemotePodScheduler{
		httpClient: &http.Client{Timeout: time.Duration(remoteTimeoutSeconds) * time.Second},
		endpoint:   endpoint,
	}
}

type remotePodSchedulerRequest struct {
	SimTime        float64 `json:"sim_time"`
	PodID          int     `json:"pod_id"`
	DeploymentName string  `json:"deployment_name"`
	CpuRequest     float64 `json:"cpu_request"`
}

type remotePodSchedulerResponse struct {
	NodeName string `json:"node_name"`
	Reason   string `json:"reason"`
}

func (r *RemotePodScheduler) SchedulePod(pod *entities.Pod, nodes []*entities.Node) *SchedulingResult {
	simTime := pod.CreatedAt

	payload := remotePodSchedulerRequest{
		SimTime:        simTime,
		PodID:          pod.ID,
		DeploymentName: pod.Deployment.Name,
		CpuRequest:     pod.CPURequest,
	}

	body, _ := json.Marshal(payload)

	resp, err := r.httpClient.Post(r.endpoint, "application/json", bytes.NewReader(body))
	if err != nil {
		panic(fmt.Sprintf("RemotePodScheduler: HTTP POST to %s failed: %v", r.endpoint, err))
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		panic(fmt.Sprintf("RemotePodScheduler: unexpected status %d from %s", resp.StatusCode, r.endpoint))
	}

	var result remotePodSchedulerResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		panic(fmt.Sprintf("RemotePodScheduler: failed to decode response: %v", err))
	}

	if result.NodeName == "" {
		panic(fmt.Sprintf("RemotePodScheduler: empty node_name returned for pod %d", pod.ID))
	}

	// Find the node with the given name
	var selectedNode *entities.Node
	for _, node := range nodes {
		if node.Name == result.NodeName {
			selectedNode = node
			break
		}
	}

	if selectedNode == nil {
		panic(fmt.Sprintf("RemotePodScheduler: returned node_name '%s' does not exist in cluster", result.NodeName))
	}

	schedulingResult := NewSchedulingResult()
	schedulingResult.SelectedNode = selectedNode
	schedulingResult.SchedulingStatus = "Success"
	schedulingResult.Reason = fmt.Sprintf("Remote: %s", result.Reason)

	logger.GetLogger(simTime).
		WithField("pod_id", pod.ID).
		WithField("deployment_name", pod.Deployment.Name).
		WithField("node_name", result.NodeName).
		Debug("Remote pod scheduler recommendation accepted")

	return schedulingResult
}
