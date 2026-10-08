#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


def find_bi_measurement_files(measurements_dir: Path, experiment_name: str) -> list[Path]:
    """Find all measurement CSV files for the given Booking.info experiment."""
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


def load_bi_measurement(csv_path: Path, service: str = "productpage") -> pd.DataFrame:
    """
    Load a single Booking.info measurement CSV file.
    
    Args:
        csv_path: Path to CSV file
        service: Service name to extract metrics for (default: productpage)
    
    Returns:
        DataFrame with columns: time, rps, rct_p50, rct_p90, rct_p95, hpa_cpu, pods
    """
    df = pd.read_csv(csv_path)
    
    # Convert timestamp to elapsed time
    time = pd.to_datetime(df["timestamp"])
    df["time"] = (time - time.iloc[0]).dt.total_seconds()
    
    # Define upstream service mapping for BookInfo architecture
    # BookInfo call chain: unknown -> productpage -> details
    #                                             -> reviews-v2 -> ratings
    upstream_map = {
        "productpage": "unknown",
        "details": "productpage-v1",
        "reviews-v2": "productpage-v1",
        "reviews": "productpage-v1",
        "ratings": "reviews-v2",
    }
    
    # Get the upstream service for this target service
    upstream = upstream_map.get(service, "unknown")
    
    # For service names without version suffix, add -v1 for column lookup
    service_with_version = service if service.endswith("-v1") or service.endswith("-v2") else f"{service}-v1"
    
    # Extract metrics based on service and its upstream
    # RPS: incoming traffic from upstream to this service
    rps_col = f"rps_{upstream}_TO_{service_with_version}"
    rct_p50_col = f"rct_p50_{upstream}_TO_{service_with_version}"
    rct_p90_col = f"rct_p90_{upstream}_TO_{service_with_version}"
    rct_p95_col = f"rct_p95_{upstream}_TO_{service_with_version}"
    
    # HPA and pods columns use service name without version
    service_base = service.replace("-v1", "").replace("-v2", "")
    hpa_col = f"hpa_target_metric_{service_base}"
    pods_col = f"nr_pods_{service_with_version}"
    
    result = pd.DataFrame({
        "time": df["time"],
        "rps": df[rps_col] if rps_col in df.columns else 0,
        "rct_p50": df[rct_p50_col] / 1000.0 if rct_p50_col in df.columns else 0,  # Convert ms to s
        "rct_p90": df[rct_p90_col] / 1000.0 if rct_p90_col in df.columns else 0,  # Convert ms to s
        "rct_p95": df[rct_p95_col] / 1000.0 if rct_p95_col in df.columns else 0,  # Convert ms to s
        "hpa_cpu": df[hpa_col] / 100.0 if hpa_col in df.columns else 0,  # Convert 0-100 to 0-1
        "pods": df[pods_col] if pods_col in df.columns else 1,
    })
    
    return result


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
        t_val = stats.t.ppf((1 + ci) / 2, n - 1)
        margin = t_val * std / np.sqrt(n)
    
    return pd.DataFrame({
        "time": time_grid,
        "mean": mean,
        "lower": mean - margin,
        "upper": mean + margin,
    })


def plot_bi_results(
    stats_dict: dict,
    experiment_name: str,
    service: str,
    output_path: Path = None,
    show_individual_runs: bool = False,
    raw_dfs: list[pd.DataFrame] = None,
):
    """
    Create 2x3 plot with RPS, Pods, P50, P90, P95, and HPA CPU metrics with confidence intervals.
    
    Args:
        stats_dict: Dict with keys 'rps', 'pods', 'p50', 'p90', 'p95', 'hpa_cpu', each a DataFrame with time, mean, lower, upper
        experiment_name: Experiment name for plot title
        service: Service name
        output_path: Optional path to save the plot
        show_individual_runs: If True, plot all individual runs
        raw_dfs: Optional list of raw DataFrames for plotting individual runs
    """
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f"Booking.info Analysis: {experiment_name} ({service})", fontsize=16, fontweight="bold")
    
    color = "#1f77b4"
    individual_color = "#1f77b4"
    
    # Top-left: RPS vs time
    ax = axes[0, 0]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["rps"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "rps" in stats_dict and len(stats_dict["rps"]) > 0:
        df = stats_dict["rps"]
        ax.plot(df["time"], df["mean"], color=color, linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=color, alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Requests per Second (RPS)", fontsize=11)
    ax.set_title("Request Rate", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Top-middle: Pods vs time
    ax = axes[0, 1]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["pods"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "pods" in stats_dict and len(stats_dict["pods"]) > 0:
        df = stats_dict["pods"]
        ax.plot(df["time"], df["mean"], color="#ff7f0e", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#ff7f0e", alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Number of Pods", fontsize=11)
    ax.set_title("Pod Count", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Top-right: HPA CPU metric vs time
    ax = axes[0, 2]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["hpa_cpu"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "hpa_cpu" in stats_dict and len(stats_dict["hpa_cpu"]) > 0:
        df = stats_dict["hpa_cpu"]
        ax.plot(df["time"], df["mean"], color="#d62728", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#d62728", alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("CPU Utilization", fontsize=11)
    ax.set_title("HPA CPU Metric", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Bottom-left: P50 vs time
    ax = axes[1, 0]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["rct_p50"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p50" in stats_dict and len(stats_dict["p50"]) > 0:
        df = stats_dict["p50"]
        ax.plot(df["time"], df["mean"], color="#2ca02c", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#2ca02c", alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P50 Response Time (s)", fontsize=11)
    ax.set_title("RCT P50", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Bottom-middle: P90 vs time
    ax = axes[1, 1]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["rct_p90"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p90" in stats_dict and len(stats_dict["p90"]) > 0:
        df = stats_dict["p90"]
        ax.plot(df["time"], df["mean"], color="#9467bd", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#9467bd", alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P90 Response Time (s)", fontsize=11)
    ax.set_title("RCT P90", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # Bottom-right: P95 vs time
    ax = axes[1, 2]
    if show_individual_runs and raw_dfs:
        for i, df in enumerate(raw_dfs):
            label = "Individual runs" if i == 0 else None
            ax.plot(df["time"], df["rct_p95"], color=individual_color, linewidth=0.8, alpha=0.3, label=label)
    if "p95" in stats_dict and len(stats_dict["p95"]) > 0:
        df = stats_dict["p95"]
        ax.plot(df["time"], df["mean"], color="#8c564b", linewidth=2, label="Mean")
        ax.fill_between(df["time"], df["lower"], df["upper"], color="#8c564b", alpha=0.2, label="95% CI")
    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("P95 Response Time (s)", fontsize=11)
    ax.set_title("RCT P95", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Process and visualize Booking.info experiment results with confidence intervals"
    )
    parser.add_argument(
        "experiment",
        help="Experiment name (e.g., 'EXPERIMENT_BI_CONST_60')",
    )
    parser.add_argument(
        "--measurements-dir",
        default="experiments/measurements",
        help="Path to measurements directory (default: experiments/measurements)",
    )
    parser.add_argument(
        "--service",
        default="productpage",
        help="Service name to analyze (default: productpage)",
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
    parser.add_argument(
        "--show-individual",
        action="store_true",
        help="Show individual run traces in addition to mean and CI",
    )
    
    args = parser.parse_args()
    
    repo_root = Path(__file__).resolve().parent.parent
    measurements_dir = (repo_root / args.measurements_dir).resolve()
    
    print(f"Experiment: {args.experiment}")
    print(f"Service: {args.service}")
    print(f"Finding measurement files...")
    
    measurement_files = find_bi_measurement_files(measurements_dir, args.experiment)
    print(f"Found {len(measurement_files)} measurement files")
    
    # Load data from all measurement files
    measurement_dfs = []
    for meas_file in measurement_files:
        print(f"Processing: {meas_file.name}")
        try:
            df = load_bi_measurement(meas_file, args.service)
            measurement_dfs.append(df)
        except Exception as e:
            print(f"Warning: Failed to load measurement file {meas_file.name}: {e}")
    
    if not measurement_dfs:
        raise ValueError("No valid measurement data found")
    
    print(f"\nComputing statistics across {len(measurement_dfs)} runs...")
    
    # Compute confidence intervals
    stats_dict = {
        "rps": compute_confidence_interval(measurement_dfs, "time", "rps", args.ci),
        "pods": compute_confidence_interval(measurement_dfs, "time", "pods", args.ci),
        "p50": compute_confidence_interval(measurement_dfs, "time", "rct_p50", args.ci),
        "p90": compute_confidence_interval(measurement_dfs, "time", "rct_p90", args.ci),
        "p95": compute_confidence_interval(measurement_dfs, "time", "rct_p95", args.ci),
        "hpa_cpu": compute_confidence_interval(measurement_dfs, "time", "hpa_cpu", args.ci),
    }
    
    # Generate plot
    output_path = Path(args.output).resolve() if args.output else None
    plot_bi_results(
        stats_dict,
        args.experiment,
        args.service,
        output_path,
        show_individual_runs=args.show_individual,
        raw_dfs=measurement_dfs if args.show_individual else None,
    )
    
    print("\nAnalysis complete!")


if __name__ == "__main__":
    main()
