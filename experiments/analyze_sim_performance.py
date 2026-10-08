#!/usr/bin/env python3

import argparse
import fnmatch
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def find_batch_runs(runs_dir: Path, batch_pattern: str) -> list[Path]:
    """Find all run directories matching the batch pattern."""
    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")
    
    matching_runs = sorted([
        d for d in runs_dir.iterdir()
        if d.is_dir() and fnmatch.fnmatch(d.name, batch_pattern)
    ])
    
    if not matching_runs:
        raise ValueError(f"No runs found with pattern: {batch_pattern}")
    
    return matching_runs


def load_simperf_events(log_path: Path) -> pd.DataFrame:
    """
    Load SimPerfEvent entries from simulation log.
    
    Returns:
        DataFrame with columns: simTime, speedUpFactor
    """
    perf_data = []
    
    with open(log_path, 'r') as f:
        for line in f:
            try:
                log_entry = json.loads(line.strip())
                if log_entry.get('msg') == '*events.SimPerfEvent':
                    perf_data.append({
                        'simTime': float(log_entry['simTime']),
                        'speedUpFactor': log_entry['speedUpFactor'],
                    })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    
    if not perf_data:
        return pd.DataFrame(columns=['simTime', 'speedUpFactor'])
    
    return pd.DataFrame(perf_data).sort_values('simTime').reset_index(drop=True)


def normalize_time(df: pd.DataFrame, time_col: str = "simTime") -> pd.DataFrame:
    """Normalize time to start at 0."""
    df = df.copy()
    if len(df) > 0 and time_col in df.columns:
        t_start = df[time_col].min()
        df[time_col] = df[time_col] - t_start
    return df


def compute_performance_metrics(perf_dfs: list[pd.DataFrame], t_min: float = 15.0) -> dict:
    """
    Compute performance metrics across multiple simulation runs.
    
    For each run:
    1. Calculate harmonic mean of speedup factors (after t_min)
    2. Collect per-run harmonic means
    3. Calculate mean and std dev across runs
    
    Args:
        perf_dfs: List of DataFrames with simTime and speedUpFactor
        t_min: Minimum time to start analysis (default: 15s to skip warm-up)
    
    Returns:
        Dictionary with avg_speedup (mean of per-run harmonic means) and std_dev
    """
    # Calculate harmonic mean per run
    per_run_hmeans = []
    
    for df in perf_dfs:
        if len(df) > 0:
            # Filter to only include data after t_min
            mask = df['simTime'] >= t_min
            speedups = df[mask]['speedUpFactor'].values
            
            if len(speedups) > 0:
                # Compute harmonic mean for this run
                run_hmean = stats.hmean(speedups)
                per_run_hmeans.append(run_hmean)
    
    if not per_run_hmeans:
        return {
            'avg_speedup': np.nan,
            'std_dev': np.nan,
            'n_runs': 0,
        }
    
    # Compute mean and standard deviation across per-run harmonic means
    avg_speedup = np.mean(per_run_hmeans)
    std_dev = np.std(per_run_hmeans, ddof=1) if len(per_run_hmeans) > 1 else 0.0
    
    return {
        'avg_speedup': avg_speedup,
        'std_dev': std_dev,
        'n_runs': len(per_run_hmeans),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Analyze simulation performance (speedup factors) across multiple runs"
    )
    parser.add_argument(
        "experiment",
        help="Experiment name (e.g., 'EXPERIMENT_0')",
    )
    parser.add_argument(
        "--runs-dir",
        default="experiments/runs",
        help="Path to runs directory (default: experiments/runs)",
    )
    parser.add_argument(
        "--t-min",
        type=float,
        default=15.0,
        help="Minimum simulation time to start analysis (default: 15s)",
    )
    parser.add_argument(
        "--csv",
        default="experiments/sim_performance.csv",
        help="Path to output CSV file (default: experiments/sim_performance.csv)",
    )
    
    args = parser.parse_args()
    
    repo_root = Path(__file__).resolve().parent.parent
    runs_dir = (repo_root / args.runs_dir).resolve()
    
    # Create batch pattern from experiment name
    batch_pattern = f"*_{args.experiment}_*"
    
    print(f"Experiment: {args.experiment}")
    print(f"Finding simulation runs with pattern: {batch_pattern}")
    run_dirs = find_batch_runs(runs_dir, batch_pattern)
    print(f"Found {len(run_dirs)} simulation runs")
    
    # Load SimPerfEvent data from all runs
    perf_dfs = []
    
    for run_dir in run_dirs:
        log_path = run_dir / "app.log"
        if not log_path.exists():
            print(f"Warning: Log file not found in {run_dir.name}, skipping")
            continue
        
        print(f"Processing simulation: {run_dir.name}")
        
        try:
            perf_df = load_simperf_events(log_path)
            if len(perf_df) > 0:
                perf_df = normalize_time(perf_df, "simTime")
                perf_dfs.append(perf_df)
                print(f"  Loaded {len(perf_df)} SimPerfEvent entries")
        except Exception as e:
            print(f"Warning: Failed to load perf data from {run_dir.name}: {e}")
    
    if not perf_dfs:
        raise ValueError("No valid simulation performance data found")
    
    print(f"\nComputing performance metrics (t >= {args.t_min}s)...")
    metrics = compute_performance_metrics(perf_dfs, t_min=args.t_min)
    
    # Print results
    print("\n=== Performance Metrics ===")
    print(f"Average Speedup Factor: {metrics['avg_speedup']:.2f}x")
    print(f"Standard Deviation: {metrics['std_dev']:.2f}")
    print(f"Number of Runs: {metrics['n_runs']}")
    
    # Save to CSV file
    performance_csv_path = Path(args.csv)
    if not performance_csv_path.is_absolute():
        performance_csv_path = repo_root / performance_csv_path
    
    # Create parent directory if it doesn't exist
    performance_csv_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Read existing metrics
    existing_metrics = {}
    if performance_csv_path.exists():
        with open(performance_csv_path, 'r') as f:
            header = f.readline()  # Skip header
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split('\t')
                    if len(parts) == 3:
                        exp_name = parts[0]
                        existing_metrics[exp_name] = parts[1:]
    
    # Format experiment name with leading zero if needed
    exp_parts = args.experiment.split('_')
    if len(exp_parts) >= 2 and exp_parts[-1].isdigit() and len(exp_parts[-1]) == 1:
        formatted_exp_name = '_'.join(exp_parts[:-1]) + '_' + exp_parts[-1].zfill(2)
    else:
        formatted_exp_name = args.experiment
    
    # Update with current experiment
    existing_metrics[formatted_exp_name] = [
        f"{metrics['avg_speedup']:.4f}" if not np.isnan(metrics['avg_speedup']) else "NaN",
        f"{metrics['std_dev']:.4f}" if not np.isnan(metrics['std_dev']) else "NaN",
    ]
    
    # Sort by experiment name (natural sort for numbers)
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
    
    sorted_experiments = sorted(existing_metrics.keys(), key=natural_sort_key)
    
    # Write to CSV
    with open(performance_csv_path, 'w') as f:
        f.write("Experiment\tavg_speedup_factor\tstd_speedup_factor\n")
        for exp_name in sorted_experiments:
            values = existing_metrics[exp_name]
            values_str = '\t'.join(values)
            f.write(f"{exp_name}\t{values_str}\n")
    
    print(f"\nPerformance metrics written to: {performance_csv_path}")
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
