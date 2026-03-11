from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.host import recover_run


DEFAULT_ORPHAN_IDLE_TIMEOUT = 600
ORPHANED_RUN_NOTE = (
    "Reconciled as killed: worker process was gone and the run had no recent event activity."
)


def normalize_status(status: Any) -> Any:
    if status == "completed":
        return "success"
    if status == "failed":
        return "failure"
    return status


def iter_run_dirs(repo_root: Path):
    root_runs = repo_root / "runs"
    if root_runs.is_dir():
        for run_dir in sorted(root_runs.iterdir()):
            if run_dir.is_dir():
                yield run_dir

    plants_dir = repo_root / "plants"
    if not plants_dir.is_dir():
        return
    for plant_dir in sorted(plants_dir.iterdir()):
        runs_dir = plant_dir / "runs"
        if not runs_dir.is_dir():
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            if run_dir.is_dir():
                yield run_dir


def load_meta(run_dir: Path) -> dict[str, Any] | None:
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_age_seconds(meta: dict[str, Any]) -> float | None:
    started_at = meta.get("started_at")
    if not isinstance(started_at, str) or not started_at:
        return None
    try:
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - started_dt).total_seconds()


def has_recent_event_activity(run_dir: Path, *, idle_timeout: int = DEFAULT_ORPHAN_IDLE_TIMEOUT) -> bool:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        return False
    try:
        return (time.time() - events_path.stat().st_mtime) < idle_timeout
    except OSError:
        return False


def is_orphaned_run(run_dir: Path, meta: dict[str, Any], *, idle_timeout: int = DEFAULT_ORPHAN_IDLE_TIMEOUT) -> bool:
    if normalize_status(meta.get("status")) != "running":
        return False
    age = run_age_seconds(meta)
    if age is not None and age < idle_timeout:
        return False
    return not has_recent_event_activity(run_dir, idle_timeout=idle_timeout)


def reconcile_run(run_dir: Path, *, idle_timeout: int = DEFAULT_ORPHAN_IDLE_TIMEOUT) -> dict[str, Any] | None:
    meta = load_meta(run_dir)
    if meta is None or not is_orphaned_run(run_dir, meta, idle_timeout=idle_timeout):
        return None

    driver = meta.get("driver")
    model = meta.get("model")
    if not isinstance(driver, str) or not driver or not isinstance(model, str) or not model:
        return None

    result = recover_run(
        driver=driver,
        model=model,
        run_dir=run_dir,
        finalize_orphaned=True,
        orphaned_note=ORPHANED_RUN_NOTE,
    )
    return {
        "run_dir": str(run_dir),
        "run_id": meta.get("run_id", run_dir.name),
        "status": result.get("status"),
        "recoverable": bool(result.get("recoverable")),
    }


def reconcile_orphaned_runs(repo_root: Path, *, idle_timeout: int = DEFAULT_ORPHAN_IDLE_TIMEOUT) -> list[dict[str, Any]]:
    reconciled: list[dict[str, Any]] = []
    for run_dir in iter_run_dirs(repo_root):
        result = reconcile_run(run_dir, idle_timeout=idle_timeout)
        if result is not None:
            reconciled.append(result)
    return reconciled


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile orphaned PersonalAgentKit runs")
    parser.add_argument("--root", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--idle-timeout", type=int, default=DEFAULT_ORPHAN_IDLE_TIMEOUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.root).resolve()
    print(
        json.dumps(
            reconcile_orphaned_runs(repo_root, idle_timeout=args.idle_timeout),
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
