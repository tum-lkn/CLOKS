#!/usr/bin/env python3

import argparse
import fnmatch
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# Import functions from profiler/utils.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "profiler"))
from utils import load_counter_df, load_hpa_df

# Threshold for filtering out erroneous P50 values (20ms)
# Values below this threshold indicate data collection errors
P50_THRESHOLD = 0.02  # seconds


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
    
    # Filter out DataFrames that don't have the required columns or are empty
    valid_dfs = [
        df for df in data_list 
        if len(df) > 0 and time_col in df.columns and value_col in df.columns
    ]
    
    if not valid_dfs:
        return pd.DataFrame(columns=["time", "mean", "lower", "upper"])
    
    # Find common time range across all runs
    t_min = max(df[time_col].min() for df in valid_dfs)
    t_max = min(df[time_col].max() for df in valid_dfs)
    
    # Create a common time grid (use 200 points for smooth curves)
    time_grid = np.linspace(t_min, t_max, 200)
    
    # Interpolate each run onto the common time grid
    interpolated_values = []
    for df in valid_dfs:
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


def find_measurement_files(measurements_dir: Path, experiment_name: str) -> list[Path]:
    """Find all measurement CSV files for the given experiment."""
    if not measurements_dir.exists():
        raise FileNotFoundError(f"Measurements directory not found: {measurements_dir}")
    
    # Look for experiment subdirectory
    experiment_dir = measurements_dir / experiment_name
    if not experiment_dir.exists():
        raise FileNotFoundError(f"Experiment measurements directory not found: {experiment_dir}")
    
    # Find all CSV files in the experiment directory
    matching_files = sorted([
        f for f in experiment_dir.iterdir()
        if f.is_file() and f.suffix.lower() == '.csv'
    ])
    
    if not matching_files:
        raise ValueError(f"No CSV measurement files found in: {experiment_dir}")
    
    return matching_files


def load_measurement_data(measurement_file: Path, deployment: str) -> pd.DataFrame:
    """Load a single measurement CSV file."""
    df = pd.read_csv(measurement_file)
    
    # Convert timestamp to elapsed time
    time = pd.to_datetime(df["timestamp"])
    df["x"] = (time - time.iloc[0]).dt.total_seconds()
    
    # Extract and rename columns
    df = df.rename(columns={
        f"rct_p50_unknown_TO_{deployment}": "rct_p50",
        f"rct_p90_unknown_TO_{deployment}": "rct_p90",
        f"rct_p95_unknown_TO_{deployment}": "rct_p95",
        f"nr_pods_{deployment}": "pods",
        f"rps_unknown_TO_{deployment}": "rps",
    }).sort_values("x")
    
    # Convert RCT from milliseconds to seconds
    df["rct_p50"] = df["rct_p50"] / 1000.0
    df["rct_p90"] = df["rct_p90"] / 1000.0
    df["rct_p95"] = df["rct_p95"] / 1000.0
    
    # Add HPA metric (convert from 0-100 to 0-1 scale)
    hpa_col = f"hpa_target_metric_{deployment}"
    if hpa_col in df.columns:
        df["hpa_cpu"] = df[hpa_col] / 100.0
    else:
        df["hpa_cpu"] = np.nan
    
    return df


def plot_comparison(
    sim_counter_stats: dict,
    sim_hpa_stats: pd.DataFrame,
    measured_stats: dict,
    experiment_name: str,
    output_path: Path = None,
    counter_dfs: list[pd.DataFrame] = None,
    hpa_dfs: list[pd.DataFrame] = None,
    measured_dfs: list[pd.DataFrame] = None,
    show_individual_runs: bool = False,
):
    """
    Create 2x3 plot comparing simulation (blue) vs measured (red) data.
    Row 1: P50, P90, P95
    Row 2: RPS, Pods, HPA CPU
    
    Args:
        sim_counter_stats: Dict with 'rps', 'pods', 'p50', 'p90', 'p95' simulation stats
        sim_hpa_stats: Simulation HPA stats DataFrame
        measured_stats: Dict with measurement stats (mean and CI) for each metric
        experiment_name: Experiment name for plot title
        output_path: Optional path to save the plot
        counter_dfs: Optional list of raw counter DataFrames for plotting individual runs
        hpa_dfs: Optional list of raw HPA DataFrames for plotting individual runs
        measured_dfs: Optional list of raw measurement DataFrames for plotting individual runs
        show_individual_runs: If True, plot all individual simulation and measurement runs
    """
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f"Simulation vs Measured: {experiment_name}", fontsize=16, fontweight="bold")
    
    # Color scheme: Blue for simulation, Red for measured
    sim_color = "#1f77b4"  # Blue
    measured_color = "#d62728"  # Red
    measured_individual_color = "#d62728"  # Same red for individual measurement runs
    sim_individual_color = "#1f77b4"  # Same blue for individual runs
    
    # Row 1, Col 1: P50 vs time
    ax = axes[0, 0]
    # Plot individual runs if requested
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p50"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if "p50" in sim_counter_stats and len(sim_counter_stats["p50"]) > 0 and "time" in sim_counter_stats["p50"].columns:
        df = sim_counter_stats["p50"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "rct_p50" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["rct_p50"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p50" in measured_stats and len(measured_stats["rct_p50"]) > 0 and "time" in measured_stats["rct_p50"].columns:
        df = measured_stats["rct_p50"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P50 Response Time (s)", fontsize=11)
    ax.set_title("RCT P50", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 1, Col 2: P90 vs time
    ax = axes[0, 1]
    # Plot individual runs if requested
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p90"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if "p90" in sim_counter_stats and len(sim_counter_stats["p90"]) > 0 and "time" in sim_counter_stats["p90"].columns:
        df = sim_counter_stats["p90"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "rct_p90" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["rct_p90"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p90" in measured_stats and len(measured_stats["rct_p90"]) > 0 and "time" in measured_stats["rct_p90"].columns:
        df = measured_stats["rct_p90"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P90 Response Time (s)", fontsize=11)
    ax.set_title("RCT P90", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 1, Col 3: P95 vs time
    ax = axes[0, 2]
    # Plot individual runs if requested
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p95"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if "p95" in sim_counter_stats and len(sim_counter_stats["p95"]) > 0 and "time" in sim_counter_stats["p95"].columns:
        df = sim_counter_stats["p95"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "rct_p95" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["rct_p95"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p95" in measured_stats and len(measured_stats["rct_p95"]) > 0 and "time" in measured_stats["rct_p95"].columns:
        df = measured_stats["rct_p95"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P95 Response Time (s)", fontsize=11)
    ax.set_title("RCT P95", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 1: RPS vs time
    ax = axes[1, 0]
    # Plot individual runs if requested
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["rps"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if "rps" in sim_counter_stats and len(sim_counter_stats["rps"]) > 0 and "time" in sim_counter_stats["rps"].columns:
        df = sim_counter_stats["rps"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "rps" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["rps"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rps" in measured_stats and len(measured_stats["rps"]) > 0 and "time" in measured_stats["rps"].columns:
        df = measured_stats["rps"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Requests per Second (RPS)", fontsize=11)
    ax.set_title("Request Rate", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 115)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 2: Pods vs time
    ax = axes[1, 1]
    # Plot individual runs if requested
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["podsRunning"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if "pods" in sim_counter_stats and len(sim_counter_stats["pods"]) > 0 and "time" in sim_counter_stats["pods"].columns:
        df = sim_counter_stats["pods"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "pods" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["pods"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "pods" in measured_stats and len(measured_stats["pods"]) > 0 and "time" in measured_stats["pods"].columns:
        df = measured_stats["pods"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Number of Pods", fontsize=11)
    ax.set_title("Pod Count", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 41)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 3: HPA CPU metric vs time
    ax = axes[1, 2]
    # Plot individual runs if requested
    if show_individual_runs and hpa_dfs:
        for i, df in enumerate(hpa_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["cpu_avg"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    # Plot mean and CI
    if len(sim_hpa_stats) > 0 and "time" in sim_hpa_stats.columns:
        ax.plot(sim_hpa_stats["time"], sim_hpa_stats["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(sim_hpa_stats["time"], sim_hpa_stats["lower"], sim_hpa_stats["upper"], color=sim_color, alpha=0.2)
    # Plot individual measurement runs if requested
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            if "hpa_cpu" in df.columns:
                label = "Individual measurements" if i == 0 else None
                ax.plot(df["x"], df["hpa_cpu"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "hpa_cpu" in measured_stats and len(measured_stats["hpa_cpu"]) > 0 and "time" in measured_stats["hpa_cpu"].columns:
        df = measured_stats["hpa_cpu"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("CPU Utilization", fontsize=11)
    ax.set_title("HPA CPU Metric", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1.2)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def compute_summary_statistics(
    sim_counter_stats: dict,
    sim_hpa_stats: pd.DataFrame,
    measured_stats: dict,
    counter_dfs: list[pd.DataFrame],
    hpa_dfs: list[pd.DataFrame],
    measured_dfs: list[pd.DataFrame],
) -> dict:
    """
    Compute summary statistics comparing simulation vs measured data.
    Only considers data after t=100s to skip warm-up period.
    
    Returns:
        Dictionary with computed metrics
    """
    metrics = {}
    
    # Common time range for interpolation (skip warm-up period: t >= 100s)
    if "pods" not in measured_stats or len(measured_stats["pods"]) == 0:
        return metrics
    
    t_min = max(
        sim_counter_stats["pods"]["time"].min() if len(sim_counter_stats["pods"]) > 0 else 0,
        measured_stats["pods"]["time"].min(),
        100.0  # Skip warm-up period
    )
    t_max = min(
        sim_counter_stats["pods"]["time"].max() if len(sim_counter_stats["pods"]) > 0 else float('inf'),
        measured_stats["pods"]["time"].max()
    )
    
    # 1. MAE of number of pods
    if "pods" in sim_counter_stats and len(sim_counter_stats["pods"]) > 0 and "pods" in measured_stats:
        sim_pods = sim_counter_stats["pods"]
        meas_pods = measured_stats["pods"]
        mask_sim = (sim_pods["time"] >= t_min) & (sim_pods["time"] <= t_max)
        mask_meas = (meas_pods["time"] >= t_min) & (meas_pods["time"] <= t_max)
        sim_time = sim_pods["time"][mask_sim].values
        sim_mean = sim_pods["mean"][mask_sim].values
        
        meas_pods_interp = np.interp(sim_time, meas_pods["time"][mask_meas].values, meas_pods["mean"][mask_meas].values)
        metrics["mae_pods"] = np.mean(np.abs(sim_mean - meas_pods_interp))
    
    # 2. MAE of HPA CPU metric
    if len(sim_hpa_stats) > 0 and "hpa_cpu" in measured_stats and len(measured_stats["hpa_cpu"]) > 0:
        meas_hpa = measured_stats["hpa_cpu"]
        mask_sim = (sim_hpa_stats["time"] >= t_min) & (sim_hpa_stats["time"] <= t_max)
        mask_meas = (meas_hpa["time"] >= t_min) & (meas_hpa["time"] <= t_max)
        sim_time = sim_hpa_stats["time"][mask_sim].values
        sim_mean = sim_hpa_stats["mean"][mask_sim].values
        
        meas_hpa_interp = np.interp(sim_time, meas_hpa["time"][mask_meas].values, meas_hpa["mean"][mask_meas].values)
        metrics["mae_hpa"] = np.mean(np.abs(sim_mean - meas_hpa_interp))
    
    # 3. Percentual difference in pod-seconds
    if "pods" in sim_counter_stats and len(sim_counter_stats["pods"]) > 0 and "pods" in measured_stats:
        sim_pods = sim_counter_stats["pods"]
        meas_pods = measured_stats["pods"]
        mask_sim = (sim_pods["time"] >= t_min) & (sim_pods["time"] <= t_max)
        mask_meas = (meas_pods["time"] >= t_min) & (meas_pods["time"] <= t_max)
        sim_time = sim_pods["time"][mask_sim].values
        sim_mean = sim_pods["mean"][mask_sim].values
        
        # Integrate using trapezoidal rule
        sim_pod_seconds = np.trapz(sim_mean, sim_time)
        
        meas_time = meas_pods["time"][mask_meas].values
        meas_mean = meas_pods["mean"][mask_meas].values
        meas_pod_seconds = np.trapz(meas_mean, meas_time)
        
        if meas_pod_seconds > 0:
            metrics["pod_seconds_diff_pct"] = 100 * (sim_pod_seconds - meas_pod_seconds) / meas_pod_seconds
        metrics["sim_pod_seconds"] = sim_pod_seconds
        metrics["meas_pod_seconds"] = meas_pod_seconds
    
    # 4. Collect all P50, P90, P95 values for boxplot (after t=100s warm-up)
    # Filter out P50 values below threshold as they indicate data collection errors
    metrics["sim_p50_all"] = []
    metrics["sim_p90_all"] = []
    metrics["sim_p95_all"] = []
    
    for df in counter_dfs:
        mask = (df["simTime"] >= t_min) & (df["simTime"] <= t_max) & (df["p50"] >= P50_THRESHOLD)
        metrics["sim_p50_all"].extend(df[mask]["p50"].values)
        metrics["sim_p90_all"].extend(df[mask]["p90"].values)
        metrics["sim_p95_all"].extend(df[mask]["p95"].values)
    
    metrics["meas_p50_all"] = []
    metrics["meas_p90_all"] = []
    metrics["meas_p95_all"] = []
    
    for df in measured_dfs:
        mask = (df["x"] >= t_min) & (df["x"] <= t_max) & (df["rct_p50"] >= P50_THRESHOLD)
        metrics["meas_p50_all"].extend(df[mask]["rct_p50"].values)
        metrics["meas_p90_all"].extend(df[mask]["rct_p90"].values)
        metrics["meas_p95_all"].extend(df[mask]["rct_p95"].values)
    
    # 5. MAE and MAPE of RCT P50 (after t=100s, excluding P50 below threshold)
    if "p50" in sim_counter_stats and len(sim_counter_stats["p50"]) > 0 and "rct_p50" in measured_stats:
        sim_p50 = sim_counter_stats["p50"]
        meas_p50 = measured_stats["rct_p50"]
        mask_sim = (sim_p50["time"] >= t_min) & (sim_p50["time"] <= t_max)
        mask_meas = (meas_p50["time"] >= t_min) & (meas_p50["time"] <= t_max)
        sim_time = sim_p50["time"][mask_sim].values
        sim_mean = sim_p50["mean"][mask_sim].values
        
        meas_p50_interp = np.interp(sim_time, meas_p50["time"][mask_meas].values, meas_p50["mean"][mask_meas].values)
        
        # Filter out points where either sim or measured below threshold (data collection errors)
        valid_mask = (meas_p50_interp >= P50_THRESHOLD) & (sim_mean >= P50_THRESHOLD)
        if np.any(valid_mask):
            # MAE (Mean Absolute Error)
            metrics["mae_p50"] = np.mean(np.abs(sim_mean[valid_mask] - meas_p50_interp[valid_mask]))
            # MAPE (Mean Absolute Percentage Error)
            mape = np.mean(np.abs((sim_mean[valid_mask] - meas_p50_interp[valid_mask]) / meas_p50_interp[valid_mask])) * 100
            metrics["mape_p50"] = mape
            metrics["mape_p50_n_points"] = np.sum(valid_mask)
    
    # 6. KS distance of distributions
    if len(metrics.get("sim_p50_all", [])) > 0 and len(metrics.get("meas_p50_all", [])) > 0:
        metrics["ks_p50"] = stats.ks_2samp(metrics["sim_p50_all"], metrics["meas_p50_all"]).statistic
        metrics["ks_p90"] = stats.ks_2samp(metrics["sim_p90_all"], metrics["meas_p90_all"]).statistic
        metrics["ks_p95"] = stats.ks_2samp(metrics["sim_p95_all"], metrics["meas_p95_all"]).statistic
    
    # 7. Average P50 difference (after t=100s, using same mask for both sim and measured)
    if "p50" in sim_counter_stats and len(sim_counter_stats["p50"]) > 0 and "rct_p50" in measured_stats and len(measured_stats["rct_p50"]) > 0:
        sim_p50 = sim_counter_stats["p50"]
        meas_p50 = measured_stats["rct_p50"]
        mask_sim = (sim_p50["time"] >= t_min) & (sim_p50["time"] <= t_max)
        mask_meas = (meas_p50["time"] >= t_min) & (meas_p50["time"] <= t_max)
        sim_time = sim_p50["time"][mask_sim].values
        sim_mean = sim_p50["mean"][mask_sim].values
        
        # Interpolate measured to simulation time points
        meas_p50_interp = np.interp(sim_time, meas_p50["time"][mask_meas].values, meas_p50["mean"][mask_meas].values)
        
        # Apply same threshold mask to both
        valid_mask = (meas_p50_interp >= P50_THRESHOLD) & (sim_mean >= P50_THRESHOLD)
        if np.any(valid_mask):
            sim_avg_p50 = sim_mean[valid_mask].mean()
            meas_avg_p50 = meas_p50_interp[valid_mask].mean()
            
            if meas_avg_p50 > 0:
                metrics["avg_p50_diff_pct"] = 100 * (sim_avg_p50 - meas_avg_p50) / meas_avg_p50
                metrics["sim_avg_p50"] = sim_avg_p50
                metrics["meas_avg_p50"] = meas_avg_p50
    
    return metrics


def plot_summary(
    metrics: dict,
    experiment_name: str,
    output_path: Path = None,
):
    """
    Create summary plot with condensed statistical comparisons.
    
    Layout: 2x3 grid
    - Top row: MAE metrics (bars), Pod-seconds comparison, MAPE P50
    - Bottom row: Boxplots of P50/P90/P95, KS distances
    """
    fig = plt.figure(figsize=(18, 10))
    gs = fig.add_gridspec(2, 3, hspace=0.3, wspace=0.3)
    fig.suptitle(f"Summary Statistics: {experiment_name}", fontsize=16, fontweight="bold")
    
    # Color scheme
    sim_color = "#1f77b4"
    meas_color = "#d62728"
    
    # Top-left: MAE metrics (Pods and HPA)
    ax1 = fig.add_subplot(gs[0, 0])
    mae_labels = []
    mae_values = []
    if "mae_pods" in metrics:
        mae_labels.append("Pods")
        mae_values.append(metrics["mae_pods"])
    if "mae_hpa" in metrics:
        mae_labels.append("HPA CPU")
        mae_values.append(metrics["mae_hpa"])
    
    if mae_labels:
        bars = ax1.bar(mae_labels, mae_values, color=[sim_color, "#ff7f0e"])
        ax1.set_ylabel("Mean Absolute Error", fontsize=11)
        ax1.set_title("MAE: Pods & HPA CPU", fontsize=12, fontweight="bold")
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Annotate values
        for bar, val in zip(bars, mae_values):
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height,
                    f'{val:.3f}', ha='center', va='bottom', fontsize=10)
    
    # Top-middle: Pod-seconds comparison
    ax2 = fig.add_subplot(gs[0, 1])
    if "pod_seconds_diff_pct" in metrics:
        labels = ["Simulation", "Measured"]
        values = [metrics.get("sim_pod_seconds", 0), metrics.get("meas_pod_seconds", 0)]
        bars = ax2.bar(labels, values, color=[sim_color, meas_color])
        ax2.set_ylabel("Pod-seconds", fontsize=11)
        ax2.set_title(f"Pod-seconds (Δ: {metrics['pod_seconds_diff_pct']:.1f}%)", fontsize=12, fontweight="bold")
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Annotate values
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{val:.0f}', ha='center', va='bottom', fontsize=10)
    
    # Top-right: MAPE P50 and Average P50 difference
    ax3 = fig.add_subplot(gs[0, 2])
    if "mape_p50" in metrics:
        ax3.bar(["MAPE P50"], [metrics["mape_p50"]], color="#2ca02c")
        ax3.set_ylabel("MAPE (%)", fontsize=11)
        ax3.set_title(f"MAPE P50 (n={metrics.get('mape_p50_n_points', 0)})", fontsize=12, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis='y')
        ax3.text(0, metrics["mape_p50"], f"{metrics['mape_p50']:.2f}%",
                ha='center', va='bottom', fontsize=11, fontweight='bold')
    else:
        ax3.text(0.5, 0.5, "MAPE P50\nNot Available\n(filtered data)", 
                ha='center', va='center', fontsize=11, transform=ax3.transAxes)
        ax3.axis('off')
    
    # Add Average P50 difference as text box
    if "avg_p50_diff_pct" in metrics:
        textstr = f"Avg P50 Difference\n{metrics['avg_p50_diff_pct']:+.2f}%\n\nSim: {metrics['sim_avg_p50']:.3f}s\nMeas: {metrics['meas_avg_p50']:.3f}s"
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        ax3.text(0.02, 0.02, textstr, transform=ax3.transAxes, fontsize=10,
                verticalalignment='bottom', bbox=props)
    
    # Bottom-left: Boxplots of P50, P90, P95
    ax4 = fig.add_subplot(gs[1, 0:2])
    if len(metrics.get("sim_p50_all", [])) > 0:
        box_data = []
        box_labels = []
        box_positions = []
        pos = 1
        
        for percentile, label in [("p50", "P50"), ("p90", "P90"), ("p95", "P95")]:
            if f"sim_{percentile}_all" in metrics and len(metrics[f"sim_{percentile}_all"]) > 0:
                box_data.append(metrics[f"sim_{percentile}_all"])
                box_labels.append(f"{label}\nSim")
                box_positions.append(pos)
                pos += 1
                
                if f"meas_{percentile}_all" in metrics and len(metrics[f"meas_{percentile}_all"]) > 0:
                    box_data.append(metrics[f"meas_{percentile}_all"])
                    box_labels.append(f"{label}\nMeas")
                    box_positions.append(pos)
                pos += 2
        
        bp = ax4.boxplot(box_data, positions=box_positions, labels=box_labels,
                        patch_artist=True, widths=0.6)
        
        # Color boxes
        for i, patch in enumerate(bp['boxes']):
            if "Sim" in box_labels[i]:
                patch.set_facecolor(sim_color)
                patch.set_alpha(0.6)
            else:
                patch.set_facecolor(meas_color)
                patch.set_alpha(0.6)
        
        ax4.set_ylabel("Response Time (s)", fontsize=11)
        ax4.set_title("RCT Distribution Comparison (all time points)", fontsize=12, fontweight="bold")
        ax4.grid(True, alpha=0.3, axis='y')
    
    # Bottom-right: KS distances
    ax5 = fig.add_subplot(gs[1, 2])
    if "ks_p50" in metrics:
        ks_labels = ["P50", "P90", "P95"]
        ks_values = [metrics.get("ks_p50", 0), metrics.get("ks_p90", 0), metrics.get("ks_p95", 0)]
        bars = ax5.bar(ks_labels, ks_values, color=["#2ca02c", "#9467bd", "#8c564b"])
        ax5.set_ylabel("KS Distance", fontsize=11)
        ax5.set_title("KS 2-sample Test", fontsize=12, fontweight="bold")
        ax5.set_ylim(0, 1)
        ax5.grid(True, alpha=0.3, axis='y')
        
        # Annotate values
        for bar, val in zip(bars, ks_values):
            height = bar.get_height()
            ax5.text(bar.get_x() + bar.get_width()/2., height,
                    f'{val:.3f}', ha='center', va='bottom', fontsize=10)
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Summary plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Compare simulation results against measured data with confidence intervals"
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
        "--measurements-dir",
        default="experiments/measurements",
        help="Path to measurements directory (default: experiments/measurements)",
    )
    parser.add_argument(
        "--deployment",
        default="burn-cpu",
        help="Deployment name (default: burn-cpu)",
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
    measurements_dir = (repo_root / args.measurements_dir).resolve()
    
    # Create batch pattern from experiment name
    batch_pattern = f"*_{args.experiment}_*"
    
    print(f"Experiment: {args.experiment}")
    print(f"Finding simulation runs with pattern: {batch_pattern}")
    run_dirs = find_batch_runs(runs_dir, batch_pattern)
    print(f"Found {len(run_dirs)} simulation runs")
    
    # Load simulation data from all runs
    counter_dfs = []
    hpa_dfs = []
    
    for run_dir in run_dirs:
        log_path = run_dir / "app.log"
        if not log_path.exists():
            print(f"Warning: Log file not found in {run_dir.name}, skipping")
            continue
        
        print(f"Processing simulation: {run_dir.name}")
        
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
            if len(hpa_df) > 0:
                hpa_df = normalize_time(hpa_df, "simTime")
                hpa_dfs.append(hpa_df)
        except Exception as e:
            print(f"Warning: Failed to load HPA data from {run_dir.name}: {e}")
    
    if not counter_dfs:
        raise ValueError("No valid simulation counter data found")
    
    print(f"\nComputing simulation statistics across {len(counter_dfs)} runs...")
    
    # Compute confidence intervals for simulation data
    sim_counter_stats = {
        "rps": compute_confidence_interval(counter_dfs, "simTime", "rps", args.ci),
        "pods": compute_confidence_interval(counter_dfs, "simTime", "podsRunning", args.ci),
        "p50": compute_confidence_interval(counter_dfs, "simTime", "p50", args.ci),
        "p90": compute_confidence_interval(counter_dfs, "simTime", "p90", args.ci),
        "p95": compute_confidence_interval(counter_dfs, "simTime", "p95", args.ci),
    }
    
    sim_hpa_stats = pd.DataFrame(columns=["time", "mean", "lower", "upper"])
    if hpa_dfs:
        sim_hpa_stats = compute_confidence_interval(hpa_dfs, "simTime", "cpu_avg", args.ci)
    
    # Load measurement data
    print(f"\nLoading measurement data...")
    measured_dfs = []
    try:
        measurement_files = find_measurement_files(measurements_dir, args.experiment)
        print(f"Found {len(measurement_files)} measurement files")
        
        for meas_file in measurement_files:
            print(f"Processing measurement: {meas_file.name}")
            try:
                df = load_measurement_data(meas_file, args.deployment)
                measured_dfs.append(df)
            except Exception as e:
                print(f"Warning: Failed to load measurement file {meas_file.name}: {e}")
    except Exception as e:
        print(f"Warning: Failed to find measurement files: {e}")
    
    # Compute statistics for measurement data (mean and CI)
    measured_stats = {}
    if measured_dfs:
        print(f"\nComputing measurement statistics across {len(measured_dfs)} runs...")
        measured_stats = {
            "rps": compute_confidence_interval(measured_dfs, "x", "rps", args.ci),
            "pods": compute_confidence_interval(measured_dfs, "x", "pods", args.ci),
            "rct_p50": compute_confidence_interval(measured_dfs, "x", "rct_p50", args.ci),
            "rct_p90": compute_confidence_interval(measured_dfs, "x", "rct_p90", args.ci),
            "rct_p95": compute_confidence_interval(measured_dfs, "x", "rct_p95", args.ci),
            "hpa_cpu": compute_confidence_interval(measured_dfs, "x", "hpa_cpu", args.ci),
        }
    
    # Generate detailed comparison plot
    if args.output:
        output_path = Path(args.output).resolve()
        plot_comparison(sim_counter_stats, sim_hpa_stats, measured_stats, args.experiment, output_path,
                       counter_dfs=counter_dfs, hpa_dfs=hpa_dfs, measured_dfs=measured_dfs, show_individual_runs=True)
    
    # Compute summary statistics (using data after t=100s)
    print(f"\nComputing summary statistics (t >= 100s)...")
    summary_metrics = compute_summary_statistics(
        sim_counter_stats, sim_hpa_stats, measured_stats, counter_dfs, hpa_dfs, measured_dfs
    )
    
    # Calculate additional metrics for final CSV export
    final_metrics_csv_path = repo_root / "experiments" / "final_metrics.csv"
    
    # Get MAE (Mean Absolute Error) metrics
    mae_p50 = summary_metrics.get("mae_p50", np.nan)
    mae_pods = summary_metrics.get("mae_pods", np.nan)
    mae_hpa = summary_metrics.get("mae_hpa", np.nan)
    
    # Get other error metrics
    mape_p50 = summary_metrics.get("mape_p50", np.nan)
    avg_p50_diff_pct = summary_metrics.get("avg_p50_diff_pct", np.nan)
    pod_minutes_diff_pct = summary_metrics.get("pod_seconds_diff_pct", np.nan)  # Already in percentage
    
    # Read existing metrics
    existing_final_metrics = {}
    if final_metrics_csv_path.exists():
        with open(final_metrics_csv_path, 'r') as f:
            header = f.readline()  # Skip header
            for line in f:
                line = line.strip()
                if line:
                    parts = line.split('\t')
                    if len(parts) == 7:
                        exp_name = parts[0]
                        existing_final_metrics[exp_name] = parts[1:]
    
    # Format experiment name with leading zero if needed
    exp_parts = args.experiment.split('_')
    if len(exp_parts) >= 2 and exp_parts[-1].isdigit() and len(exp_parts[-1]) == 1:
        formatted_exp_name = '_'.join(exp_parts[:-1]) + '_' + exp_parts[-1].zfill(2)
    else:
        formatted_exp_name = args.experiment
    
    # Update with current experiment
    existing_final_metrics[formatted_exp_name] = [
        f"{mae_p50:.4f}" if not np.isnan(mae_p50) else "NaN",
        f"{mae_pods:.2f}" if not np.isnan(mae_pods) else "NaN",
        f"{mae_hpa:.4f}" if not np.isnan(mae_hpa) else "NaN",
        f"{mape_p50:.2f}" if not np.isnan(mape_p50) else "NaN",
        f"{avg_p50_diff_pct:.2f}" if not np.isnan(avg_p50_diff_pct) else "NaN",
        f"{pod_minutes_diff_pct:.2f}" if not np.isnan(pod_minutes_diff_pct) else "NaN",
    ]
    
    # Sort by experiment name (natural sort for numbers)
    def natural_sort_key(s):
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
    
    sorted_experiments = sorted(existing_final_metrics.keys(), key=natural_sort_key)
    
    # Write to CSV
    with open(final_metrics_csv_path, 'w') as f:
        f.write("Experiment\tmae_rct_p50_s\tmae_nr_pods\tmae_cpu_util\tmape_rct_p50_pct\tmean_rct_p50_rel_error\tdelta_pod_minutes_pct\n")
        for exp_name in sorted_experiments:
            values = existing_final_metrics[exp_name]
            values_str = '\t'.join(values)
            f.write(f"{exp_name}\t{values_str}\n")
    
    print(f"\nFinal metrics written to: {final_metrics_csv_path}")
    
    # Write/update summary metrics to CSV file
    metrics_csv_path = repo_root / "experiments" / "validation_metrics.csv"
    if "avg_p50_diff_pct" in summary_metrics:
        # Read existing metrics
        existing_metrics = {}
        if metrics_csv_path.exists():
            with open(metrics_csv_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) == 2:
                            existing_metrics[parts[0]] = float(parts[1])
        
        # Update with current experiment
        existing_metrics[args.experiment] = abs(summary_metrics["avg_p50_diff_pct"])
        
        # Sort by experiment name and write
        with open(metrics_csv_path, 'w') as f:
            f.write("# Experiment\tAverage_P50_Absolute_Error_Percent\n")
            for exp_name in sorted(existing_metrics.keys()):
                f.write(f"{exp_name}\t{existing_metrics[exp_name]:.4f}\n")
        
        print(f"\nValidation metrics written to: {metrics_csv_path}")
        print(f"Average P50 Absolute Error: {abs(summary_metrics['avg_p50_diff_pct']):.4f}%")
    
    # Generate summary plot
    if args.output:
        # Create summary filename: EXPERIMENT_0.png -> EXPERIMENT_0_summary.png
        output_base = Path(args.output)
        summary_output = output_base.parent / f"{output_base.stem}_summary{output_base.suffix}"
        plot_summary(summary_metrics, args.experiment, summary_output)
    else:
        # Show detailed plot first
        plot_comparison(sim_counter_stats, sim_hpa_stats, measured_stats, args.experiment, None,
                       counter_dfs=counter_dfs, hpa_dfs=hpa_dfs, measured_dfs=measured_dfs, show_individual_runs=True)
        # Then show summary plot
        plot_summary(summary_metrics, args.experiment, None)
    
    print("\nComparison complete!")


if __name__ == "__main__":
    main()
