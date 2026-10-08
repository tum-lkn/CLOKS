#!/usr/bin/env python3

"""
Plot 2: Box plots of P50, P90, and P95 distributions.
Shows comparison of simulation vs measured response time distributions
including outliers.
Formatted for IEEE double-column width.
"""

import argparse
import fnmatch
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Import plotting configuration
from plot_config import (
    add_latex_argument,
    configure_plot_style,
    set_use_latex,
    FIGURE_WIDTH_INCHES,
    FIGURE_HEIGHT_INCHES,
    COLOR_SIMULATION,
    COLOR_MEASURED,
    FONT_SIZE_TITLE,
    FONT_SIZE_LABEL,
    FONT_SIZE_LEGEND,
)

FIGURE_WIDTH_INCHES *= 0.35
FIGURE_HEIGHT_INCHES *= 0.8

# Import utility functions from profiler
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "profiler"))
from utils import load_counter_df

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
        f"rct_p90_unknown_TO_{deployment}": "rct_p90",
        f"rct_p95_unknown_TO_{deployment}": "rct_p95",
    }).sort_values("x")
    
    # Convert RCT from milliseconds to seconds
    df["rct_p50"] = df["rct_p50"] / 1000.0
    df["rct_p90"] = df["rct_p90"] / 1000.0
    df["rct_p95"] = df["rct_p95"] / 1000.0
    
    return df


def plot_boxplots(
    sim_data: dict,
    measured_data: dict,
    experiment_name: str,
    output_path: Path = None,
):
    """
    Create box plots comparing P50, P90, P95 distributions.
    
    Args:
        sim_data: Dict with keys 'p50_all', 'p90_all', 'p95_all' containing lists of values
        measured_data: Dict with keys 'p50_all', 'p90_all', 'p95_all' containing lists of values
        experiment_name: Experiment name for plot title
        output_path: Optional path to save the plot
    """
    # Configure plot style
    configure_plot_style()
    
    # Create figure with half width and double height
    fig, ax = plt.subplots(1, 1, figsize=(FIGURE_WIDTH_INCHES, FIGURE_HEIGHT_INCHES))
    
    # Prepare box plot data
    box_data = []
    box_labels = []
    box_positions = []
    box_colors = []
    percentile_groups = []  # Track percentile groups for custom ticks
    pos = 1
    
    # Store handles for legend
    sim_patch = None
    meas_patch = None
    
    for percentile, label in [("p50", "$p50$"), ("p90", "$p90$"), ("p95", "$p95$")]:
        group_start = pos
        # Simulation data
        if f"{percentile}_all" in sim_data and len(sim_data[f"{percentile}_all"]) > 0:
            box_data.append(sim_data[f"{percentile}_all"])
            box_labels.append("")  # No label, we'll add custom ticks
            box_positions.append(pos)
            box_colors.append(COLOR_SIMULATION)
            pos += 1
        
        # Measured data
        if f"{percentile}_all" in measured_data and len(measured_data[f"{percentile}_all"]) > 0:
            box_data.append(measured_data[f"{percentile}_all"])
            box_labels.append("")  # No label, we'll add custom ticks
            box_positions.append(pos)
            box_colors.append(COLOR_MEASURED)
            pos += 1
        
        # Store the center position for this percentile group
        group_end = pos - 1
        percentile_groups.append((label, (group_start + group_end) / 2))
        
        # Add spacing between percentile groups
        pos += 1
    
    # Create box plot without outliers
    bp = ax.boxplot(box_data, positions=box_positions, labels=box_labels,
                    patch_artist=True, widths=0.6, showfliers=False)
    
    # Color the boxes
    for i, (patch, color) in enumerate(zip(bp['boxes'], box_colors)):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
        # Store first patch of each type for legend
        if color == COLOR_SIMULATION and sim_patch is None:
            sim_patch = patch
        elif color == COLOR_MEASURED and meas_patch is None:
            meas_patch = patch
    
    # Color the other elements to match
    for i, color in enumerate(box_colors):
        bp['medians'][i].set_color('black')
        bp['medians'][i].set_linewidth(1.5)
        bp['whiskers'][i*2].set_color(color)
        bp['whiskers'][i*2+1].set_color(color)
        bp['caps'][i*2].set_color(color)
        bp['caps'][i*2+1].set_color(color)
    
    # Set custom x-axis ticks at the center of each percentile group
    tick_positions = [center for _, center in percentile_groups]
    tick_labels = [label for label, _ in percentile_groups]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels)
    
    # Add legend at the top (higher position)
    if sim_patch and meas_patch:
        fig.legend([sim_patch, meas_patch], ['Simulation', 'Measured'],
                  loc='center', ncol=1, fontsize=FONT_SIZE_LEGEND,
                  bbox_to_anchor=(0.5, 1), frameon=False)
    
    ax.set_ylabel("$rct$ (s)", fontsize=FONT_SIZE_LABEL)
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.subplots_adjust(top=0.88, bottom=0.12, left=0.15, right=0.95)
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches="tight")
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Generate IEEE-formatted box plot comparison"
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
        default="plot_2.pdf",
        help="Output filename for plot (default: plot_2.pdf)",
    )
    parser.add_argument(
        "--t-min",
        type=float,
        default=None,
        help="Minimum time to include (default: use all data)",
    )
    parser.add_argument(
        "--t-max",
        type=float,
        default=None,
        help="Maximum time to include (default: use all data)",
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
    
    # Load simulation data and collect all percentile values
    counter_dfs = []
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
    
    if not counter_dfs:
        raise ValueError("No valid simulation data found")
    
    # Determine time range
    t_min = args.t_min
    t_max = args.t_max
    
    if t_min is None or t_max is None:
        all_t_min = min(df["simTime"].min() for df in counter_dfs)
        all_t_max = min(df["simTime"].max() for df in counter_dfs)
        if t_min is None:
            t_min = all_t_min
        if t_max is None:
            t_max = all_t_max
    
    print(f"\nCollecting percentile values from time range [{t_min:.1f}, {t_max:.1f}]")
    
    # Collect all P50, P90, P95 values from simulation
    sim_data = {
        "p50_all": [],
        "p90_all": [],
        "p95_all": [],
    }
    
    for df in counter_dfs:
        mask = (df["simTime"] >= t_min) & (df["simTime"] <= t_max) & (df["p50"] >= P50_THRESHOLD)
        sim_data["p50_all"].extend(df[mask]["p50"].values)
        sim_data["p90_all"].extend(df[mask]["p90"].values)
        sim_data["p95_all"].extend(df[mask]["p95"].values)
    
    print(f"Collected {len(sim_data['p50_all'])} simulation data points")
    
    # Load measurement data
    measured_data = {
        "p50_all": [],
        "p90_all": [],
        "p95_all": [],
    }
    
    try:
        measurement_files = find_measurement_files(measurements_dir, args.experiment)
        print(f"Found {len(measurement_files)} measurement files")
        
        measured_dfs = []
        for meas_file in measurement_files:
            print(f"Processing measurement: {meas_file.name}")
            try:
                df = load_measurement_data(meas_file, args.deployment)
                measured_dfs.append(df)
            except Exception as e:
                print(f"Warning: Failed to load measurement: {e}")
        
        # Collect all P50, P90, P95 values from measurements
        for df in measured_dfs:
            mask = (df["x"] >= t_min) & (df["x"] <= t_max) & (df["rct_p50"] >= P50_THRESHOLD)
            measured_data["p50_all"].extend(df[mask]["rct_p50"].values)
            measured_data["p90_all"].extend(df[mask]["rct_p90"].values)
            measured_data["p95_all"].extend(df[mask]["rct_p95"].values)
        
        print(f"Collected {len(measured_data['p50_all'])} measurement data points")
        
    except Exception as e:
        print(f"Warning: Failed to find measurements: {e}")
    
    # Generate plot
    output_dir = (repo_root / args.output_dir).resolve()
    output_path = (output_dir / args.output).resolve()
    plot_boxplots(sim_data, measured_data, args.experiment, output_path)
    
    print("\nPlot generation complete!")


if __name__ == "__main__":
    main()
