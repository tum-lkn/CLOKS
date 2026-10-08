#!/usr/bin/env python3

import argparse
import fnmatch
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Import functions from profiler/utils.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "profiler"))
from utils import load_counter_df, load_hpa_df


def find_batch_runs(runs_dir: Path, batch_prefix: str) -> list[Path]:
    """Find all run directories matching the batch prefix (supports glob patterns)."""
    if not runs_dir.exists():
        raise FileNotFoundError(f"Runs directory not found: {runs_dir}")
    
    matching_runs = sorted([
        d for d in runs_dir.iterdir()
        if d.is_dir() and fnmatch.fnmatch(d.name, batch_prefix)
    ])
    
    if not matching_runs:
        raise ValueError(f"No runs found with pattern: {batch_prefix}")
    
    return matching_runs


def normalize_time(df: pd.DataFrame, time_col: str = "simTime") -> pd.DataFrame:
    """Normalize time to start at 0."""
    df = df.copy()
    if len(df) > 0 and time_col in df.columns:
        t_start = df[time_col].min()
        df[time_col] = df[time_col] - t_start
    return df


def compute_confidence_interval(data_list: list[pd.DataFrame], time_col: str, value_col: str, ci: float = 0.95):
    """
    Compute mean and confidence interval across multiple runs.
    
    Args:
        data_list: List of DataFrames, each with time_col and value_col
        time_col: Name of time column
        value_col: Name of value column
        ci: Confidence level (default 0.95 for 95% CI)
    
    Returns:
        DataFrame with columns: time, mean, lower, upper
    """
    if not data_list:
        return pd.DataFrame(columns=["time", "mean", "lower", "upper"])
    
    # Find common time range across all runs
    t_min = max(df[time_col].min() for df in data_list if len(df) > 0)
    t_max = min(df[time_col].max() for df in data_list if len(df) > 0)
    
    # Create a common time grid (use 200 points for smooth curves)
    time_grid = np.linspace(t_min, t_max, 200)
    
    # Interpolate each run onto the common time grid
    interpolated_values = []
    for df in data_list:
        if len(df) > 0:
            values_interp = np.interp(time_grid, df[time_col].values, df[value_col].values)
            interpolated_values.append(values_interp)
    
    if not interpolated_values:
        return pd.DataFrame(columns=["time", "mean", "lower", "upper"])
    
    # Stack into array (rows = time points, columns = runs)
    values_array = np.stack(interpolated_values, axis=1)
    
    # Compute mean and confidence interval
    mean = np.mean(values_array, axis=1)
    std = np.std(values_array, axis=1, ddof=1)
    n = values_array.shape[1]
    
    # Use t-distribution for small sample sizes, otherwise normal distribution
    if n > 30:
        # Normal distribution (z-score)
        z = 1.96 if ci == 0.95 else 2.576  # 95% or 99% CI
        margin = z * std / np.sqrt(n)
    else:
        # t-distribution
        from scipy import stats
        t_val = stats.t.ppf((1 + ci) / 2, n - 1)
        margin = t_val * std / np.sqrt(n)
    
    return pd.DataFrame({
        "time": time_grid,
        "mean": mean,
        "lower": mean - margin,
        "upper": mean + margin,
    })


def plot_batch_results(
    counter_stats: pd.DataFrame,
    hpa_stats: pd.DataFrame,
    batch_prefix: str,
    output_path: Path = None,
):
    """
    Create 2x2 plot with RPS, Pods, P50, and HPA CPU metrics with confidence intervals.
    
    Args:
        counter_stats: Dict with keys 'rps', 'pods', 'p50', each a DataFrame with time, mean, lower, upper
        hpa_stats: DataFrame with time, mean, lower, upper for HPA CPU metric
        batch_prefix: Batch name for plot title
        output_path: Optional path to save the plot
    """
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Batch Analysis: {batch_prefix}", fontsize=16, fontweight="bold")
    
    # Top-left: RPS vs time
    ax = axes[0, 0]
    if "rps" in counter_stats and len(counter_stats["rps"]) > 0:
        df = counter_stats["rps"]
        ax.plot(df["time"], df["mean"], color="#1f77b4", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#1f77b4", alpha=0.2, label="95% CI")
    ax.set_xlabel("Simulation Time (s)", fontsize=11)
    ax.set_ylabel("Requests per Second (RPS)", fontsize=11)
    ax.set_title("Request Rate", fontsize=12, fontweight="bold")
    # ax.set_ylim(0, 115)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Top-right: Pods vs time
    ax = axes[0, 1]
    if "pods" in counter_stats and len(counter_stats["pods"]) > 0:
        df = counter_stats["pods"]
        ax.plot(df["time"], df["mean"], color="#ff7f0e", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#ff7f0e", alpha=0.2, label="95% CI")
    ax.set_xlabel("Simulation Time (s)", fontsize=11)
    ax.set_ylabel("Number of Pods", fontsize=11)
    ax.set_title("Pod Count", fontsize=12, fontweight="bold")
    # ax.set_ylim(0, 40)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Bottom-left: P50 vs time
    ax = axes[1, 0]
    if "p50" in counter_stats and len(counter_stats["p50"]) > 0:
        df = counter_stats["p50"]
        ax.plot(df["time"], df["mean"], color="#2ca02c", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#2ca02c", alpha=0.2, label="95% CI")
    ax.set_xlabel("Simulation Time (s)", fontsize=11)
    ax.set_ylabel("P50 Response Time (s)", fontsize=11)
    ax.set_title("Median Request Completion Time", fontsize=12, fontweight="bold")
    # ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Bottom-right: HPA CPU metric vs time
    ax = axes[1, 1]
    if len(hpa_stats) > 0:
        ax.plot(hpa_stats["time"], hpa_stats["mean"], color="#d62728", linewidth=2, label="Mean")
        ax.fill_between(hpa_stats["time"], hpa_stats["lower"], hpa_stats["upper"], color="#d62728", alpha=0.2, label="95% CI")
    ax.set_xlabel("Simulation Time (s)", fontsize=11)
    ax.set_ylabel("CPU Utilization", fontsize=11)
    ax.set_title("HPA CPU Metric", fontsize=12, fontweight="bold")
    # ax.set_ylim(0, 1.2)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Process and visualize batch experiment results with confidence intervals"
    )
    parser.add_argument(
        "--batch-prefix",
        required=True,
        help="Batch prefix/pattern to match run directories (supports glob patterns, e.g., '*_EXPERIMENT_0' or '20260416T152524Z_EXPERIMENT_0')",
    )
    parser.add_argument(
        "--runs-dir",
        default="experiments/runs",
        help="Path to runs directory (default: experiments/runs)",
    )
    parser.add_argument(
        "--deployment",
        default="burn-cpu",
        help="Deployment name for HPA metrics (default: burn-cpu)",
    )
    parser.add_argument(
        "--output",
        help="Output path for plot (optional, if not provided will show plot)",
    )
    parser.add_argument(
        "--ci",
        type=float,
        default=0.95,
        help="Confidence interval level (default: 0.95 for 95%% CI)",
    )
    
    args = parser.parse_args()
    
    repo_root = Path(__file__).resolve().parent.parent
    runs_dir = (repo_root / args.runs_dir).resolve()
    
    print(f"Finding runs with pattern: {args.batch_prefix}")
    run_dirs = find_batch_runs(runs_dir, args.batch_prefix)
    print(f"Found {len(run_dirs)} runs")
    
    # Load data from all runs
    counter_dfs = []
    hpa_dfs = []
    
    for run_dir in run_dirs:
        log_path = run_dir / "app.log"
        if not log_path.exists():
            print(f"Warning: Log file not found in {run_dir.name}, skipping")
            continue
        
        print(f"Processing: {run_dir.name}")
        
        # Load counter data (RPS, pods, P50)
        try:
            counter_df = load_counter_df(log_path)
            counter_df = normalize_time(counter_df, "simTime")
            counter_dfs.append(counter_df)
        except Exception as e:
            print(f"Warning: Failed to load counter data from {run_dir.name}: {e}")
        
        # Load HPA data
        try:
            hpa_df = load_hpa_df(log_path, args.deployment)
            hpa_df = normalize_time(hpa_df, "simTime")
            hpa_dfs.append(hpa_df)
        except Exception as e:
            print(f"Warning: Failed to load HPA data from {run_dir.name}: {e}")
    
    if not counter_dfs:
        raise ValueError("No valid counter data found in any run")
    
    print(f"\nComputing statistics across {len(counter_dfs)} runs...")
    
    # Compute confidence intervals for each metric
    counter_stats = {
        "rps": compute_confidence_interval(counter_dfs, "simTime", "rps", args.ci),
        "pods": compute_confidence_interval(counter_dfs, "simTime", "podsRunning", args.ci),
        "p50": compute_confidence_interval(counter_dfs, "simTime", "p50", args.ci),
    }
    
    hpa_stats = pd.DataFrame(columns=["time", "mean", "lower", "upper"])
    if hpa_dfs:
        hpa_stats = compute_confidence_interval(hpa_dfs, "simTime", "cpu_avg", args.ci)
    
    # Generate plots
    output_path = Path(args.output).resolve() if args.output else None
    plot_batch_results(counter_stats, hpa_stats, args.batch_prefix, output_path)
    
    print("\nBatch processing complete!")


if __name__ == "__main__":
    main()
