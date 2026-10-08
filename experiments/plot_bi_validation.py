#!/usr/bin/env python3

"""
Plot BookInfo Validation Metrics: MAE and Avg P50 Difference across services and experiments.
Creates a 1x2 plot showing MAE P50 (ms) and Average P50 Difference (%) for each service,
with different experiments shown as grouped bars.
Formatted for IEEE double-column width.
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

# Import plotting configuration
from plot_config import (
    configure_plot_style,
    FIGURE_WIDTH_INCHES,
    FONT_SIZE_LABEL,
    FONT_SIZE_LEGEND,
    FONT_SIZE_TICK,
    DPI_SAVE,
)

# Adjust figure dimensions
FIGURE_HEIGHT_INCHES = FIGURE_WIDTH_INCHES * 0.4


def load_validation_metrics(csv_path: Path) -> pd.DataFrame:
    """Load validation metrics from CSV file."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Metrics file not found: {csv_path}")
    
    df = pd.read_csv(csv_path, sep='\t')
    return df


def plot_validation_metrics(
    df: pd.DataFrame,
    output_path: Path = None,
):
    """
    Create 1x2 plot comparing MAE P50 and Avg P50 Difference across services and experiments.
    
    Args:
        df: DataFrame with columns: Experiment, Service, MAPE_P50_pct, Avg_P50_Diff_pct, MAE_P50_ms
        output_path: Optional path to save the plot
    """
    # Configure plot style
    configure_plot_style()
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(FIGURE_WIDTH_INCHES, FIGURE_HEIGHT_INCHES))
    
    # Define service order (as specified)
    services_order = ['productpage', 'reviews-v2', 'ratings', 'details']
    
    # Filter to only show experiments 51 and 52
    df = df[df['Experiment'].isin(['EXPERIMENT_51', 'EXPERIMENT_52'])]
    
    # Get unique experiments (sorted)
    experiments = sorted(df['Experiment'].unique())
    
    # Map experiment names to readable labels
    experiment_labels = {
        'EXPERIMENT_51': '60 RPS',
        'EXPERIMENT_52': '80 RPS'
    }
    
    # Define colors for services (matplotlib default colors)
    service_colors = {}
    default_colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
    for i, service in enumerate(services_order):
        service_colors[service] = default_colors[i % len(default_colors)]
    
    # Define hatching patterns for experiments
    # EXPERIMENT_50 gets no hatch, others get different patterns
    hatches = {}
    available_hatches = ['', '///', '...', 'xxx', '+++', '\\\\\\', 'ooo', '***']
    for i, exp in enumerate(experiments):
        if exp == 'EXPERIMENT_50':
            hatches[exp] = ''  # No hatch for EXPERIMENT_50
        else:
            # Assign hatches to other experiments (skip index 0 since it's used for EXPERIMENT_50)
            hatch_idx = min(i, len(available_hatches) - 1)
            hatches[exp] = available_hatches[hatch_idx]
    
    # Width of bars and positions
    bar_width = 0.8 / len(experiments)
    x_pos = np.arange(len(services_order))
    
    # Plot 1: MAE P50 (ms)
    for i, exp in enumerate(experiments):
        exp_data = df[df['Experiment'] == exp]
        values = []
        colors = []
        for service in services_order:
            service_data = exp_data[exp_data['Service'] == service]
            if len(service_data) > 0:
                values.append(service_data['MAE_P50_ms'].values[0])
            else:
                values.append(0)
            colors.append(service_colors[service])
        
        offset = (i - len(experiments)/2 + 0.5) * bar_width
        ax1.bar(x_pos + offset, values, bar_width, label=exp, color=colors, 
                hatch=hatches[exp], edgecolor='black', linewidth=0.5)
    
    ax1.set_title('$rct_{p50}$ MAE (ms)', fontsize=FONT_SIZE_LABEL)
    ax1.set_xlabel('Service', fontsize=FONT_SIZE_LABEL)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels([])  # Remove x-axis labels
    ax1.tick_params(axis='y', labelsize=FONT_SIZE_TICK)
    ax1.grid(True, alpha=0.3, axis='y', linestyle='-', linewidth=0.5)
    ax1.set_axisbelow(True)
    
    # Plot 2: Avg P50 Difference (%)
    for i, exp in enumerate(experiments):
        exp_data = df[df['Experiment'] == exp]
        values = []
        colors = []
        for service in services_order:
            service_data = exp_data[exp_data['Service'] == service]
            if len(service_data) > 0:
                values.append(service_data['Avg_P50_Diff_pct'].values[0])
            else:
                values.append(0)
            colors.append(service_colors[service])
        
        offset = (i - len(experiments)/2 + 0.5) * bar_width
        ax2.bar(x_pos + offset, values, bar_width, label=exp, color=colors,
                hatch=hatches[exp], edgecolor='black', linewidth=0.5)
    
    ax2.set_title('Mean $rct$ rel. error (\\%)', fontsize=FONT_SIZE_LABEL)
    ax2.set_xlabel('Service', fontsize=FONT_SIZE_LABEL)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels([])  # Remove x-axis labels
    ax2.tick_params(axis='y', labelsize=FONT_SIZE_TICK)
    ax2.grid(True, alpha=0.3, axis='y', linestyle='-', linewidth=0.5)
    ax2.set_axisbelow(True)
    
    # Create custom legend handles for services (colored boxes)
    service_handles = [
        mpatches.Patch(facecolor=service_colors[service], edgecolor='black', label=service)
        for service in services_order
    ]
    
    # Create custom legend handles for experiments (with hatching patterns)
    # Use a neutral color (gray) to show just the patterns
    experiment_handles = [
        mpatches.Patch(facecolor='white', hatch=hatches[exp], edgecolor='black', 
                      label=experiment_labels.get(exp, exp))
        for exp in experiments
    ]
    
    # Combine service and experiment handles into one legend
    # Interleave services and experiments
    all_handles = []
    max_len = max(len(service_handles), len(experiment_handles))
    for i in range(max_len):
        if i < len(service_handles):
            all_handles.append(service_handles[i])
        if i < len(experiment_handles):
            all_handles.append(experiment_handles[i])
    
    legend1 = fig.legend(handles=all_handles, loc='center', 
                        ncol=len(services_order), 
                        fontsize=FONT_SIZE_LEGEND,
                        bbox_to_anchor=(0.5, 1.05), frameon=False)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=DPI_SAVE, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Plot BookInfo validation metrics across services and experiments"
    )
    parser.add_argument(
        "--input",
        default="experiments/bi_validation_metrics.csv",
        help="Path to validation metrics CSV file (default: experiments/bi_validation_metrics.csv)",
    )
    parser.add_argument(
        "--output",
        default="experiments/plot_bi_validation.pdf",
        help="Output path for plot (default: experiments/plot_bi_validation.pdf)",
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (repo_root / args.input).resolve()
    
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = (repo_root / args.output).resolve()
    
    print(f"Loading validation metrics from: {input_path}")
    df = load_validation_metrics(input_path)
    print(f"Loaded {len(df)} metric entries")
    print(f"Services: {['productpage', 'reviews-v2', 'ratings', 'details']}")
    print(f"Experiments: {sorted(df['Experiment'].unique())}")
    
    print(f"\nGenerating plot...")
    plot_validation_metrics(df, output_path)
    
    print("\nPlot generation complete!")


if __name__ == "__main__":
    main()
