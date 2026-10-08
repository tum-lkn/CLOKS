#!/usr/bin/env python3

import argparse
import copy
import csv
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml



def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def save_yaml(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def expand_matrix(matrix: dict) -> list:
    if not matrix:
        return [{}]

    keys = list(matrix.keys())
    values = []
    for key in keys:
        v = matrix[key]
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError(f"Matrix key '{key}' must be a non-empty list")
        values.append(v)

    combinations = []
    for row in itertools.product(*values):
        item = {}
        for i, key in enumerate(keys):
            item[key] = row[i]
        combinations.append(item)
    return combinations


def get_git_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def apply_top_level_overrides(sim_cfg: dict, fixed: dict, params: dict):
    selectors = ["infra", "requests", "services", "hpa", "exporter"]
    for key in selectors:
        if key in fixed:
            sim_cfg[key] = fixed[key]
        if key in params:
            sim_cfg[key] = params[key]

    if "seed" in fixed:
        sim_cfg["seed"] = int(fixed["seed"])
    if "seed" in params:
        sim_cfg["seed"] = int(params["seed"])


def mutate_services_config(path: Path, params: dict):
    data = load_yaml(path)
    services = data.get("services", [])
    if not isinstance(services, list):
        raise ValueError(f"Invalid services configuration in {path}")

    min_global = params.get("min_replicas")
    max_global = params.get("max_replicas")
    cpu_request_global = params.get("cpu_request")
    cpu_limit_global = params.get("cpu_limit")
    cpu_num_workers_global = params.get("cpu_num_workers")
    request_duration_global = params.get("request_duration")
    min_by_service = params.get("min_replicas_by_service", {})
    max_by_service = params.get("max_replicas_by_service", {})
    cpu_request_by_service = params.get("cpu_request_by_service", {})
    cpu_limit_by_service = params.get("cpu_limit_by_service", {})
    cpu_num_workers_by_service = params.get("cpu_num_workers_by_service", {})
    request_duration_by_service = params.get("request_duration_by_service", {})

    if min_global is not None:
        min_global = int(min_global)
    if max_global is not None:
        max_global = int(max_global)
    if cpu_request_global is not None:
        cpu_request_global = int(cpu_request_global)
    if cpu_limit_global is not None:
        cpu_limit_global = int(cpu_limit_global)
    if cpu_num_workers_global is not None:
        cpu_num_workers_global = int(cpu_num_workers_global)
    if request_duration_global is not None:
        request_duration_global = int(request_duration_global)

    for svc in services:
        name = svc.get("name", "")

        if min_global is not None:
            svc["min_replicas"] = min_global
        if max_global is not None:
            svc["max_replicas"] = max_global
        if cpu_request_global is not None:
            svc["cpu_request"] = cpu_request_global
        if cpu_limit_global is not None:
            svc["cpu_limit"] = cpu_limit_global
        if cpu_num_workers_global is not None:
            svc["cpu_num_workers"] = cpu_num_workers_global

        if isinstance(min_by_service, dict) and name in min_by_service:
            svc["min_replicas"] = int(min_by_service[name])
        if isinstance(max_by_service, dict) and name in max_by_service:
            svc["max_replicas"] = int(max_by_service[name])
        if isinstance(cpu_request_by_service, dict) and name in cpu_request_by_service:
            svc["cpu_request"] = int(cpu_request_by_service[name])
        if isinstance(cpu_limit_by_service, dict) and name in cpu_limit_by_service:
            svc["cpu_limit"] = int(cpu_limit_by_service[name])
        if isinstance(cpu_num_workers_by_service, dict) and name in cpu_num_workers_by_service:
            svc["cpu_num_workers"] = int(cpu_num_workers_by_service[name])

        # Update request_duration in all request_profiles
        request_duration_for_service = None
        if request_duration_global is not None:
            request_duration_for_service = request_duration_global
        if isinstance(request_duration_by_service, dict) and name in request_duration_by_service:
            request_duration_for_service = int(request_duration_by_service[name])
        
        if request_duration_for_service is not None:
            profiles = svc.get("request_profiles", [])
            if isinstance(profiles, list):
                for profile in profiles:
                    profile["request_duration"] = request_duration_for_service

        min_rep = int(svc.get("min_replicas", 0))
        max_rep = int(svc.get("max_replicas", 0))
        cpu_request = int(svc.get("cpu_request", 0))
        cpu_limit = int(svc.get("cpu_limit", 0))

        if min_rep > max_rep:
            raise ValueError(
                f"Invalid replicas for service '{name}' in {path}: min_replicas={min_rep} > max_replicas={max_rep}"
            )
        if cpu_request <= 0 or cpu_limit <= 0:
            raise ValueError(
                f"Invalid CPU values for service '{name}' in {path}: cpu_request={cpu_request}, cpu_limit={cpu_limit}"
            )
        if cpu_request > cpu_limit:
            raise ValueError(
                f"Invalid CPU values for service '{name}' in {path}: cpu_request={cpu_request} > cpu_limit={cpu_limit}"
            )

    save_yaml(path, data)


def mutate_hpa_config(path: Path, params: dict):
    data = load_yaml(path)
    hpa_items = data.get("hpa", [])
    if not isinstance(hpa_items, list):
        raise ValueError(f"Invalid hpa configuration in {path}")

    threshold_global = params.get("hpa_threshold")
    threshold_by_service = params.get("hpa_threshold_by_service", {})

    if threshold_global is not None:
        threshold_global = float(threshold_global)

    for item in hpa_items:
        service_name = item.get("service_name", "")

        if threshold_global is not None:
            item["threshold"] = threshold_global

        if isinstance(threshold_by_service, dict) and service_name in threshold_by_service:
            item["threshold"] = float(threshold_by_service[service_name])

    save_yaml(path, data)


def build_run_id(batch_stamp: str, batch_name: str, run_index: int, params: dict) -> str:
    h = short_hash(params)
    return f"{batch_stamp}_{batch_name}_{run_index:04d}_{h}"


def run_single(
    repo_root: Path,
    batch_stamp: str,
    run_index: int,
    batch_name: str,
    base_conf_dir: Path,
    base_sim_cfg_path: Path,
    binary_path: Path,
    output_root: Path,
    fixed: dict,
    params: dict,
    git_commit: str,
):
    effective_params = copy.deepcopy(params)
    run_id = build_run_id(batch_stamp, batch_name, run_index, effective_params)
    run_dir = output_root / run_id
    run_conf_dir = run_dir / "conf"

    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copytree(base_conf_dir, run_conf_dir, dirs_exist_ok=True)

    sim_cfg_path = run_conf_dir / base_sim_cfg_path.name
    sim_cfg = load_yaml(sim_cfg_path)
    apply_top_level_overrides(sim_cfg, fixed, effective_params)
    save_yaml(sim_cfg_path, sim_cfg)

    services_file = run_conf_dir / "services" / sim_cfg["services"]
    hpa_file = run_conf_dir / "hpa" / sim_cfg["hpa"]

    if not services_file.exists():
        raise FileNotFoundError(f"Services file does not exist: {services_file}")
    if not hpa_file.exists():
        raise FileNotFoundError(f"HPA file does not exist: {hpa_file}")

    mutate_services_config(services_file, effective_params)
    mutate_hpa_config(hpa_file, effective_params)

    metadata = {
        "run_id": run_id,
        "batch": batch_name,
        "created_at": now_utc_iso(),
        "status": "running",
        "git_commit": git_commit,
        "base_config": str(base_sim_cfg_path),
        "effective_params": effective_params,
        "paths": {
            "run_dir": str(run_dir),
            "config": str(sim_cfg_path),
            "services_config": str(services_file),
            "hpa_config": str(hpa_file),
            "log": str(run_dir / "app.log"),
            "stdout": str(run_dir / "stdout.log"),
            "stderr": str(run_dir / "stderr.log"),
        },
    }

    metadata_path = run_dir / "metadata.json"
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    cmd = [str(binary_path), "-config", str(sim_cfg_path), "-log", str(run_dir / "app.log")]

    start = time.time()
    with (run_dir / "stdout.log").open("w", encoding="utf-8") as out, (run_dir / "stderr.log").open(
        "w", encoding="utf-8"
    ) as err:
        result = subprocess.run(cmd, cwd=repo_root, stdout=out, stderr=err)
    duration_sec = round(time.time() - start, 3)

    metadata["completed_at"] = now_utc_iso()
    metadata["duration_sec"] = duration_sec
    metadata["exit_code"] = int(result.returncode)
    metadata["status"] = "success" if result.returncode == 0 else "failed"

    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return {
        "run_id": run_id,
        "status": metadata["status"],
        "exit_code": metadata["exit_code"],
        "duration_sec": duration_sec,
        "run_dir": str(run_dir),
    }


def maybe_build(repo_root: Path):
    result = subprocess.run(["make", "build"], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError("Build failed")


def compute_runs(matrix_rows: list, repeats: int, seeds_cfg: dict, fixed: dict) -> list:
    def config_identity(payload: dict) -> str:
        # Seed/repeat only distinguish repetitions; they do not define a new configuration.
        filtered = {k: v for k, v in payload.items() if k not in {"seed", "repeat"}}
        return json.dumps(filtered, sort_keys=True, separators=(",", ":"))

    runs = []
    config_index_by_identity = {}
    seed_idx_by_identity = {}
    seed_mode = seeds_cfg.get("mode", "none")
    seed_start = int(seeds_cfg.get("start", 42))

    for row in matrix_rows:
        identity = config_identity(row)
        if identity not in config_index_by_identity:
            config_index_by_identity[identity] = len(config_index_by_identity)
        if identity not in seed_idx_by_identity:
            seed_idx_by_identity[identity] = 0
        config_index = config_index_by_identity[identity]

        for repeat in range(repeats):
            params = copy.deepcopy(row)
            params["repeat"] = repeat

            if "seed" not in fixed and "seed" not in params:
                if seed_mode == "increment":
                    params["seed"] = seed_start + seed_idx_by_identity[identity]
                    seed_idx_by_identity[identity] += 1
                elif seed_mode == "fixed":
                    params["seed"] = seed_start

            runs.append({"config_index": config_index, "params": params})
    return runs


def write_batch_summary(output_root: Path, batch_name: str, rows: list):
    summary_json = output_root / f"{batch_name}_summary.json"
    summary_csv = output_root / f"{batch_name}_summary.csv"

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    fieldnames = ["run_id", "status", "exit_code", "duration_sec", "run_dir"]
    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Batch experiment runner for network-simulator")
    parser.add_argument(
        "--experiment",
        required=True,
        help="Path to experiment definition YAML",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run make build before starting experiments",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Expand and print run combinations without executing",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    exp_path = (repo_root / args.experiment).resolve() if not os.path.isabs(args.experiment) else Path(args.experiment)
    if not exp_path.exists():
        raise FileNotFoundError(f"Experiment file not found: {exp_path}")

    exp = load_yaml(exp_path)

    batch_name = exp.get("name", exp_path.stem)
    base_config_rel = exp.get("base_config", "conf/simulation.yaml")
    binary_rel = exp.get("binary", "./network-simulator")
    output_root_rel = exp.get("output_root", "experiments/runs")
    concurrency = int(exp.get("concurrency", 1))
    repeats = int(exp.get("repeats", 1))

    fixed = exp.get("fixed", {}) or {}
    matrix = exp.get("matrix", {}) or {}
    seeds_cfg = exp.get("seeds", {}) or {}

    base_sim_cfg_path = (repo_root / base_config_rel).resolve()
    if not base_sim_cfg_path.exists():
        raise FileNotFoundError(f"Base simulation config does not exist: {base_sim_cfg_path}")

    base_conf_dir = base_sim_cfg_path.parent
    binary_path = (repo_root / binary_rel).resolve() if not os.path.isabs(binary_rel) else Path(binary_rel)
    output_root = (repo_root / output_root_rel).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    matrix_rows = expand_matrix(matrix)
    runs = compute_runs(matrix_rows, repeats, seeds_cfg, fixed)

    print(f"Batch name: {batch_name}")
    print(f"Total runs: {len(runs)}")
    print(f"Concurrency: {concurrency}")
    print(f"Output root: {output_root}")

    if args.dry_run:
        for run in runs:
            print(f"[{run['config_index']}] {json.dumps(run['params'], sort_keys=True)}")
        return

    if args.build:
        maybe_build(repo_root)

    if not binary_path.exists():
        raise FileNotFoundError(f"Simulator binary not found: {binary_path}")

    git_commit = get_git_commit(repo_root)
    batch_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for run in runs:
            futures.append(
                pool.submit(
                    run_single,
                    repo_root,
                    batch_stamp,
                    run["config_index"],
                    batch_name,
                    base_conf_dir,
                    base_sim_cfg_path,
                    binary_path,
                    output_root,
                    fixed,
                    run["params"],
                    git_commit,
                )
            )

        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            print(f"[{row['status']}] {row['run_id']} ({row['duration_sec']}s)")

    results.sort(key=lambda x: x["run_id"])
    write_batch_summary(output_root, batch_name, results)

    total = len(results)
    ok = len([r for r in results if r["status"] == "success"])
    failed = total - ok
    print(f"Completed batch: total={total}, success={ok}, failed={failed}")
    print(f"Summary: {output_root / (batch_name + '_summary.json')}")
    print(f"Summary: {output_root / (batch_name + '_summary.csv')}")


if __name__ == "__main__":
    main()
