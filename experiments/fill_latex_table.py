#!/usr/bin/env python3

import argparse
import re
from pathlib import Path

import pandas as pd


def parse_experiment_id(exp_name: str) -> str:
    """
    Convert EXPERIMENT_00 to E-00 format.
    
    Args:
        exp_name: Experiment name like "EXPERIMENT_00"
    
    Returns:
        Formatted experiment ID like "E-00"
    """
    match = re.search(r'EXPERIMENT_(\d+)', exp_name)
    if match:
        num = match.group(1)
        return f"E-{num}"
    return exp_name


def format_value(value, conversion_factor=1.0, decimal_places=2):
    """
    Format a value for LaTeX table.
    
    Args:
        value: The numeric value to format
        conversion_factor: Factor to multiply the value by (e.g., 1000 for s->ms, 100 for fraction->%)
        decimal_places: Number of decimal places
    
    Returns:
        Formatted string, or "0" if value is NaN
    """
    try:
        val = float(value)
        if pd.isna(val):
            return "0"
        converted = val * conversion_factor
        return f"{converted:.{decimal_places}f}"
    except (ValueError, TypeError):
        return "0"


def load_metrics(csv_path: Path) -> dict:
    """
    Load metrics from CSV file.
    
    Args:
        csv_path: Path to final_metrics.csv
    
    Returns:
        Dictionary mapping experiment IDs (E-00 format) to metric values
    """
    df = pd.read_csv(csv_path, sep='\t')
    
    metrics = {}
    for _, row in df.iterrows():
        exp_name = row['Experiment']
        exp_id = parse_experiment_id(exp_name)
        
        metrics[exp_id] = {
            'mae_rct_p50_ms': format_value(row['mae_rct_p50_s'], conversion_factor=1000, decimal_places=2),
            'mae_nr_pods': format_value(row['mae_nr_pods'], decimal_places=2),
            'mae_cpu_util_pct': format_value(row['mae_cpu_util'], conversion_factor=100, decimal_places=2),
            'mean_rct_p50_rel_error': format_value(row['mean_rct_p50_rel_error'], decimal_places=2),
            'delta_pod_minutes_pct': format_value(row['delta_pod_minutes_pct'], decimal_places=2),
        }
    
    return metrics


def fill_template(template_path: Path, metrics: dict, output_path: Path):
    """
    Fill LaTeX template with metrics from CSV.
    
    Args:
        template_path: Path to template .tex file
        metrics: Dictionary of metrics per experiment
        output_path: Path to write filled template
    """
    with open(template_path, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    output_lines = []
    
    for line in lines:
        # Look for lines with experiment IDs (E-00, E-01, etc.)
        match = re.search(r'(E-\d+)', line)
        if match and '--' in line:
            exp_id = match.group(1)
            
            # Check if we have metrics for this experiment
            if exp_id in metrics:
                m = metrics[exp_id]
                
                # Replace the -- placeholders with actual values
                # The line format is:
                # \rownumber & E-XX & Description & -- & -- & -- & -- & -- \\
                parts = line.split('&')
                if len(parts) >= 8:
                    # Keep first 3 parts (row number, exp ID, description)
                    # Replace the 5 metric columns (parts 3-7)
                    # Preserve the trailing \\ from the last part
                    last_part_suffix = parts[7].split('--')[-1] if '--' in parts[7] else parts[7].strip()
                    
                    parts[3] = f" {m['mae_rct_p50_ms']} "
                    parts[4] = f" {m['mae_nr_pods']} "
                    parts[5] = f" {m['mae_cpu_util_pct']} "
                    parts[6] = f" {m['mean_rct_p50_rel_error']} "
                    parts[7] = f" {m['delta_pod_minutes_pct']} {last_part_suffix}"
                    
                    line = '&'.join(parts)
        
        output_lines.append(line)
    
    # Write output
    with open(output_path, 'w') as f:
        f.write('\n'.join(output_lines))
    
    print(f"Filled template written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Fill LaTeX table template with metrics from CSV"
    )
    parser.add_argument(
        "--csv",
        default="final_metrics.csv",
        help="Path to final_metrics.csv (default: final_metrics.csv)",
    )
    parser.add_argument(
        "--template",
        default="single-error.tex",
        help="Path to template .tex file (default: single-error.tex)",
    )
    parser.add_argument(
        "--output",
        default="/Users/razvan/Documents/Research/PhD/Papers/Globecom_2026/content/tables/single-error.tex",
        help="Path to write filled template (default: /Users/razvan/Documents/Research/PhD/Papers/Globecom_2026/content/tables/single-error.tex)",
    )
    
    args = parser.parse_args()
    
    # Resolve paths - script is in experiments/ directory
    script_dir = Path(__file__).resolve().parent
    csv_path = (script_dir / args.csv).resolve() if not Path(args.csv).is_absolute() else Path(args.csv)
    template_path = (script_dir / args.template).resolve() if not Path(args.template).is_absolute() else Path(args.template)
    output_path = (script_dir / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    
    # Validate inputs
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")
    
    # Create output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading metrics from: {csv_path}")
    metrics = load_metrics(csv_path)
    print(f"Loaded metrics for {len(metrics)} experiments")
    
    print(f"Loading template from: {template_path}")
    fill_template(template_path, metrics, output_path)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
