#!/usr/bin/env python3

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# Threshold for filtering out erroneous P50 values (0.1ms)
P50_THRESHOLD = 0.0001  # seconds

# Bookinfo service list
BOOKINFO_SERVICES = ["productpage", "details", "reviews-v2", "ratings"]


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


def load_counter_events_per_service(log_path: Path) -> dict[str, pd.DataFrame]:
    """
    Load counter events from simulation log, organized by service.
    
    Returns:
        Dictionary mapping service names to DataFrames with columns:
        simTime, p50, p90, p95, rps, podsRunning
    """
    service_data = {svc: [] for svc in BOOKINFO_SERVICES}
    
    with open(log_path, 'r') as f:
        for line in f:
            try:
                log_entry = json.loads(line.strip())
                if log_entry.get('msg') == '*events.CounterEvent':
                    service_name = log_entry.get('serviceName')
                    if service_name in BOOKINFO_SERVICES:
                        service_data[service_name].append({
                            'simTime': float(log_entry['simTime']),
                            'p50': log_entry['p50'],
                            'p90': log_entry['p90'],
                            'p95': log_entry['p95'],
                            'rps': log_entry.get('nrReq', 0) / 5.0,  # Convert to RPS (5s intervals)
                            'podsRunning': log_entry['podsRunning'],
                        })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    
    # Convert to DataFrames
    result = {}
    for service, data in service_data.items():
        if data:
            result[service] = pd.DataFrame(data).sort_values('simTime').reset_index(drop=True)
        else:
            result[service] = pd.DataFrame(columns=['simTime', 'p50', 'p90', 'p95', 'rps', 'podsRunning'])
    
    return result


def load_hpa_events_per_service(log_path: Path) -> dict[str, pd.DataFrame]:
    """
    Load HPA events from simulation log, organized by deployment.
    
    Returns:
        Dictionary mapping deployment names to DataFrames with columns:
        simTime, cpu_avg (mean CPU utilization 0-1)
    """
    deployment_data = {}
    
    with open(log_path, 'r') as f:
        for line in f:
            try:
                log_entry = json.loads(line.strip())
                if log_entry.get('msg') == '*events.HPAEvent':
                    deployment_name = log_entry.get('deploymentName')
                    if deployment_name:
                        if deployment_name not in deployment_data:
                            deployment_data[deployment_name] = []
                        
                        deployment_data[deployment_name].append({
                            'simTime': float(log_entry['simTime']),
                            'cpu_avg': log_entry.get('meanCpuUtilization', 0),
                        })
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    
    # Convert to DataFrames
    result = {}
    for deployment, data in deployment_data.items():
        if data:
            result[deployment] = pd.DataFrame(data).sort_values('simTime').reset_index(drop=True)
        else:
            result[deployment] = pd.DataFrame(columns=['simTime', 'cpu_avg'])
    
    return result


def normalize_time(df: pd.DataFrame, time_col: str = "simTime") -> pd.DataFrame:
    """Normalize time to start at 0."""
    df = df.copy()
    if len(df) > 0 and time_col in df.columns:
        t_start = df[time_col].min()
        df[time_col] = df[time_col] - t_start
    return df


def compute_confidence_interval(data_list: list[pd.DataFrame], time_col: str, value_col: str, ci: float = 0.95, t_min_warmup: float = 0.0):
    """
    Compute mean and confidence interval across multiple runs.
    
    Args:
        data_list: List of DataFrames, each with time_col and value_col
        time_col: Name of time column
        value_col: Name of value column
        ci: Confidence level (default 0.95 for 95% CI)
        t_min_warmup: Minimum time to start analysis (skip warm-up period, default: 0.0)
    
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
    
    # Find common time range across all runs (skip warm-up period)
    t_min = max(
        max(df[time_col].min() for df in valid_dfs),
        t_min_warmup
    )
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
    
    # Use t-distribution for small sample sizes
    if n > 30:
        z = 1.96 if ci == 0.95 else 2.576
        margin = z * std / np.sqrt(n)
    else:
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


def load_bi_measurement(csv_path: Path, service: str) -> pd.DataFrame:
    """
    Load a single Bookinfo measurement CSV file for a specific service.
    
    Args:
        csv_path: Path to CSV file
        service: Service name (productpage, details, reviews-v2, ratings)
    
    Returns:
        DataFrame with columns: x (time), rps, rct_p50, rct_p90, rct_p95, hpa_cpu, pods
    """
    df = pd.read_csv(csv_path)
    
    # Convert timestamp to elapsed time
    time = pd.to_datetime(df["timestamp"])
    df["x"] = (time - time.iloc[0]).dt.total_seconds()
    
    # Define upstream service mapping for BookInfo architecture
    upstream_map = {
        "productpage": "unknown",
        "details": "productpage-v1",
        "reviews-v2": "productpage-v1",
        "reviews": "productpage-v1",
        "ratings": "reviews-v2",
    }
    
    upstream = upstream_map.get(service, "unknown")
    service_with_version = service if service.endswith("-v1") or service.endswith("-v2") else f"{service}-v1"
    
    # Extract metrics - use rps_ prefix (not downstream_rps__)
    rps_col = f"rps_{upstream}_TO_{service_with_version}"
    rct_p50_col = f"rct_p50_{upstream}_TO_{service_with_version}"
    rct_p90_col = f"rct_p90_{upstream}_TO_{service_with_version}"
    rct_p95_col = f"rct_p95_{upstream}_TO_{service_with_version}"
    
    # Verify we're using the correct RPS column (rps_, not downstream_rps__)
    if rps_col not in df.columns:
        # Debug: check what columns are available
        available_rps_cols = [col for col in df.columns if 'rps' in col.lower() and service_with_version in col]
        print(f"Warning: Expected RPS column '{rps_col}' not found. Available: {available_rps_cols}")
    
    # HPA column uses version-less name for most services, but reviews-v2 keeps the suffix
    service_base = service.replace("-v1", "").replace("-v2", "")
    hpa_col_base = f"hpa_target_metric_{service_base}"
    hpa_col_versioned = f"hpa_target_metric_{service}"
    pods_col = f"nr_pods_{service_with_version}"
    
    # Try both versioned and base column names
    if hpa_col_versioned in df.columns:
        hpa_col = hpa_col_versioned
    elif hpa_col_base in df.columns:
        hpa_col = hpa_col_base
    else:
        hpa_col = None
    
    result = pd.DataFrame({
        "x": df["x"],
        "rps": df[rps_col] if rps_col in df.columns else 0,
        "rct_p50": df[rct_p50_col] / 1000.0 if rct_p50_col in df.columns else 0,
        "rct_p90": df[rct_p90_col] / 1000.0 if rct_p90_col in df.columns else 0,
        "rct_p95": df[rct_p95_col] / 1000.0 if rct_p95_col in df.columns else 0,
        "hpa_cpu": df[hpa_col] / 100.0 if hpa_col and hpa_col in df.columns else 0,
        "pods": df[pods_col] if pods_col in df.columns else 1,
    })
    
    return result


def compute_summary_statistics_per_service(
    sim_counter_stats: dict,
    sim_hpa_stats: dict,
    measured_stats: dict,
    counter_dfs: dict,
    hpa_dfs: dict,
    measured_dfs: dict,
    service: str,
    t_min_warmup: float,
) -> dict:
    """
    Compute summary statistics comparing simulation vs measured data for a single service.
    
    Args:
        t_min_warmup: Minimum time to start analysis (skip warm-up period, default: 400s)
    
    Returns:
        Dictionary with computed metrics
    """
    metrics = {}
    
    # Get data for this service
    sim_counter = sim_counter_stats.get(service, {})
    sim_hpa = sim_hpa_stats.get(service, pd.DataFrame())
    meas = measured_stats.get(service, {})
    
    if not meas or "pods" not in meas or len(meas["pods"]) == 0:
        return metrics
    
    # Common time range (skip warm-up period)
    t_min = max(
        sim_counter.get("pods", pd.DataFrame()).get("time", pd.Series([0])).min() if "pods" in sim_counter else 0,
        meas["pods"]["time"].min(),
        t_min_warmup  # Skip warm-up period
    )
    t_max = min(
        sim_counter.get("pods", pd.DataFrame()).get("time", pd.Series([float('inf')])).max() if "pods" in sim_counter else float('inf'),
        meas["pods"]["time"].max()
    )
    
    # 1. MAE of number of pods
    if "pods" in sim_counter and len(sim_counter["pods"]) > 0 and "pods" in meas:
        sim_pods = sim_counter["pods"]
        meas_pods = meas["pods"]
        mask_sim = (sim_pods["time"] >= t_min) & (sim_pods["time"] <= t_max)
        mask_meas = (meas_pods["time"] >= t_min) & (meas_pods["time"] <= t_max)
        sim_time = sim_pods["time"][mask_sim].values
        sim_mean = sim_pods["mean"][mask_sim].values
        
        meas_pods_interp = np.interp(sim_time, meas_pods["time"][mask_meas].values, meas_pods["mean"][mask_meas].values)
        metrics["mae_pods"] = np.mean(np.abs(sim_mean - meas_pods_interp))
    
    # 2. MAE of HPA CPU metric (after t=100s)
    if len(sim_hpa) > 0 and "hpa_cpu" in meas and len(meas["hpa_cpu"]) > 0:
        meas_hpa = meas["hpa_cpu"]
        mask_sim = (sim_hpa["time"] >= max(t_min, t_min_warmup)) & (sim_hpa["time"] <= t_max)
        mask_meas = (meas_hpa["time"] >= max(t_min, t_min_warmup)) & (meas_hpa["time"] <= t_max)
        sim_time = sim_hpa["time"][mask_sim].values
        sim_mean = sim_hpa["mean"][mask_sim].values
        
        if len(sim_time) > 0:
            meas_hpa_interp = np.interp(sim_time, meas_hpa["time"][mask_meas].values, meas_hpa["mean"][mask_meas].values)
            metrics["mae_hpa"] = np.mean(np.abs(sim_mean - meas_hpa_interp))
    
    # 3. Percentual difference in pod-seconds
    if "pods" in sim_counter and len(sim_counter["pods"]) > 0 and "pods" in meas:
        sim_pods = sim_counter["pods"]
        meas_pods = meas["pods"]
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
    
    # 4. Collect all P50, P90, P95 values for boxplot
    metrics["sim_p50_all"] = []
    metrics["sim_p90_all"] = []
    metrics["sim_p95_all"] = []
    
    service_counter_dfs = counter_dfs.get(service, [])
    for df in service_counter_dfs:
        mask = (df["simTime"] >= t_min) & (df["simTime"] <= t_max) & (df["p50"] >= P50_THRESHOLD)
        metrics["sim_p50_all"].extend(df[mask]["p50"].values)
        metrics["sim_p90_all"].extend(df[mask]["p90"].values)
        metrics["sim_p95_all"].extend(df[mask]["p95"].values)
    
    metrics["meas_p50_all"] = []
    metrics["meas_p90_all"] = []
    metrics["meas_p95_all"] = []
    
    service_meas_dfs = measured_dfs.get(service, [])
    for df in service_meas_dfs:
        mask = (df["x"] >= t_min) & (df["x"] <= t_max) & (df["rct_p50"] >= P50_THRESHOLD)
        metrics["meas_p50_all"].extend(df[mask]["rct_p50"].values)
        metrics["meas_p90_all"].extend(df[mask]["rct_p90"].values)
        metrics["meas_p95_all"].extend(df[mask]["rct_p95"].values)
    
    # 5. MAE and MAPE of RCT P50, P90, P95
    if "p50" in sim_counter and len(sim_counter["p50"]) > 0 and "rct_p50" in meas:
        sim_p50 = sim_counter["p50"]
        meas_p50 = meas["rct_p50"]
        mask_sim = (sim_p50["time"] >= t_min) & (sim_p50["time"] <= t_max)
        mask_meas = (meas_p50["time"] >= t_min) & (meas_p50["time"] <= t_max)
        sim_time = sim_p50["time"][mask_sim].values
        sim_mean = sim_p50["mean"][mask_sim].values
        
        meas_p50_interp = np.interp(sim_time, meas_p50["time"][mask_meas].values, meas_p50["mean"][mask_meas].values)
        
        # Filter out points below threshold
        valid_mask = (meas_p50_interp >= P50_THRESHOLD) & (sim_mean >= P50_THRESHOLD)
        if np.any(valid_mask):
            # MAE (Mean Absolute Error)
            metrics["mae_p50"] = np.mean(np.abs(sim_mean[valid_mask] - meas_p50_interp[valid_mask]))
            # MAPE (Mean Absolute Percentage Error)
            mape = np.mean(np.abs((sim_mean[valid_mask] - meas_p50_interp[valid_mask]) / meas_p50_interp[valid_mask])) * 100
            metrics["mape_p50"] = mape
            metrics["mape_p50_n_points"] = np.sum(valid_mask)
    
    # MAPE for P90
    if "p90" in sim_counter and len(sim_counter["p90"]) > 0 and "rct_p90" in meas:
        sim_p90 = sim_counter["p90"]
        meas_p90 = meas["rct_p90"]
        mask_sim = (sim_p90["time"] >= t_min) & (sim_p90["time"] <= t_max)
        mask_meas = (meas_p90["time"] >= t_min) & (meas_p90["time"] <= t_max)
        sim_time = sim_p90["time"][mask_sim].values
        sim_mean = sim_p90["mean"][mask_sim].values
        
        meas_p90_interp = np.interp(sim_time, meas_p90["time"][mask_meas].values, meas_p90["mean"][mask_meas].values)
        
        # Filter out points below threshold
        valid_mask = (meas_p90_interp >= P50_THRESHOLD) & (sim_mean >= P50_THRESHOLD)
        if np.any(valid_mask):
            # MAE (Mean Absolute Error)
            metrics["mae_p90"] = np.mean(np.abs(sim_mean[valid_mask] - meas_p90_interp[valid_mask]))
            # MAPE (Mean Absolute Percentage Error)
            mape = np.mean(np.abs((sim_mean[valid_mask] - meas_p90_interp[valid_mask]) / meas_p90_interp[valid_mask])) * 100
            metrics["mape_p90"] = mape
            metrics["mape_p90_n_points"] = np.sum(valid_mask)
    
    # MAPE for P95
    if "p95" in sim_counter and len(sim_counter["p95"]) > 0 and "rct_p95" in meas:
        sim_p95 = sim_counter["p95"]
        meas_p95 = meas["rct_p95"]
        mask_sim = (sim_p95["time"] >= t_min) & (sim_p95["time"] <= t_max)
        mask_meas = (meas_p95["time"] >= t_min) & (meas_p95["time"] <= t_max)
        sim_time = sim_p95["time"][mask_sim].values
        sim_mean = sim_p95["mean"][mask_sim].values
        
        meas_p95_interp = np.interp(sim_time, meas_p95["time"][mask_meas].values, meas_p95["mean"][mask_meas].values)
        
        # Filter out points below threshold
        valid_mask = (meas_p95_interp >= P50_THRESHOLD) & (sim_mean >= P50_THRESHOLD)
        if np.any(valid_mask):
            # MAE (Mean Absolute Error)
            metrics["mae_p95"] = np.mean(np.abs(sim_mean[valid_mask] - meas_p95_interp[valid_mask]))
            # MAPE (Mean Absolute Percentage Error)
            mape = np.mean(np.abs((sim_mean[valid_mask] - meas_p95_interp[valid_mask]) / meas_p95_interp[valid_mask])) * 100
            metrics["mape_p95"] = mape
            metrics["mape_p95_n_points"] = np.sum(valid_mask)
    
    # 6. KS distance of distributions
    if len(metrics.get("sim_p50_all", [])) > 0 and len(metrics.get("meas_p50_all", [])) > 0:
        metrics["ks_p50"] = stats.ks_2samp(metrics["sim_p50_all"], metrics["meas_p50_all"]).statistic
        metrics["ks_p90"] = stats.ks_2samp(metrics["sim_p90_all"], metrics["meas_p90_all"]).statistic
        metrics["ks_p95"] = stats.ks_2samp(metrics["sim_p95_all"], metrics["meas_p95_all"]).statistic
    
    # 7. Average P50 difference (percentual)
    if "p50" in sim_counter and len(sim_counter["p50"]) > 0 and "rct_p50" in meas and len(meas["rct_p50"]) > 0:
        sim_p50 = sim_counter["p50"]
        meas_p50 = meas["rct_p50"]
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


def plot_comparison(
    sim_counter_stats: dict,
    sim_hpa_stats: pd.DataFrame,
    measured_stats: dict,
    experiment_name: str,
    service: str,
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
        service: Service name
        output_path: Optional path to save the plot
        counter_dfs: Optional list of raw counter DataFrames for plotting individual runs
        hpa_dfs: Optional list of raw HPA DataFrames for plotting individual runs
        measured_dfs: Optional list of raw measurement DataFrames for plotting individual runs
        show_individual_runs: If True, plot all individual simulation and measurement runs
    """
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f"Simulation vs Measured: {experiment_name} - {service}", fontsize=16, fontweight="bold")
    
    # Color scheme: Blue for simulation, Red for measured
    sim_color = "#1f77b4"
    measured_color = "#d62728"
    sim_individual_color = "#1f77b4"
    measured_individual_color = "#d62728"
    
    # Row 1, Col 1: P50 vs time
    ax = axes[0, 0]
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p50"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p50" in sim_counter_stats and len(sim_counter_stats["p50"]) > 0:
        df = sim_counter_stats["p50"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["rct_p50"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p50" in measured_stats and len(measured_stats["rct_p50"]) > 0:
        df = measured_stats["rct_p50"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P50 Response Time (s)", fontsize=11)
    ax.set_title("RCT P50", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 0.2)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 1, Col 2: P90 vs time
    ax = axes[0, 1]
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p90"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p90" in sim_counter_stats and len(sim_counter_stats["p90"]) > 0:
        df = sim_counter_stats["p90"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["rct_p90"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p90" in measured_stats and len(measured_stats["rct_p90"]) > 0:
        df = measured_stats["rct_p90"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P90 Response Time (s)", fontsize=11)
    ax.set_title("RCT P90", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 0.2)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 1, Col 3: P95 vs time
    ax = axes[0, 2]
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["p95"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p95" in sim_counter_stats and len(sim_counter_stats["p95"]) > 0:
        df = sim_counter_stats["p95"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["rct_p95"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rct_p95" in measured_stats and len(measured_stats["rct_p95"]) > 0:
        df = measured_stats["rct_p95"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P95 Response Time (s)", fontsize=11)
    ax.set_title("RCT P95", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 0.2)
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 1: RPS vs time
    ax = axes[1, 0]
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["rps"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rps" in sim_counter_stats and len(sim_counter_stats["rps"]) > 0:
        df = sim_counter_stats["rps"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["rps"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rps" in measured_stats and len(measured_stats["rps"]) > 0:
        df = measured_stats["rps"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Requests per Second (RPS)", fontsize=11)
    ax.set_title("Request Rate", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 2: Pods vs time
    ax = axes[1, 1]
    if show_individual_runs and counter_dfs:
        for i, df in enumerate(counter_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["podsRunning"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "pods" in sim_counter_stats and len(sim_counter_stats["pods"]) > 0:
        df = sim_counter_stats["pods"]
        ax.plot(df["time"], df["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["pods"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "pods" in measured_stats and len(measured_stats["pods"]) > 0:
        df = measured_stats["pods"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Number of Pods", fontsize=11)
    ax.set_title("Pod Count", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Row 2, Col 3: HPA CPU metric vs time
    ax = axes[1, 2]
    if show_individual_runs and hpa_dfs:
        for i, df in enumerate(hpa_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["simTime"], df["cpu_avg"], color=sim_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if len(sim_hpa_stats) > 0:
        ax.plot(sim_hpa_stats["time"], sim_hpa_stats["mean"], color=sim_color, linewidth=2, label="Simulation (mean)")
        ax.fill_between(sim_hpa_stats["time"], sim_hpa_stats["lower"], sim_hpa_stats["upper"], color=sim_color, alpha=0.2)
    if show_individual_runs and measured_dfs:
        for i, df in enumerate(measured_dfs):
            label = "Individual measurements" if i == 0 else None
            ax.plot(df["x"], df["hpa_cpu"], color=measured_individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "hpa_cpu" in measured_stats and len(measured_stats["hpa_cpu"]) > 0:
        df = measured_stats["hpa_cpu"]
        ax.plot(df["time"], df["mean"], color=measured_color, linewidth=2, label="Measured (mean)")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=measured_color, alpha=0.2)
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("CPU Utilization", fontsize=11)
    ax.set_title("HPA CPU Metric", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def plot_summary(
    metrics: dict,
    experiment_name: str,
    service: str,
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
    fig.suptitle(f"Summary Statistics: {experiment_name} - {service}", fontsize=16, fontweight="bold")
    
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
    
    # Top-right: MAPE for P50, P90, P95
    ax3 = fig.add_subplot(gs[0, 2])
    mape_labels = []
    mape_values = []
    mape_colors = []
    
    if "mape_p50" in metrics:
        mape_labels.append("P50")
        mape_values.append(metrics["mape_p50"])
        mape_colors.append("#2ca02c")
    if "mape_p90" in metrics:
        mape_labels.append("P90")
        mape_values.append(metrics["mape_p90"])
        mape_colors.append("#9467bd")
    if "mape_p95" in metrics:
        mape_labels.append("P95")
        mape_values.append(metrics["mape_p95"])
        mape_colors.append("#8c564b")
    
    if mape_labels:
        bars = ax3.bar(mape_labels, mape_values, color=mape_colors)
        ax3.set_ylabel("MAPE (%)", fontsize=11)
        ax3.set_title("MAPE: RCT Percentiles", fontsize=12, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis='y')
        
        # Annotate values
        for bar, val in zip(bars, mape_values):
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., height,
                    f'{val:.2f}%', ha='center', va='bottom', fontsize=10)
    else:
        ax3.text(0.5, 0.5, "MAPE\nNot Available\n(filtered data)", 
                ha='center', va='center', fontsize=11, transform=ax3.transAxes)
        ax3.axis('off')
    
    # Add Average P50 difference as text box if available
    if "avg_p50_diff_pct" in metrics:
        textstr = f"Avg P50 Diff: {metrics['avg_p50_diff_pct']:+.2f}%"
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        ax3.text(0.02, 0.02, textstr, transform=ax3.transAxes, fontsize=9,
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
        description="Compare Bookinfo simulation results against measured data"
    )
    parser.add_argument(
        "experiment",
        help="Experiment name (e.g., 'EXPERIMENT_BI_CONST_60')",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Path to runs directory (default: runs)",
    )
    parser.add_argument(
        "--measurements-dir",
        default="measurements",
        help="Path to measurements directory (default: measurements)",
    )
    parser.add_argument(
        "--service",
        default="all",
        help="Service to analyze (default: all). Options: " + ", ".join(BOOKINFO_SERVICES + ["all"]),
    )
    parser.add_argument(
        "--output",
        help="Output path for plot (optional, only used when --service is not 'all')",
    )
    parser.add_argument(
        "--ci",
        type=float,
        default=0.95,
        help="Confidence interval level (default: 0.95)",
    )
    parser.add_argument(
        "--t-min",
        type=float,
        default=400.0,
        help="Minimum time to start error analysis, skipping warm-up period (default: 400s)",
    )
    parser.add_argument(
        "--write-metrics",
        action="store_true",
        help="Write metrics to CSV file (default when --service is 'all')",
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    script_dir = Path(__file__).resolve().parent
    runs_dir = (script_dir / args.runs_dir).resolve() if not Path(args.runs_dir).is_absolute() else Path(args.runs_dir)
    measurements_dir = (script_dir / args.measurements_dir).resolve() if not Path(args.measurements_dir).is_absolute() else Path(args.measurements_dir)
    
    # Find simulation runs
    batch_pattern = f"*_{args.experiment}_*"
    print(f"Experiment: {args.experiment}")
    print(f"Finding simulation runs with pattern: {batch_pattern}")
    run_dirs = find_batch_runs(runs_dir, batch_pattern)
    print(f"Found {len(run_dirs)} simulation runs")
    
    # Load simulation data
    all_counter_dfs = {svc: [] for svc in BOOKINFO_SERVICES}
    all_hpa_dfs = {}
    
    for run_dir in run_dirs:
        log_path = run_dir / "app.log"
        if not log_path.exists():
            print(f"Warning: Log file not found in {run_dir.name}, skipping")
            continue
        
        print(f"Processing simulation: {run_dir.name}")
        
        # Load counter events per service
        counter_data = load_counter_events_per_service(log_path)
        for service, df in counter_data.items():
            if len(df) > 0:
                df = normalize_time(df, "simTime")
                all_counter_dfs[service].append(df)
        
        # Load HPA events per deployment
        hpa_data = load_hpa_events_per_service(log_path)
        for deployment, df in hpa_data.items():
            if len(df) > 0:
                df = normalize_time(df, "simTime")
                if deployment not in all_hpa_dfs:
                    all_hpa_dfs[deployment] = []
                all_hpa_dfs[deployment].append(df)
    
    # Determine which services to process
    services_to_process = BOOKINFO_SERVICES if args.service == "all" else [args.service]
    if args.service != "all" and args.service not in BOOKINFO_SERVICES:
        raise ValueError(f"Unknown service: {args.service}. Valid options: {', '.join(BOOKINFO_SERVICES)}")
    
    # Determine if we should write metrics
    write_metrics = args.write_metrics or args.service == "all"
    
    # Storage for all metrics
    all_service_metrics = {}
    
    # Process each service
    for service in services_to_process:
        print(f"\n{'='*60}")
        print(f"Analyzing service: {service}")
        print(f"{'='*60}")
        
        counter_dfs = all_counter_dfs.get(service, [])
        if not counter_dfs:
            print(f"Warning: No simulation data found for service: {service}, skipping")
            continue
        
        print(f"Computing simulation statistics across {len(counter_dfs)} runs (t >= {args.t_min}s)...")
        
        sim_counter_stats = {
            "rps": compute_confidence_interval(counter_dfs, "simTime", "rps", args.ci, args.t_min),
            "pods": compute_confidence_interval(counter_dfs, "simTime", "podsRunning", args.ci, args.t_min),
            "p50": compute_confidence_interval(counter_dfs, "simTime", "p50", args.ci, args.t_min),
            "p90": compute_confidence_interval(counter_dfs, "simTime", "p90", args.ci, args.t_min),
            "p95": compute_confidence_interval(counter_dfs, "simTime", "p95", args.ci, args.t_min),
        }
        
        # HPA stats (deployment name may differ from service name)
        # Try multiple variations: exact service name, without version suffix
        deployment_name = None
        for candidate in [service, service.replace("-v1", "").replace("-v2", "")]:
            if candidate in all_hpa_dfs:
                deployment_name = candidate
                break
        
        hpa_dfs = []
        sim_hpa_stats = pd.DataFrame(columns=["time", "mean", "lower", "upper"])
        if deployment_name:
            hpa_dfs = all_hpa_dfs.get(deployment_name, [])
            print(f"Found HPA data for deployment: {deployment_name}")
            if hpa_dfs:
                sim_hpa_stats = compute_confidence_interval(hpa_dfs, "simTime", "cpu_avg", args.ci, args.t_min)
        else:
            print(f"Warning: No HPA data found for service '{service}'")
        
        # Load measurement data
        print(f"Loading measurement data...")
        measured_dfs = []
        try:
            measurement_files = find_measurement_files(measurements_dir, args.experiment)
            
            for meas_file in measurement_files:
                try:
                    df = load_bi_measurement(meas_file, service)
                    measured_dfs.append(df)
                except Exception as e:
                    print(f"Warning: Failed to load measurement file {meas_file.name}: {e}")
        except Exception as e:
            print(f"Warning: Failed to find measurement files: {e}")
        
        # Compute measurement statistics
        measured_stats = {}
        if measured_dfs:
            print(f"Computing measurement statistics across {len(measured_dfs)} runs (t >= {args.t_min}s)...")
            measured_stats = {
                "rps": compute_confidence_interval(measured_dfs, "x", "rps", args.ci, args.t_min),
                "pods": compute_confidence_interval(measured_dfs, "x", "pods", args.ci, args.t_min),
                "rct_p50": compute_confidence_interval(measured_dfs, "x", "rct_p50", args.ci, args.t_min),
                "rct_p90": compute_confidence_interval(measured_dfs, "x", "rct_p90", args.ci, args.t_min),
                "rct_p95": compute_confidence_interval(measured_dfs, "x", "rct_p95", args.ci, args.t_min),
                "hpa_cpu": compute_confidence_interval(measured_dfs, "x", "hpa_cpu", args.ci, args.t_min),
            }
        
        # Compute summary statistics
        print(f"Computing summary statistics (t >= {args.t_min}s)...")
        summary_metrics = compute_summary_statistics_per_service(
            {service: sim_counter_stats},
            {service: sim_hpa_stats},
            {service: measured_stats},
            {service: counter_dfs},
            {service: hpa_dfs},
            {service: measured_dfs},
            service,
            t_min_warmup=args.t_min
        )
        
        # Store metrics for this service
        all_service_metrics[service] = summary_metrics
        
        # Print summary (skip list-type metrics used for plotting)
        print("\n=== Summary Statistics ===")
        for metric, value in summary_metrics.items():
            if isinstance(value, (int, float, np.number)):
                print(f"{metric}: {value:.4f}")
        
        # Generate plots if output path is specified and single service mode
        if args.output and args.service != "all":
            output_path = Path(args.output).resolve()
            print(f"\nGenerating comparison plot...")
            plot_comparison(
                sim_counter_stats,
                sim_hpa_stats,
                measured_stats,
                args.experiment,
                service,
                output_path,
                counter_dfs=counter_dfs,
                hpa_dfs=hpa_dfs,
                measured_dfs=measured_dfs,
                show_individual_runs=True
            )
            
            # Generate summary plot
            summary_output = output_path.parent / f"{output_path.stem}_summary{output_path.suffix}"
            print(f"\nGenerating summary plot...")
            plot_summary(
                summary_metrics,
                args.experiment,
                service,
                summary_output
            )
    
    # Write metrics to CSV if requested
    if write_metrics and all_service_metrics:
        repo_root = Path(__file__).resolve().parent.parent
        metrics_csv_path = repo_root / "experiments" / "bi_validation_metrics.csv"
        
        # Read existing metrics
        existing_metrics = {}
        if metrics_csv_path.exists():
            with open(metrics_csv_path, 'r') as f:
                header = f.readline().strip()
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        parts = line.split('\t')
                        if len(parts) >= 5:
                            exp_name = parts[0]
                            service_name = parts[1]
                            key = (exp_name, service_name)
                            existing_metrics[key] = parts[2:]
        
        # Update with current experiment metrics
        for service, metrics in all_service_metrics.items():
            mape_p50 = metrics.get("mape_p50", np.nan)
            avg_p50_diff_pct = metrics.get("avg_p50_diff_pct", np.nan)
            mae_p50 = metrics.get("mae_p50", np.nan)
            
            # Convert MAE from seconds to milliseconds
            mae_p50_ms = mae_p50 * 1000.0 if not np.isnan(mae_p50) else np.nan
            
            # Take absolute value of avg_p50_diff_pct
            avg_p50_diff_pct_abs = abs(avg_p50_diff_pct) if not np.isnan(avg_p50_diff_pct) else np.nan
            
            key = (args.experiment, service)
            existing_metrics[key] = [
                f"{mape_p50:.2f}" if not np.isnan(mape_p50) else "NaN",
                f"{avg_p50_diff_pct_abs:.2f}" if not np.isnan(avg_p50_diff_pct_abs) else "NaN",
                f"{mae_p50_ms:.2f}" if not np.isnan(mae_p50_ms) else "NaN",
            ]
        
        # Sort by experiment name, then service name
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
        
        sorted_keys = sorted(existing_metrics.keys(), key=lambda k: (natural_sort_key(k[0]), k[1]))
        
        # Write to CSV
        with open(metrics_csv_path, 'w') as f:
            f.write("Experiment\tService\tMAPE_P50_pct\tAvg_P50_Diff_pct\tMAE_P50_ms\n")
            for key in sorted_keys:
                exp_name, service_name = key
                values = existing_metrics[key]
                values_str = '\t'.join(values)
                f.write(f"{exp_name}\t{service_name}\t{values_str}\n")
        
        print(f"\nValidation metrics written to: {metrics_csv_path}")
    
    print("\nComparison complete!")


if __name__ == "__main__":
    main()
