#!/usr/bin/env python3
"""
Plot 4: Simulation Speedup Factor vs Request Rate (Scalability Analysis)

This script plots the average speedup factor (harmonic mean) as a function
of incoming request rates for scalability experiments.
"""

import argparse
import csv
import re
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

# Import plotting configuration
from plot_config import (
    add_latex_argument,
    configure_plot_style,
    set_use_latex,
    FIGURE_WIDTH_INCHES,
    FONT_SIZE_TITLE,
    FONT_SIZE_LABEL,
    FONT_SIZE_TICK,
    FONT_SIZE_LEGEND,
    DPI_SAVE,
)


def load_performance_data(csv_path: Path) -> dict:
    """
    Load simulation performance data from CSV file.
    
    Returns:
        dict: Mapping from experiment name to (avg_speedup, std_speedup)
    """
    data = {}
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            exp_name = row['Experiment']
            avg_speedup = float(row['avg_speedup_factor'])
            std_speedup = float(row['std_speedup_factor'])
            data[exp_name] = (avg_speedup, std_speedup)
    return data


def extract_rps_from_scalability_experiment(exp_name: str) -> int:
    """
    Extract RPS value from SCALABILITY experiment name.
    
    SCALABILITY_0 or SCALABILITY_01 -> 20
    SCALABILITY_1 or SCALABILITY_01 -> 100
    SCALABILITY_2 or SCALABILITY_02 -> 500
    SCALABILITY_3 or SCALABILITY_03 -> 1000
    SCALABILITY_4 or SCALABILITY_04 -> 1500
    SCALABILITY_5 or SCALABILITY_05 -> 2000
    SCALABILITY_6 or SCALABILITY_06 -> 2500
    SCALABILITY_7 or SCALABILITY_07 -> 3000
    SCALABILITY_8 or SCALABILITY_08 -> 3500
    SCALABILITY_9 or SCALABILITY_09 -> 4000
    """
    # Extract the number from the experiment name
    match = re.search(r'SCALABILITY[_-]?(\d+)', exp_name)
    if not match:
        return 0
    
    exp_num = int(match.group(1))
    
    rps_mapping = {
        0: 20, 
        1: 100,
        2: 500,
        3: 1000,
        4: 1500,
        5: 2000,
        6: 2500,
        7: 3000,
        8: 3500,
        9: 4000,
    }
    return rps_mapping.get(exp_num, 0)


def plot_speedup_vs_rps(performance_data: dict, output_path: Path):
    """
    Create line plot of speedup factor vs request rate.
    
    Args:
        performance_data: Dictionary mapping experiment names to (avg, std) tuples
        output_path: Path where to save the plot
    """
    # Configure plotting style
    configure_plot_style()
    
    # Filter and prepare data for scalability experiments
    scalability_data = []
    for exp_name, (avg_speedup, std_speedup) in performance_data.items():
        if exp_name.startswith('SCALABILITY_'):
            rps = extract_rps_from_scalability_experiment(exp_name)
            if rps > 0:
                scalability_data.append((rps, avg_speedup, std_speedup))
    
    # Sort by RPS
    scalability_data.sort(key=lambda x: x[0])
    
    if not scalability_data:
        print("No SCALABILITY experiments found in performance data")
        return
    
    # Extract arrays for plotting
    rps_values = np.array([x[0] for x in scalability_data])
    speedups = np.array([x[1] for x in scalability_data])
    std_devs = np.array([x[2] for x in scalability_data])
    
    # Create figure
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH_INCHES / 2, FIGURE_WIDTH_INCHES * 0.35))
    
    # Plot line and markers first
    line = ax.plot(
        rps_values,
        speedups,
        'o-',                  # Circle markers with line
        color='#1f77b4',       # Blue color
        linewidth=1.5,
        markersize=5,
        label='Single-tier',
        zorder=2
    )[0]
    
    # Plot error bars on top with higher z-order
    ax.errorbar(
        rps_values,
        speedups,
        yerr=std_devs,
        fmt='none',            # No line or markers, just error bars
        capsize=3,
        capthick=1.0,
        ecolor='black',
        elinewidth=1.0,
        zorder=3               # Higher z-order to appear on top
    )
    
    # Set labels and title
    ax.set_xlabel('RPS', fontsize=FONT_SIZE_LABEL)
    ax.set_ylabel('Speedup ($\\times$)', fontsize=FONT_SIZE_LABEL)
    
    # Set y-axis ticks
    ax.set_yticks([0, 10, 20, 30])
    
    # Set tick font sizes
    ax.tick_params(axis='both', which='major', labelsize=FONT_SIZE_TICK)
    
    # Set y-axis range
    ax.set_ylim(0, 30)
    
    # Add grid for better readability
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)
    
    plt.tight_layout()
    
    # Save figure
    plt.savefig(output_path, dpi=DPI_SAVE, bbox_inches='tight')
    print(f"Saved plot to {output_path}")
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Plot simulation speedup factor vs request rate for scalability analysis"
    )
    parser.add_argument(
        '--csv',
        type=Path,
        default=Path('scalability_performance.csv'),
        help='Path to scalability_performance.csv file'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file path (e.g., figures/speedup_vs_rps.pdf)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        help='Output directory (will use default filename: speedup_vs_rps.pdf)'
    )
    
    add_latex_argument(parser)
    args = parser.parse_args()
    set_use_latex(args.latex)
    
    # Determine output path
    if args.output:
        output_path = args.output
    elif args.output_dir:
        output_path = args.output_dir / 'speedup_vs_rps.pdf'
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path('speedup_vs_rps.pdf')
    
    # Load performance data
    if not args.csv.exists():
        print(f"Error: CSV file not found: {args.csv}")
        return 1
    
    performance_data = load_performance_data(args.csv)
    print(f"Loaded performance data for {len(performance_data)} experiments")
    
    # Create plot
    plot_speedup_vs_rps(performance_data, output_path)
    
    return 0


if __name__ == '__main__':
    exit(main())
