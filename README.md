# CLOKS

**A Control-Loop-Oriented Kubernetes Simulator for high-fidelity modeling of microservice architectures.**

CLOKS is a discrete-event simulator, written in Go, that models the three core Kubernetes control loops (**Load
Balancing**, the **Horizontal Pod Autoscaler**, and **Pod Scheduling**) together with request-level execution, a
CFS-style CPU scheduler, and cgroups-based CPU throttling. It predicts QoS (request completion times) and resource
usage (pod counts, CPU utilization) for a cluster configuration before you deploy it.

> The CLOKS paper has been accepted at **IEEE CCNC 2027** and is not yet published. This repository
> contains the simulator and everything needed to reproduce its results.

## Reproducing the paper results

[`experiments/reproduce_paper.sh`](experiments/reproduce_paper.sh) runs the experiments and creates the figures
and the accuracy table.

**Requirements**

- Go ≥ 1.23, to build the simulator.
- **Python 3.10 or 3.11**: the pinned packages in `requirements.txt` are not available for Python 3.12 or newer.
- Optional: LaTeX (`texlive-latex-extra`, `texlive-fonts-recommended`, `cm-super`, `dvipng`) for figures in the
  paper's font; without it, matplotlib's own text renderer is used.

After cloning the repository, set up a Python environment with the package versions used for the paper, with `venv` or with
[uv](https://docs.astral.sh/uv/) (which also downloads Python 3.10 if needed):

```bash
# venv                                       # uv
python3.10 -m venv .venv                     # uv venv --python 3.10
source .venv/bin/activate                    # source .venv/bin/activate
python -m pip install -r requirements.txt    # uv pip install -r requirements.txt
```

**Run**

```bash
experiments/reproduce_paper.sh --single-tier --clean
```

| Option | Effect |
|---|---|
| `--single-tier` | only the 8 single-tier experiments (Table II, Fig. 3, 4, 6a) |
| `--scalability` | only the scalability experiments (Fig. 6b) |
| *(none)* | both |
| `--clean` | delete earlier runs of these experiments first, so old and new results are not mixed |
| `--plots-only` | no simulations; recreate the figures and the table from existing runs |
| `--no-latex` | draw without LaTeX (automatic when LaTeX is not installed) |

**Results** are written to `experiments/figures/`; the raw data of every simulation stays in `experiments/runs/`
(see [Batch experiments](#batch-experiments)).

| File | Paper |
|---|---|
| `table2_single_tier_accuracy.tex` | Table II: time-averaged MAE of $rct_{p50}$, number of pods and CPU utilization; relative error of the mean $rct$; Δ Pod-Minutes |
| `fig3_baseline_timeseries.pdf` | Fig. 3: simulation vs. measurements over time (baseline) |
| `fig4_rct_percentiles.pdf` | Fig. 4: response time percentiles |
| `fig6a_speedup_per_experiment.pdf` | Fig. 6a: speedup over real time per experiment |
| `fig6b_speedup_vs_rps.pdf` | Fig. 6b: speedup vs. requests per second |
| `comparison/<EXPERIMENT>.png` | simulation vs. measurements, per experiment |

### Experiments

Each single-tier experiment runs 20 times (seeds 42–61) with the baseline shown in
[Configuration](#configuration): the CPU-bound `burn-cpu` service on four nodes.

| Paper # | Description | Config | Differs from the baseline in |
|---|---|---|---|
| 1 | Baseline: traffic rises in steps from 10 to 100 requests/s | `EXPERIMENT_0` | — |
| 2 | Traffic from a public trace | `EXPERIMENT_1` | traffic |
| 3 | Traffic rises, then falls again | `EXPERIMENT_12` | traffic |
| 4 | Traffic rises, then drops suddenly | `EXPERIMENT_13` | traffic |
| 5 | HPA threshold 0.10 | `EXPERIMENT_4` | `hpa_threshold: 0.10` |
| 6 | HPA threshold 0.30 | `EXPERIMENT_20` | `hpa_threshold: 0.30` |
| 7 | CPU limit 750 mCPU | `EXPERIMENT_19` | `cpu_request/limit: 750`, |
| 8 | CPU limit 1000 mCPU | `EXPERIMENT_8` | `cpu_request/limit: 1000` |

The scalability experiments (`SCALABILITY_0`–`9`) use 1,000–2,000 pods on `1000_cpus_nodes.yaml` with a constant
load from 1 to 4,000 requests/s.

### Measurement data

The measurements from the real Kubernetes cluster, which the simulation results are compared against (Table II,
Fig. 3, Fig. 4), are provided in `experiments/measurements/<EXPERIMENT>/`: one CSV file per run (e.g.
`EXPERIMENT_0/burn-cpu_EXPERIMENT_0_run_1.csv`), with one row every 5 seconds:

| Column | Meaning |
|---|---|
| `timestamp` | time of the sample |
| `rps_unknown_TO_burn-cpu` | requests per second |
| `rct_p50_unknown_TO_burn-cpu`, `rct_p90_…`, `rct_p95_…` | response time percentiles (ms) |
| `nr_pods_burn-cpu` | number of pods |
| `hpa_target_metric_burn-cpu` | CPU utilization reported to the HPA (%) |

## Features

| Layer | What is modeled |
|---|---|
| **Kubernetes** | Load balancer, HPA, Metrics Server, Kubelet, pod scheduler, pod lifecycle (`Pending` → `Ready` → `Terminating`) |
| **Application** | Services, per-pod workers and threads, request profiles, blocking and non-blocking upstream calls |
| **Infrastructure** | Nodes, CPUs, a preemptive CFS scheduler (`vruntime`), CPU requests/limits with quota throttling, inter-node latency |

- **Load balancing** (per service): `least_requests` (Istio default), `round_robin`, `random`, `ewma`.
- **HPA:** the upstream algorithm with periodic Metrics Server sampling, sync period, tolerance, min/max replicas,
  and separate scale-out/scale-in stabilization windows; or an external service (`mode: remote`).
- **Pod scheduling:** `default`, `consolidation`, `highest_cpu`, or an external scheduler (`mode: remote`).
- **Workloads:** constant, staircase and trace-driven arrivals (exponential inter-arrival times, optional jitter);
  multi-tier chains where each upstream call has a `trigger_at` point, a `probability` and a `blocking` flag;
  per-request timeouts.
- **Tooling:** batch runner with per-run configuration snapshots and seed control, a REST API to control a running
  simulation, and optional metrics export to InfluxDB/Grafana.

## Getting started

```bash
make build                 # produces ./network-simulator (also: make time, make profile)
mkdir -p simlogs
./network-simulator -config=./conf/simulation.yaml -log=./simlogs/app.log
```

The default `conf/simulation.yaml` selects the multi-tier BookInfo setup. To simulate the paper baseline, use the batch runner:

```bash
python3 experiments/batch_runner.py --experiment conf/experiments/EXPERIMENT_0.yaml --dry-run   # preview
python3 experiments/batch_runner.py --experiment conf/experiments/EXPERIMENT_0.yaml             # 20 runs
```

## Configuration

`conf/simulation.yaml` selects one file per subdirectory of `conf/`. The paper baseline:

```yaml
# conf/simulation.yaml
infra:         04_nodes.yaml                     # nodes, CPU templates, latencies
requests:      req_iat_burn_cpu_stairs_inc.yaml  # traffic
services:      burn-cpu.yaml                     # deployments and request profiles
hpa:           burn-cpu.yaml                     # autoscaler per service
pod_scheduler: local.yaml                        # placement policy
exporter:      influxdb.yaml                     # optional metrics export
seed: 42
sim_perf_period: 30                              # s between simulator-performance samples
simulation_server: {enabled: false, port: 9090}
sampling_periods: {metrics_server: 15, kubelet: 9, counter: 5}   # s; counter = KPI window in the log

# conf/services/burn-cpu.yaml
services:
  - name: burn-cpu
    lb_policy: least_requests
    min_replicas: 3                  # also the initial number of pods
    max_replicas: 40
    pod_ready_delay: 25              # s until a new pod receives traffic
    pod_deletion_grace_period: 30    # s
    cpu_num_workers: 1
    cpu_num_threads: 1
    cpu_request: 500                 # mCPU
    cpu_limit: 500                   # mCPU, enforced through quota throttling
    request_timeout: 10              # s
    request_profiles:
      - {name: profile-regular, request_duration: 52}   # ms of CPU time with a full core

# conf/hpa/burn-cpu.yaml
hpa:
  - service_name: burn-cpu
    mode: original                   # or: remote
    threshold: 0.50                  # target CPU utilization, relative to cpu_request
    synch_period: 15
    grace_period_scale_out: 15
    grace_period_scale_in: 300

# conf/requests/req_iat_burn_cpu_stairs_inc.yaml
iat:
  end_time: 500                      # simulated seconds
  profiles:
    - name: profile-regular
      service_name: burn-cpu
      iat_distribution: exponential
      iat_jitter_ms: 10
      rates:         [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]   # requests/s per phase
      change_points: [50, 100, 150, 200, 250, 300, 350, 400, 450] # s
```

The CPU scheduler parameters (CFS period, time slice) are set in `NewCFSScheduler` (`entities/cpuscheduler.go`).

## Outputs

Each simulation writes a JSON-lines event log (`simlogs/app.log`, or `app.log` in a batch run folder);
`profiler/utils.py` (`load_counter_df`, `load_hpa_df`) loads it into pandas DataFrames.

| `msg` | Content |
|---|---|
| `*events.CounterEvent` | per-service KPIs per sampling window: `p50`/`p90`/`p95`/`mean` RCT, `nrReq`, `nrReqTimeout`, `podsRunning`, `avgCPUUtilization` |
| `*events.HPAEvent` | per-pod CPU measurements and the utilization the HPA acted on |
| `*events.PodCreationEvent`, `*events.PodReadyEvent` | pod lifecycle |
| `*events.SimPerfEvent` | simulator speedup over real time |

## Batch experiments

`experiments/batch_runner.py` runs the simulations of an experiment definition; each run gets a folder in
`experiments/runs/` with a snapshot of its configuration (`conf/`), `app.log`, `stdout.log`, `stderr.log` and
`metadata.json`, plus a `<NAME>_summary.csv/.json` next to the runs.

```yaml
# conf/experiments/EXPERIMENT_4.yaml
name: EXPERIMENT_4
base_config: conf/simulation.yaml
binary: ./network-simulator
output_root: experiments/runs
concurrency: 5
repeats: 20
fixed:   {infra: 04_nodes.yaml, requests: req_iat_burn_cpu_stairs_inc.yaml, services: burn-cpu.yaml, hpa: burn-cpu.yaml}
matrix:  {hpa_threshold: [0.10]}          # Cartesian product of all listed values
seeds:   {mode: increment, start: 42}     # increment | fixed | none
```

- `fixed`: `infra`, `requests`, `services`, `hpa`, `exporter`, `seed`.
- `matrix`: `hpa_threshold`, `min_replicas`, `max_replicas`, `cpu_request`, `cpu_limit`, `cpu_num_workers`,
  `request_duration`, and the selectors of `fixed`. A `_by_service` suffix sets a value for one service only
  (e.g. `min_replicas_by_service: {ratings: 2}`).

## Extending CLOKS

Strategies can be added in Go (`entities/`, `podscheduler/`), or delegated to an external HTTP service that
receives the current state at each decision point and returns the decision:

- **Remote HPA:** `mode: remote` and an `endpoint` in the HPA file; reference server `test/remote_hpa/scaling_server.py`.
- **Remote pod scheduler:** `pod_scheduler: remote.yaml`; reference server in `test/remote_pod_scheduler/`.

With `simulation_server.enabled: true`, a running simulation exposes on the configured port: `GET /status`
(running/paused), `GET /time` (simulation time), `POST /pause`, `POST /resume`, `POST /schedule-pause` (e.g.
`{"time": 150.5}`), and `POST /update-iat` (validates a new arrival process; not yet applied to the running
simulation).

## Repository layout

```
main.go              entry point (flags: -config, -log)
core/                simulator engine, configuration loading, event handlers
entities/            pods, workers, threads, CPU/CFS scheduler, LB, HPA, Metrics Server, Kubelet
podscheduler/        scheduling framework, plugins, remote scheduler
events/ simrand/     event types, seeded RNG
metrics/ logger/     exporters and structured logging
server/              simulation control REST API
conf/                infra, services, hpa, requests, pod_scheduler, exporter, experiments
experiments/         reproduction script, batch runner, analysis and plotting scripts
profiler/            log loaders and plotting helpers
test/                reference servers for remote HPA and pod scheduling
docs/                CFS scheduler and CPU bandwidth control notes
```

## Limitations and known issues

- CLOKS does not model resource contention or monitoring overheads (including sidecar proxies), assumes one
  deployment per service, and pins workers to CPUs without inter-CPU rebalancing; measured tail latencies
  (p90/p95) therefore spread more than simulated ones.

## Citation

If you use CLOKS, please cite the paper (accepted at IEEE CCNC 2027, not yet published):

```bibtex
@inproceedings{ursu2027cloks,
  title     = {{CLOKS}: A Control-Loop-Oriented Kubernetes Simulator for High-Fidelity Modeling of Microservice Architectures},
  author    = {Ursu, Răzvan-Mihai and Asadi, Navidreza and Kellerer, Wolfgang},
  booktitle = {2027 IEEE 24th Consumer Communications \& Networking Conference (CCNC)},
  year      = {2027},
  note      = {Accepted, to appear}
}
```

Contact: Răzvan-Mihai Ursu ([razvan.ursu@tum.de](mailto:razvan.ursu@tum.de)), Chair of Communication Networks,
Technical University of Munich.
