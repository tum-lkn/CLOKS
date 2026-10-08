#!/usr/bin/env python3

"""
Plot 3: Simulation Performance (Speedup Factors) across experiments.
Creates a bar chart showing the average speedup factor with standard deviation
for each experiment, ordered according to single-error.tex.
"""

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Import plotting configuration
from plot_config import (
    add_latex_argument,
    configure_plot_style,
    label,
    set_use_latex,
    FIGURE_WIDTH_INCHES,
    FONT_SIZE_TITLE,
    FONT_SIZE_LABEL,
    FONT_SIZE_TICK,
    FONT_SIZE_LEGEND,
    DPI_SAVE,
)


def parse_experiment_order(tex_path: Path) -> list[str]:
    """
    Parse single-error.tex to extract experiment IDs in order.
    
    Returns:
        List of experiment IDs (e.g., ['EXPERIMENT_00', 'EXPERIMENT_01', ...])
    """
    with open(tex_path, 'r') as f:
        content = f.read()
    
    # Find all experiment IDs like "E-00", "E-01", etc.
    # Pattern: E-XX where XX is a two-digit number
    pattern = r'E-(\d{2})'
    matches = re.findall(pattern, content)
    
    # Convert to EXPERIMENT_XX format and preserve order
    experiments = []
    seen = set()
    for match in matches:
        exp_name = f"EXPERIMENT_{match}"
        if exp_name not in seen:
            experiments.append(exp_name)
            seen.add(exp_name)
    
    return experiments


def load_performance_data(csv_path: Path) -> pd.DataFrame:
    """
    Load simulation performance data from CSV.
    
    Returns:
        DataFrame with columns: Experiment, avg_speedup_factor, std_speedup_factor
    """
    df = pd.read_csv(csv_path, sep='\t')
    return df


def plot_speedup_factors(
    experiments: list[str],
    perf_data: pd.DataFrame,
    output_path: Path = None,
):
    """
    Create bar chart of speedup factors with error bars.
    
    Args:
        experiments: List of experiment names in desired order
        perf_data: DataFrame with performance metrics
        output_path: Optional path to save the plot
    """
    # Filter and reorder data according to experiments list
    # Create a mapping for quick lookup
    perf_dict = {}
    for _, row in perf_data.iterrows():
        perf_dict[row['Experiment']] = {
            'avg_speedup': row['avg_speedup_factor'],
            'std_speedup': row['std_speedup_factor'],
        }
    
    # Build data arrays in the correct order
    speedups = []
    std_devs = []
    labels = []
    
    for exp in experiments:
        if exp in perf_dict:
            speedups.append(perf_dict[exp]['avg_speedup'])
            std_devs.append(perf_dict[exp]['std_speedup'])
            # Convert EXPERIMENT_XX to E-XX for labels
            exp_num = exp.split('_')[-1]
            labels.append(f"E-{exp_num}")
        else:
            # Experiment not found in performance data
            speedups.append(0)
            std_devs.append(0)
            exp_num = exp.split('_')[-1]
            labels.append(f"E-{exp_num}")
    
    # Create figure
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_INCHES / 2, FIGURE_WIDTH_INCHES * 0.35))
    
    # Create bar chart
    x_pos = np.arange(len(experiments))
    bars = ax.bar(
        x_pos,
        speedups,
        yerr=std_devs,
        capsize=1.5,
        color='#1f77b4',
        alpha=0.8,
        edgecolor='black',
        linewidth=0.8,
        error_kw={'linewidth': 0.8, 'ecolor': 'black'},
        label='Single-tier'
    )
    
    # Customize plot
    ax.set_xlabel(label('Experiment \#'), fontsize=FONT_SIZE_LABEL)
    ax.set_ylabel('Speedup ($\\times$)', fontsize=FONT_SIZE_LABEL)
    
    # Set x-axis ticks to show only 1, 5, 10, 15, etc. (1-indexed positions)
    tick_positions = [0, 1, 2, 3, 4, 5, 6, 7, 9, 14]  # 0-indexed positions for 1st, 5th, 10th, 15th experiments
    tick_positions = [p for p in tick_positions if p < len(experiments)]
    tick_labels = [str(p + 1) for p in tick_positions]  # Convert to 1-indexed: 1, 5, 10, 15
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, fontsize=FONT_SIZE_TICK)
    
    # Set y-axis ticks
    ax.set_yticks([0, 500, 1000])
    ax.tick_params(axis='y', labelsize=FONT_SIZE_TICK)
    ax.grid(True, alpha=0.3, axis='y', linestyle='-', linewidth=0.5)
    # ax.set_axisbelow(False)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=DPI_SAVE, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Plot simulation performance (speedup factors) across experiments"
    )
    parser.add_argument(
        "--tex-file",
        default="single-error.tex",
        help="Path to single-error.tex file (default: experiments/single-error.tex)",
    )
    parser.add_argument(
        "--csv-file",
        default="sim_performance.csv",
        help="Path to sim_performance.csv file (default: experiments/sim_performance.csv)",
    )
    parser.add_argument(
        "--output",
        help="Output file path for plot (optional)",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for plot (optional, uses default filename: speedup_factors.pdf)",
    )
    
    add_latex_argument(parser)
    args = parser.parse_args()
    set_use_latex(args.latex)
    
    # Configure plot style
    configure_plot_style()
    
    # Resolve paths
    cwd = Path(__file__).resolve().parent
    tex_path = (cwd / args.tex_file).resolve()
    csv_path = (cwd / args.csv_file).resolve()
    
    # Check files exist
    if not tex_path.exists():
        raise FileNotFoundError(f"LaTeX file not found: {tex_path}")
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    print(f"Reading experiment order from: {tex_path}")
    experiments = parse_experiment_order(tex_path)
    print(f"Found {len(experiments)} experiments: {', '.join(experiments)}")
    
    print(f"\nReading performance data from: {csv_path}")
    perf_data = load_performance_data(csv_path)
    print(f"Loaded performance data for {len(perf_data)} experiments")
    
    # Determine output path
    output_path = None
    if args.output:
        output_path = Path(args.output).resolve()
    elif args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "speedup_factors.pdf"
    print(f"\nGenerating plot...")
    plot_speedup_factors(experiments, perf_data, output_path)
    
    print("\nPlot generation complete!")


if __name__ == "__main__":
    main()
