# Remote Pod Scheduler Testing

This directory contains a test server for the Remote Pod Scheduler feature.

## Overview

The Remote Pod Scheduler allows the simulator to delegate pod placement decisions to an external service. This is similar to the Remote HPA feature, but for scheduling pods to nodes instead of scaling decisions.

## Quick Start

### 1. Start the Remote Scheduling Server

```bash
cd test/remote_pod_scheduler
python scheduling_server.py --port 8081 --strategy round_robin --num-nodes 4
```

### 2. Configure the Simulator

Edit `conf/simulation.yaml` and uncomment the remote pod scheduler line:

```yaml
pod_scheduler: remote.yaml
```

### 3. Run the Simulator

```bash
./network-simulator
```

## Scheduling Strategies

The test server supports three strategies:

- **round_robin** (default): Cycles through nodes in order
- **random**: Selects a random node
- **least_pods**: Tracks assignments and selects the node with fewest pods

Example with different strategy:
```bash
python scheduling_server.py --strategy least_pods --num-nodes 4
```

## API Endpoints

### POST /schedule

Schedules a pod and returns a node recommendation.

**Request:**
```json
{
  "sim_time": 123.45,
  "pod_id": "burn-cpu-7",
  "deployment_name": "burn-cpu",
  "cpu_request": 0.5
}
```

**Response:**
```json
{
  "node_name": "node-2",
  "reason": "Round-robin selection (index 2)"
}
```

### POST /reset

Resets internal state (pod counts, round-robin index).

### GET /stats

Returns current scheduling statistics:

```json
{
  "pod_counts": {"node-0": 3, "node-1": 2, "node-2": 5, "node-3": 1},
  "round_robin_index": 11,
  "strategy": "round_robin",
  "num_nodes": 4
}
```

## Configuration

### Remote Mode

`conf/pod_scheduler/remote.yaml`:
```yaml
mode: remote
scheduling_policy: highest_cpu  # Not used in remote mode
endpoint: http://localhost:8081/schedule
remote_timeout_seconds: 5
```

### Local Mode

`conf/pod_scheduler/local.yaml`:
```yaml
mode: local
scheduling_policy: highest_cpu  # Options: default, consolidation, highest_cpu
```

## Design Notes

### Minimal Request Payload

The request sent to the remote scheduler contains only minimal information:
- `sim_time`: Current simulation time (for querying time-series data)
- `pod_id`: Pod identifier
- `deployment_name`: Deployment/service name
- `cpu_request`: Pod CPU request

All other cluster state (current pod placements, node resources, etc.) should be retrieved by the remote service from InfluxDB or other metrics stores.

### Error Handling

The Remote Pod Scheduler **does not fall back** to local scheduling. If the remote call fails for any reason, the simulator will panic with a descriptive error message:

- HTTP connection failure
- Non-200 HTTP status
- Invalid JSON response
- Empty node name in response
- Node name doesn't exist in cluster

This ensures that scheduling behavior is predictable and failures are immediately visible.

## Production Considerations

For production use, the remote scheduler would:

1. Query InfluxDB for current cluster state:
   - Pod distribution across nodes
   - Node CPU/memory utilization
   - Historical scheduling decisions
   
2. Implement sophisticated scheduling logic:
   - Multi-objective optimization
   - Machine learning models
   - Custom business logic
   
3. Return node recommendations based on complete cluster state

The test server provided here uses simple in-memory state tracking for demonstration purposes.
