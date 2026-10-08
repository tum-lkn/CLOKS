#!/usr/bin/env bash
#
# Reproduce the CLOKS paper results: run the simulations and create the figures.
#
# Usage (from anywhere):
#   experiments/reproduce_paper.sh [options]
#
# Options:
#   --single-tier    run only the single-tier experiments (Table II, Fig. 3, 4, 6a)
#   --scalability    run only the scalability experiments (Fig. 6b)
#   --plots-only     do not run simulations, only create the figures from existing runs
#   --clean          delete earlier runs of these experiments before starting
#   --no-latex       create the figures without LaTeX
#   -h, --help       show this help
#
# Environment variables:
#   PYTHON           Python interpreter to use (default: python3)
#
# See the "Reproducing the paper results" section of README.md for details.

set -uo pipefail

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
RUNS_DIR="experiments/runs"
FIGURES_DIR="experiments/figures"
MEASUREMENTS_DIR="experiments/measurements"

# Paper experiments 1-8, in the order of Table II
SINGLE_TIER=(EXPERIMENT_0 EXPERIMENT_1 EXPERIMENT_12 EXPERIMENT_13 EXPERIMENT_4 EXPERIMENT_20 EXPERIMENT_19 EXPERIMENT_8)
# 1, 100, 500, 1000, ..., 4000 requests per second
SCALABILITY=(SCALABILITY_0 SCALABILITY_1 SCALABILITY_2 SCALABILITY_3 SCALABILITY_4
             SCALABILITY_5 SCALABILITY_6 SCALABILITY_7 SCALABILITY_8 SCALABILITY_9)

RUN_SINGLE_TIER=true
RUN_SCALABILITY=true
RUN_SIMULATIONS=true
CLEAN=false
LATEX_FLAG=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "[$(date +%H:%M:%S)] $*"; }
warn() { echo "[$(date +%H:%M:%S)] WARNING: $*" >&2; }
fail() { echo "[$(date +%H:%M:%S)] ERROR: $*" >&2; exit 1; }

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# Run one simulation batch and compute its speedup over real time.
#   $1 = experiment name, $2 = CSV file for the speedup results
run_experiment() {
    local name="$1" csv="$2"

    if $CLEAN; then
        rm -rf "$RUNS_DIR"/*_"${name}"_* "$RUNS_DIR/${name}_summary.csv" "$RUNS_DIR/${name}_summary.json"
    elif compgen -G "$RUNS_DIR/*_${name}_*" > /dev/null; then
        warn "$name already has runs in $RUNS_DIR; the new runs will be mixed with them (use --clean to avoid this)"
    fi

    log "Running $name"
    "$PYTHON" experiments/batch_runner.py --experiment "conf/experiments/${name}.yaml" \
        || fail "simulations of $name failed"
    # batch_runner.py exits successfully even if single runs fail, so check its summary.
    # A few failed runs only reduce the sample; stop if none succeeded.
    local summary="$RUNS_DIR/${name}_summary.csv" n_ok n_failed
    n_ok="$(grep -c ",success," "$summary" 2> /dev/null)"
    n_failed="$(grep -c ",failed," "$summary" 2> /dev/null)"
    if [[ "${n_ok:-0}" -eq 0 ]]; then
        fail "all simulations of $name failed; see stderr.log in $RUNS_DIR/*_${name}_*"
    elif [[ "${n_failed:-0}" -gt 0 ]]; then
        warn "$n_failed of $((n_ok + n_failed)) simulations of $name failed (see stderr.log); results use the other $n_ok"
    fi
    "$PYTHON" experiments/analyze_sim_performance.py "$name" --csv "$csv" > /dev/null \
        || fail "speedup analysis of $name failed"
}

# ---------------------------------------------------------------------------
# Read options
# ---------------------------------------------------------------------------

for arg in "$@"; do
    case "$arg" in
        --single-tier) RUN_SCALABILITY=false ;;
        --scalability) RUN_SINGLE_TIER=false ;;
        --plots-only)  RUN_SIMULATIONS=false ;;
        --clean)       CLEAN=true ;;
        --no-latex)    LATEX_FLAG="--no-latex" ;;
        -h|--help)     usage ;;
        *)             fail "unknown option: $arg (see --help)" ;;
    esac
done

cd "$REPO_ROOT" || fail "cannot enter $REPO_ROOT"

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

"$PYTHON" -c "import pandas, numpy, scipy, matplotlib, yaml" 2> /dev/null \
    || fail "$PYTHON is missing packages; install: pandas numpy scipy matplotlib pyyaml"

# Without a working LaTeX setup the figures cannot be created with LaTeX text.
if [[ -z "$LATEX_FLAG" ]] && ! kpsewhich pdftex.map > /dev/null 2>&1; then
    warn "LaTeX is not fully installed; creating the figures without LaTeX"
    LATEX_FLAG="--no-latex"
fi

# The base configuration may export metrics to a database. If that database is
# not reachable, every simulation stops at start-up.
exporter="$(awk '/^exporter:/ {print $2}' conf/simulation.yaml)"
if [[ -n "$exporter" ]] && grep -q "^enabled: true" "conf/exporter/$exporter" 2> /dev/null; then
    warn "the metrics exporter conf/exporter/$exporter is enabled; make sure its database is running,"
    warn "or set 'enabled: false' in that file to only write log files"
fi

# An enabled InfluxDB exporter reads its token file at start-up.
token_file="$(awk '/^token_file:/ {print $2}' "conf/exporter/$exporter" 2> /dev/null)"
if grep -q "^enabled: true" "conf/exporter/$exporter" 2> /dev/null \
    && [[ -n "$token_file" && ! -f "conf/exporter/$token_file" ]]; then
    fail "conf/exporter/$token_file is missing; create it with: touch conf/exporter/$token_file"
fi

if ! grep -q "min_replicas: 3" conf/services/burn-cpu.yaml; then
    warn "conf/services/burn-cpu.yaml does not use min_replicas: 3 (the value used in the paper)"
fi

mkdir -p "$RUNS_DIR" "$FIGURES_DIR"

# ---------------------------------------------------------------------------
# 1. Build the simulator
# ---------------------------------------------------------------------------

if $RUN_SIMULATIONS; then
    log "Building the simulator"
    make build > /dev/null || fail "build failed"
fi

# ---------------------------------------------------------------------------
# 2. Single-tier experiments (Table II, Fig. 3, Fig. 4, Fig. 6a)
# ---------------------------------------------------------------------------

if $RUN_SINGLE_TIER; then
    if $RUN_SIMULATIONS; then
        $CLEAN && rm -f experiments/sim_performance.csv
        for name in "${SINGLE_TIER[@]}"; do
            run_experiment "$name" experiments/sim_performance.csv
        done
    fi

    if [[ -d "$MEASUREMENTS_DIR/EXPERIMENT_0" ]]; then
        log "Creating Fig. 3 (simulation vs. measurements over time)"
        "$PYTHON" experiments/plot_1.py --experiment EXPERIMENT_0 $LATEX_FLAG \
            --output-dir "$FIGURES_DIR" --output fig3_baseline_timeseries.pdf > /dev/null \
            || fail "Fig. 3 failed"

        log "Creating Fig. 4 (response time percentiles)"
        "$PYTHON" experiments/plot_2.py --experiment EXPERIMENT_0 $LATEX_FLAG \
            --output-dir "$FIGURES_DIR" --output fig4_rct_percentiles.pdf > /dev/null \
            || fail "Fig. 4 failed"
    else
        warn "no measurements in $MEASUREMENTS_DIR/EXPERIMENT_0; skipping Fig. 3 and Fig. 4"
    fi

    log "Creating Fig. 6a (speedup per experiment)"
    "$PYTHON" experiments/plot_3.py $LATEX_FLAG \
        --output "$FIGURES_DIR/fig6a_speedup_per_experiment.pdf" > /dev/null \
        || fail "Fig. 6a failed"

    # Table II: compare each experiment with its measurements, then fill the LaTeX table.
    # The metrics are collected in experiments/final_metrics.csv (one row per experiment).
    log "Creating Table II (accuracy of the single-tier experiments)"
    rm -f experiments/final_metrics.csv
    mkdir -p "$FIGURES_DIR/comparison"
    for name in "${SINGLE_TIER[@]}"; do
        if [[ -d "$MEASUREMENTS_DIR/$name" ]]; then
            MPLBACKEND=Agg "$PYTHON" experiments/compare_sim_vs_measured.py "$name" \
                --output "$REPO_ROOT/$FIGURES_DIR/comparison/${name}.png" > /dev/null \
                || fail "comparison of $name with its measurements failed"
        else
            warn "no measurements in $MEASUREMENTS_DIR/$name; its row in Table II stays empty"
        fi
    done
    if [[ -f experiments/final_metrics.csv ]]; then
        "$PYTHON" experiments/fill_latex_table.py \
            --csv "$REPO_ROOT/experiments/final_metrics.csv" \
            --template "$REPO_ROOT/experiments/single-error.tex" \
            --output "$REPO_ROOT/$FIGURES_DIR/table2_single_tier_accuracy.tex" > /dev/null \
            || fail "Table II failed"
    fi
fi

# ---------------------------------------------------------------------------
# 3. Scalability experiments (Fig. 6b)
# ---------------------------------------------------------------------------

if $RUN_SCALABILITY; then
    if $RUN_SIMULATIONS; then
        $CLEAN && rm -f experiments/scalability_performance.csv
        for name in "${SCALABILITY[@]}"; do
            run_experiment "$name" experiments/scalability_performance.csv
        done
    fi

    log "Creating Fig. 6b (speedup vs. requests per second)"
    "$PYTHON" experiments/plot_4.py $LATEX_FLAG --csv experiments/scalability_performance.csv \
        --output "$FIGURES_DIR/fig6b_speedup_vs_rps.pdf" > /dev/null \
        || fail "Fig. 6b failed"
fi

log "Done. Figures are in $FIGURES_DIR/"
