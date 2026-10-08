#!/usr/bin/env python3

"""
Plot 1: Comparison of simulation vs measured data for EXPERIMENT_0.
Creates a 2x2 plot showing RPS, RCT P50, Number of Pods, and HPA Target.
Formatted for IEEE double-column width.
"""

import argparse
import fnmatch
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# Import plotting configuration
from plot_config import (
    add_latex_argument,
    configure_plot_style,
    label,
    set_use_latex,
    FIGURE_WIDTH_INCHES,
    FIGURE_HEIGHT_INCHES,
    LINE_WIDTH_MEAN,
    ALPHA_CI,
    COLOR_SIMULATION,
    COLOR_MEASURED,
    FONT_SIZE_TITLE,
    FONT_SIZE_LABEL,
    FONT_SIZE_LEGEND,
    SUBPLOT_LEFT,
    SUBPLOT_RIGHT,
    SUBPLOT_TOP,
    SUBPLOT_BOTTOM,
    SUBPLOT_WSPACE,
    SUBPLOT_HSPACE,
)


# OVERRIDES
FIGURE_HEIGHT_INCHES = FIGURE_WIDTH_INCHES * 0.7
SUBPLOT_HSPACE = 0.75

# Import utility functions from profiler
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "profiler"))
from utils import load_counter_df, load_hpa_df

# Threshold for filtering out erroneous P50 values (20ms)
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
    
    experiment_dir = measurements_dir / experiment_name
    if not experiment_dir.exists():
        raise FileNotFoundError(f"Experiment directory not found: {experiment_dir}")
    
    matching_files = sorted([
        f for f in experiment_dir.iterdir()
        if f.is_file() and f.suffix.lower() == '.csv'
    ])
    
    if not matching_files:
        raise ValueError(f"No CSV files found in: {experiment_dir}")
    
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
        f"rps_unknown_TO_{deployment}": "rps",
        f"nr_pods_{deployment}": "pods",
    }).sort_values("x")
    
    # Convert RCT from milliseconds to seconds
    df["rct_p50"] = df["rct_p50"] / 1000.0
    
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
):
    """
    Create 2x2 plot comparing simulation vs measured data.
    Layout: [RPS] [P50 RCT]
            [Pods] [HPA CPU]
    
    Args:
        sim_counter_stats: Dict with simulation statistics
        sim_hpa_stats: Simulation HPA stats DataFrame
        measured_stats: Dict with measurement statistics
        experiment_name: Experiment name for plot title
        output_path: Optional path to save the plot
    """
    # Configure plot style
    configure_plot_style()
    
    fig, axes = plt.subplots(2, 2, figsize=(FIGURE_WIDTH_INCHES, FIGURE_HEIGHT_INCHES))
    
    # Top-left: RPS vs time
    ax = axes[0, 0]
    sim_line = None
    meas_line = None
    if "rps" in sim_counter_stats and len(sim_counter_stats["rps"]) > 0:
        df = sim_counter_stats["rps"]
        sim_line, = ax.plot(df["time"], df["mean"], color=COLOR_SIMULATION, linewidth=LINE_WIDTH_MEAN, label="Simulation")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_SIMULATION, alpha=ALPHA_CI)
    if "rps" in measured_stats and len(measured_stats["rps"]) > 0:
        df = measured_stats["rps"]
        meas_line, = ax.plot(df["time"], df["mean"], color=COLOR_MEASURED, linewidth=LINE_WIDTH_MEAN, label="Measured")
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_MEASURED, alpha=ALPHA_CI)
    ax.set_title("RPS", fontsize=FONT_SIZE_TITLE)
    ax.grid(True, alpha=0.3)
    
    # Top-right: RCT P50 vs time
    ax = axes[0, 1]
    if "p50" in sim_counter_stats and len(sim_counter_stats["p50"]) > 0:
        df = sim_counter_stats["p50"]
        ax.plot(df["time"], df["mean"], color=COLOR_SIMULATION, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_SIMULATION, alpha=ALPHA_CI)
    if "rct_p50" in measured_stats and len(measured_stats["rct_p50"]) > 0:
        df = measured_stats["rct_p50"]
        ax.plot(df["time"], df["mean"], color=COLOR_MEASURED, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_MEASURED, alpha=ALPHA_CI)
    ax.set_title("$rct_{p50}$ (s)", fontsize=FONT_SIZE_TITLE)
    ax.set_ylim(0, 0.35)
    ax.grid(True, alpha=0.3)
    
    # Bottom-left: Number of Pods vs time
    ax = axes[1, 0]
    if "pods" in sim_counter_stats and len(sim_counter_stats["pods"]) > 0:
        df = sim_counter_stats["pods"]
        ax.plot(df["time"], df["mean"], color=COLOR_SIMULATION, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_SIMULATION, alpha=ALPHA_CI)
    if "pods" in measured_stats and len(measured_stats["pods"]) > 0:
        df = measured_stats["pods"]
        ax.plot(df["time"], df["mean"], color=COLOR_MEASURED, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_MEASURED, alpha=ALPHA_CI)
    ax.set_xlabel("Time (s)", fontsize=FONT_SIZE_LABEL)
    ax.set_title("$nr\_pods$", fontsize=FONT_SIZE_TITLE)
    ax.set_ylim(0, 26)
    ax.grid(True, alpha=0.3)
    
    # Bottom-right: HPA CPU Target vs time
    ax = axes[1, 1]
    if len(sim_hpa_stats) > 0:
        ax.plot(sim_hpa_stats["time"], sim_hpa_stats["mean"], color=COLOR_SIMULATION, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(sim_hpa_stats["time"], sim_hpa_stats["lower"], sim_hpa_stats["upper"], color=COLOR_SIMULATION, alpha=ALPHA_CI)
    if "hpa_cpu" in measured_stats and len(measured_stats["hpa_cpu"]) > 0:
        df = measured_stats["hpa_cpu"]
        ax.plot(df["time"], df["mean"], color=COLOR_MEASURED, linewidth=LINE_WIDTH_MEAN)
        ax.fill_between(df["time"], df["lower"], df["upper"], color=COLOR_MEASURED, alpha=ALPHA_CI)
    ax.set_xlabel("Time (s)", fontsize=FONT_SIZE_LABEL)
    ax.set_title(label("HPA CPU Utilization (\%)"), fontsize=FONT_SIZE_TITLE)
    ax.set_ylim(0, 1.2)
    ax.grid(True, alpha=0.3)
    
    # Add single global legend at the top
    if sim_line and meas_line:
        fig.legend([sim_line, meas_line], ['Simulation', 'Measured'], 
                  loc='upper center', ncol=2, fontsize=FONT_SIZE_LEGEND,
                  bbox_to_anchor=(0.5, 1.02), frameon=False)
    
    plt.subplots_adjust(
        left=SUBPLOT_LEFT,
        right=SUBPLOT_RIGHT,
        top=SUBPLOT_TOP - 0.12,  # More space for titles and legend
        bottom=SUBPLOT_BOTTOM,
        wspace=SUBPLOT_WSPACE,
        hspace=SUBPLOT_HSPACE
    )
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Generate IEEE-formatted comparison plot for EXPERIMENT_0"
    )
    parser.add_argument(
        "--experiment",
        default="EXPERIMENT_0",
        help="Experiment name (default: EXPERIMENT_0)",
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
        "--output-dir",
        default="experiments",
        help="Output directory for plots (default: experiments)",
    )
    parser.add_argument(
        "--output",
        default="plot_1.pdf",
        help="Output filename for plot (default: plot_1.pdf)",
    )
    parser.add_argument(
        "--ci",
        type=float,
        default=0.95,
        help="Confidence interval level (default: 0.95 for 95%% CI)",
    )
    
    add_latex_argument(parser)
    args = parser.parse_args()
    set_use_latex(args.latex)
    
    repo_root = Path(__file__).resolve().parent.parent
    runs_dir = (repo_root / args.runs_dir).resolve()
    measurements_dir = (repo_root / args.measurements_dir).resolve()
    
    # Create batch pattern from experiment name
    batch_pattern = f"*_{args.experiment}_*"
    
    print(f"Experiment: {args.experiment}")
    print(f"Finding simulation runs with pattern: {batch_pattern}")
    run_dirs = find_batch_runs(runs_dir, batch_pattern)
    print(f"Found {len(run_dirs)} simulation runs")
    
    # Load simulation data
    counter_dfs = []
    hpa_dfs = []
    
    for run_dir in run_dirs:
        log_path = run_dir / "app.log"
        if not log_path.exists():
            print(f"Warning: Log file not found in {run_dir.name}, skipping")
            continue
        
        print(f"Processing simulation: {run_dir.name}")
        
        try:
            counter_df = load_counter_df(log_path)
            counter_df = normalize_time(counter_df, "simTime")
            counter_dfs.append(counter_df)
        except Exception as e:
            print(f"Warning: Failed to load counter data: {e}")
        
        try:
            hpa_df = load_hpa_df(log_path, args.deployment)
            if len(hpa_df) > 0:
                hpa_df = normalize_time(hpa_df, "simTime")
                hpa_dfs.append(hpa_df)
        except Exception as e:
            print(f"Warning: Failed to load HPA data: {e}")
    
    if not counter_dfs:
        raise ValueError("No valid simulation data found")
    
    print(f"\nComputing simulation statistics across {len(counter_dfs)} runs...")
    
    # Compute confidence intervals for simulation
    sim_counter_stats = {
        "rps": compute_confidence_interval(counter_dfs, "simTime", "rps", args.ci),
        "pods": compute_confidence_interval(counter_dfs, "simTime", "podsRunning", args.ci),
        "p50": compute_confidence_interval(counter_dfs, "simTime", "p50", args.ci),
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
                print(f"Warning: Failed to load measurement: {e}")
    except Exception as e:
        print(f"Warning: Failed to find measurements: {e}")
    
    # Compute statistics for measurements
    measured_stats = {}
    if measured_dfs:
        print(f"\nComputing measurement statistics across {len(measured_dfs)} runs...")
        measured_stats = {
            "rps": compute_confidence_interval(measured_dfs, "x", "rps", args.ci),
            "pods": compute_confidence_interval(measured_dfs, "x", "pods", args.ci),
            "rct_p50": compute_confidence_interval(measured_dfs, "x", "rct_p50", args.ci),
            "hpa_cpu": compute_confidence_interval(measured_dfs, "x", "hpa_cpu", args.ci),
        }
    
    # Generate plot
    output_dir = (repo_root / args.output_dir).resolve()
    output_path = (output_dir / args.output).resolve()
    plot_comparison(sim_counter_stats, sim_hpa_stats, measured_stats, args.experiment, output_path)
    
    print("\nPlot generation complete!")


if __name__ == "__main__":
    main()
