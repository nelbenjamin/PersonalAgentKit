from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from runner.reflection import load_meta, normalize_status, reflection_required_for_run


def run_age_secs(meta: dict, run_dir: Path):
    started_at = meta.get("started_at")
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except ValueError:
            pass
    try:
        return time.time() - run_dir.stat().st_mtime
    except OSError:
        return None


def get_pending_goals(plant_dir: Path) -> list[str]:
    goals_dir = plant_dir / "goals"
    runs_dir = plant_dir / "runs"
    if not goals_dir.is_dir():
        return []
    run_prefixes = set()
    if runs_dir.is_dir():
        for run_dir in runs_dir.iterdir():
            if run_dir.is_dir():
                run_prefixes.add(run_dir.name[:3])
    pending = []
    for goal_file in sorted(goals_dir.glob("*.md")):
        if goal_file.stem[:3] not in run_prefixes:
            pending.append(goal_file.stem)
    return pending


def iter_scoped_run_dirs(repo_root: Path):
    runs_dir = repo_root / "runs"
    if runs_dir.is_dir():
        for run_dir in sorted(runs_dir.iterdir()):
            if run_dir.is_dir():
                yield f"root/{run_dir.name}", run_dir

    plants_dir = repo_root / "plants"
    if not plants_dir.is_dir():
        return
    for plant_dir in sorted(plants_dir.iterdir()):
        runs_dir = plant_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            if run_dir.is_dir():
                yield f"{plant_dir.name}/{run_dir.name}", run_dir


def get_health_issues(repo_root: Path, *, stale_threshold_secs: int):
    missing_reflections = []
    stale_runs = []
    active_runs = []

    for scope, run_dir in iter_scoped_run_dirs(repo_root):
        meta = load_meta(run_dir)
        if meta is None:
            continue

        status = normalize_status(meta.get("status"))
        if status == "running":
            age = run_age_secs(meta, run_dir)
            if age is None or age > stale_threshold_secs:
                stale_runs.append(scope)
            else:
                active_runs.append(scope)
            continue

        if reflection_required_for_run(run_dir, status) and not (run_dir / "reflection.md").exists():
            missing_reflections.append(scope)

    pending_by_plant = {}
    plants_dir = repo_root / "plants"
    if plants_dir.is_dir():
        for plant_dir in sorted(plants_dir.iterdir()):
            count = len(get_pending_goals(plant_dir))
            if count > 0:
                pending_by_plant[plant_dir.name] = count

    return missing_reflections, stale_runs, active_runs, pending_by_plant
