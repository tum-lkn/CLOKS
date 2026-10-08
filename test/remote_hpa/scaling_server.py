"""
Simple Flask server for testing the RemoteHPA scaling endpoint.

Usage:
    python scaling_server.py [--port PORT]

The server exposes POST /scaling and responds with a scaling action:
  - "ScaleOut" (with the number of pods to add) until num_active_pods reaches 10
  - "DoNothing" once num_active_pods >= 10
"""

import argparse
from flask import Flask, request, jsonify

MAX_PODS = 10

app = Flask(__name__)

@app.post("/scaling")
def scaling():
    data = request.get_json(force=True)

    deployment_name = data.get("deployment_name", "")
    num_active_pods = int(data.get("num_active_pods", 0))

    if num_active_pods < MAX_PODS:
        action = "ScaleOut"
        pods = MAX_PODS - num_active_pods
    else:
        action = "DoNothing"
        pods = 0

    return jsonify({
        "deployment_name": deployment_name,
        "action": action,
        "pods": pods,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RemoteHPA test scaling server")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")
    args = parser.parse_args()

    app.run(host="127.0.0.1", port=args.port)
