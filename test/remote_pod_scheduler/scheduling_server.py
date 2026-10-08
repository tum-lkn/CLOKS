"""
Simple Flask server for testing the RemotePodScheduler scheduling endpoint.

Usage:
    python scheduling_server.py [--port PORT] [--strategy STRATEGY]

The server exposes POST /schedule and responds with a node name recommendation.

Strategies:
  - round_robin: Cycles through nodes in order
  - random: Selects a random node
  - least_pods: Tracks pod assignments and selects node with fewest pods

Note: This is a stateful server for testing purposes. In production, the remote
scheduler would query InfluxDB or another data store for actual cluster state.
"""

import argparse
from flask import Flask, request, jsonify
import random
from collections import defaultdict

app = Flask(__name__)

# Global state for tracking (simulates what would be in InfluxDB)
pod_counts = defaultdict(int)  # node_name -> count
round_robin_index = 0
NUM_NODES = 4  # Default number of nodes (can be overridden)

# Strategy selection
STRATEGY = "round_robin"


@app.post("/schedule")
def schedule():
    global round_robin_index
    
    data = request.get_json(force=True)
    
    sim_time = data.get("sim_time", 0.0)
    pod_id = data.get("pod_id", "")
    deployment_name = data.get("deployment_name", "")
    cpu_request = data.get("cpu_request", 0.0)
    
    # Generate node names (assuming nodes are named node-0, node-1, etc.)
    node_names = [f"node-{i}" for i in range(NUM_NODES)]
    
    if STRATEGY == "round_robin":
        selected_node = node_names[round_robin_index % NUM_NODES]
        round_robin_index += 1
        reason = f"Round-robin selection (index {round_robin_index - 1})"
    
    elif STRATEGY == "random":
        selected_node = random.choice(node_names)
        reason = f"Random selection"
    
    elif STRATEGY == "least_pods":
        # Select the node with the fewest pods
        selected_node = min(node_names, key=lambda n: pod_counts[n])
        pod_counts[selected_node] += 1
        reason = f"Least pods strategy (current count: {pod_counts[selected_node]})"
    
    else:
        # Default to round-robin
        selected_node = node_names[round_robin_index % NUM_NODES]
        round_robin_index += 1
        reason = f"Default round-robin"
    
    app.logger.info(
        f"[{sim_time:.2f}s] Scheduled pod '{pod_id}' (deployment: {deployment_name}, "
        f"CPU: {cpu_request:.2f}) -> {selected_node} ({reason})"
    )
    
    return jsonify({
        "node_name": selected_node,
        "reason": reason,
    })


@app.post("/reset")
def reset():
    """Reset internal state (useful for testing)"""
    global round_robin_index, pod_counts
    round_robin_index = 0
    pod_counts.clear()
    return jsonify({"status": "reset"})


@app.get("/stats")
def stats():
    """Return current pod distribution (for debugging)"""
    return jsonify({
        "pod_counts": dict(pod_counts),
        "round_robin_index": round_robin_index,
        "strategy": STRATEGY,
        "num_nodes": NUM_NODES,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RemotePodScheduler test scheduling server")
    parser.add_argument("--port", type=int, default=8081, help="Port to listen on (default: 8081)")
    parser.add_argument("--strategy", type=str, default="round_robin", 
                        choices=["round_robin", "random", "least_pods"],
                        help="Scheduling strategy (default: round_robin)")
    parser.add_argument("--num-nodes", type=int, default=4, help="Number of nodes in the cluster (default: 4)")
    args = parser.parse_args()
    
    STRATEGY = args.strategy
    NUM_NODES = args.num_nodes
    
    print(f"Starting RemotePodScheduler server on port {args.port}")
    print(f"Strategy: {STRATEGY}")
    print(f"Number of nodes: {NUM_NODES}")
    print(f"Endpoints:")
    print(f"  POST /schedule - Schedule a pod")
    print(f"  POST /reset    - Reset internal state")
    print(f"  GET  /stats    - View current statistics")
    
    app.run(host="127.0.0.1", port=args.port)
