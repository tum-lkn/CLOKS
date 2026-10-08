import json
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go


# ============================================================================
# Simulation Data Helpers
# ============================================================================

def _filter_events(file_path, field, value):
    """Generic event filter for JSON log files."""
    filtered_events = []
    with open(file_path, "r") as file:
        for line in file:
            try:
                event = json.loads(line)
                if event.get(field) == value:
                    filtered_events.append(event)
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(filtered_events)


def filter_events_by_tag(file_path, tag_name):
    """Filter events by tag field."""
    return _filter_events(file_path, "tag", tag_name)


def filter_events_by_message(file_path, message_name):
    """Filter events by msg field."""
    return _filter_events(file_path, "msg", message_name)


def load_counter_df(log_path: Path) -> pd.DataFrame:
    """Parse CounterEvent lines from simulator log into DataFrame with derived RPS column."""
    raw = "\n".join(
        line for line in Path(log_path).read_text().splitlines()
        if '"msg":"*events.CounterEvent"' in line
    )
    df = pd.read_json(StringIO(raw), lines=True)
    for col in ["simTime", "p50", "p90", "p95", "podsRunning", "nrReq", "statsTime"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["simTime", "p50", "podsRunning"]).sort_values("simTime")
    df["rps"] = df["nrReq"] / (df["simTime"] - df["statsTime"])
    return df


def load_hpa_df(log_path: Path, deployment_name: str = "burn-cpu") -> pd.DataFrame:
    """Parse HPAEvent lines from simulator log, extracting CPU utilization."""
    rows = []
    for line in Path(log_path).read_text().splitlines():
        if '"msg":"*events.HPAEvent"' not in line:
            continue
        try:
            event = json.loads(line)
            if event.get("deploymentName") == deployment_name and event.get("meanCpuUtilization") is not None:
                rows.append({"simTime": float(event["simTime"]), "cpu_avg": float(event["meanCpuUtilization"])})
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return pd.DataFrame(rows).sort_values("simTime")


# ============================================================================
# Experiment Data Helpers
# ============================================================================

def normalize_measurement(
    df: pd.DataFrame,
    time_col: str = "timestamp",
    rct_col: str = "rct_p50_unknown_TO_burn-cpu",
    pods_col: str = "nr_pods_burn-cpu",
    rps_col: str = "rps_unknown_TO_burn-cpu",
) -> pd.DataFrame:
    """Convert measurement CSV with absolute timestamps to elapsed-seconds form."""
    df = df.copy()
    time = pd.to_datetime(df[time_col])
    df["x"] = (time - time.iloc[0]).dt.total_seconds()
    rename_map = {rct_col: "rct", pods_col: "pods"}
    if rps_col in df.columns:
        rename_map[rps_col] = "rps"
    return df.rename(columns=rename_map).sort_values("x")


def compute_mae(counter_df: pd.DataFrame, measured: pd.DataFrame, t_start: float = 100) -> float:
    """
    Compute MAE between simulated p50 and measured RCT (in seconds).
    Measured RCT is interpolated onto simulator time grid over common time window.
    
    Returns MAE in seconds and prints summary.
    """
    sim_time, sim_p50 = counter_df["simTime"].to_numpy(), counter_df["p50"].to_numpy()
    rct_time, rct_vals = measured["x"].to_numpy(), (measured["rct"] / 1000).to_numpy()
    
    t_min = max(sim_time.min(), rct_time.min(), t_start)
    t_max = min(sim_time.max(), rct_time.max())
    
    mask = (sim_time >= t_min) & (sim_time <= t_max)
    sim_time_common, sim_p50_common = sim_time[mask], sim_p50[mask]
    
    rct_interp = np.interp(sim_time_common, rct_time, rct_vals)
    mae = float(np.mean(np.abs(sim_p50_common - rct_interp)))
    print(f"MAE: {mae:.6f} s  ({mae * 1000:.3f} ms)")
    return mae


# ============================================================================
# Plotting Functions
# ============================================================================


def plot_dual_axis(counter_df: pd.DataFrame, measured: pd.DataFrame | None, title: str = "") -> go.Figure:
    """Overlay sim vs measured p50 RCT (left axis) and pod count (right axis)."""
    fig = go.Figure()
    
    # RCT traces (left axis)
    fig.add_trace(go.Scatter(
        x=counter_df["simTime"], y=counter_df["p50"],
        mode="lines", name="sim p50", yaxis="y1", line=dict(color="#1f77b4"),
    ))
    if measured is not None:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured["rct"] / 1000,
            mode="lines", name="measured p50", yaxis="y1", line=dict(color="#d62728"),
        ))
    
    # Pod count traces (right axis)
    fig.add_trace(go.Scatter(
        x=counter_df["simTime"], y=counter_df["podsRunning"],
        mode="lines", name="sim pods", yaxis="y2", line=dict(color="#1f77b4", dash="dot"),
    ))
    if measured is not None:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured["pods"],
            mode="lines", name="measured pods", yaxis="y2", line=dict(color="#d62728", dash="dot"),
        ))
    
    fig.update_layout(
        title=title, xaxis_title="simTime",
        yaxis=dict(title="p50 RCT (s)"),
        yaxis2=dict(title="nr pods", overlaying="y", side="right"),
        template="plotly_white", legend=dict(x=1.08),
    )
    return fig


def plot_rct(counter_df: pd.DataFrame, measured: pd.DataFrame | None, title: str = "Median RCT over simTime") -> go.Figure:
    """Line chart of simulated and measured p50 RCT."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=counter_df["simTime"], y=counter_df["p50"],
        mode="lines", name="sim p50", line=dict(color="#1f77b4"),
    ))
    if measured is not None:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured["rct"] / 1000,
            mode="lines", name="measured p50", line=dict(color="#d62728"),
        ))
    fig.update_layout(
        title=title, xaxis_title="simTime", yaxis_title="p50 (s)", template="plotly_white",
    )
    return fig


def plot_pods(counter_df: pd.DataFrame, measured: pd.DataFrame | None, title: str = "Pod Count over simTime") -> go.Figure:
    """Line chart of simulated and measured pod count."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=counter_df["simTime"], y=counter_df["podsRunning"],
        mode="lines", name="sim pods", line=dict(color="#1f77b4"),
    ))
    if measured is not None:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured["pods"],
            mode="lines", name="measured pods", line=dict(color="#d62728"),
        ))
    fig.update_layout(
        title=title, xaxis_title="simTime", yaxis_title="nr pods", template="plotly_white",
    )
    return fig


def plot_rps(counter_df: pd.DataFrame, measured: pd.DataFrame | None, title: str = "Requests Per Second over simTime") -> go.Figure:
    """Line chart of simulated and measured RPS."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=counter_df["simTime"], y=counter_df["rps"],
        mode="lines", name="sim rps", line=dict(color="#1f77b4"),
    ))
    if measured is not None:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured["rps"],
            mode="lines", name="measured rps", line=dict(color="#d62728"),
        ))
    fig.update_layout(
        title=title, xaxis_title="simTime", yaxis_title="rps", template="plotly_white",
    )
    return fig


def plot_hpa_cpu(
    log_path: Path,
    measured: pd.DataFrame | None,
    deployment_name: str = "burn-cpu",
    hpa_metric_col: str = "hpa_target_metric_burn-cpu",
    title: str = "HPA CPU metric: sim vs measured",
) -> go.Figure:
    """Plot HPA CPU metric from simulation vs measurement."""
    hpa_df = load_hpa_df(log_path, deployment_name)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hpa_df["simTime"], y=hpa_df["cpu_avg"],
        mode="lines", name="sim avg CPU load", line=dict(color="#1f77b4"),
    ))
    if measured is not None and hpa_metric_col in measured.columns:
        fig.add_trace(go.Scatter(
            x=measured["x"], y=measured[hpa_metric_col] / 100,
            mode="lines", name="measured HPA metric", line=dict(color="#d62728"),
        ))
    fig.update_layout(
        title=title, xaxis_title="simTime", yaxis_title="CPU utilisation", template="plotly_white",
    )
    return fig
