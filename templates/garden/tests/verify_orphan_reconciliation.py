#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(repo_root: Path, rel_path: str, name: str):
    sys.path.insert(0, str(repo_root))
    try:
        spec = importlib.util.spec_from_file_location(name, repo_root / rel_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def write_file(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def scaffold_repo(tmp_root: Path):
    for rel in ["runs", "plants", "scripts", "schema", "runner", "tmp"]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    shutil.copy2(REPO_ROOT / "scripts" / "personalagentkit", tmp_root / "scripts" / "personalagentkit")
    shutil.copy2(REPO_ROOT / "scripts" / "dispatch.py", tmp_root / "scripts" / "dispatch.py")
    shutil.copy2(REPO_ROOT / "scripts" / "report", tmp_root / "scripts" / "report")
    shutil.copy2(REPO_ROOT / "schema" / "run.schema.json", tmp_root / "schema" / "run.schema.json")
    shutil.copytree(REPO_ROOT / "runner", tmp_root / "runner", dirs_exist_ok=True)

    for rel in ["scripts/personalagentkit", "scripts/dispatch.py", "scripts/report"]:
        path = tmp_root / rel
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def create_orphan_run(repo_root: Path, run_rel: str):
    run_dir = repo_root / run_rel
    run_dir.mkdir(parents=True, exist_ok=True)

    started_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).replace(microsecond=0)
    meta = {
        "run_id": run_dir.name,
        "goal_file": "goals/000-genesis.md",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": None,
        "status": "running",
        "driver": "codex",
        "model": "gpt-5.4",
        "agent": "gpt-5.4",
        "cost": None,
        "outputs": [],
        "notes": None,
    }
    write_file(run_dir / "meta.json", json.dumps(meta, indent=2) + "\n")
    write_file(
        run_dir / "events.jsonl",
        "\n".join(
            [
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_0",
                            "type": "agent_message",
                            "text": "partial output before the worker disappeared",
                        },
                    }
                ),
            ]
        )
        + "\n",
    )
    write_file(run_dir / "stderr.txt", "")

    old_time = time.time() - 1200
    os.utime(run_dir / "events.jsonl", (old_time, old_time))
    os.utime(run_dir / "meta.json", (old_time, old_time))
    return run_dir


def read_meta(run_dir: Path):
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def verify_status_and_report():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        scaffold_repo(repo_root)

        surveyor_run = create_orphan_run(repo_root, "plants/surveyor/runs/000-genesis")
        status_before = read_meta(surveyor_run)["status"]
        assert_true(status_before == "running", "fixture should start as running")

        status_result = subprocess.run(
            ["./scripts/personalagentkit", "status"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        surveyor_meta = read_meta(surveyor_run)
        assert_true(surveyor_meta["status"] == "killed", "status should reconcile orphaned plant run")
        assert_true(
            surveyor_meta["notes"] == "Reconciled as killed: worker process was gone and the run had no recent event activity.",
            "status should record the orphan note",
        )
        assert_true((surveyor_run / "_stdout.md").exists(), "status reconciliation should recover stdout")
        assert_true("surveyor/000-genesis" in status_result.stdout, "status should list the reconciled plant run")
        assert_true("killed" in status_result.stdout, "status should show killed after reconciliation")

        root_run = create_orphan_run(repo_root, "runs/001-check-report")
        report_result = subprocess.run(
            ["python3", "scripts/report"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        root_meta = read_meta(root_run)
        assert_true(root_meta["status"] == "killed", "report should reconcile orphaned root run")
        assert_true("001-check-report" in report_result.stdout, "report should include the reconciled root run")
        assert_true("killed" in report_result.stdout, "report should show killed after reconciliation")


def verify_dispatch_startup():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        scaffold_repo(repo_root)
        run_dir = create_orphan_run(repo_root, "plants/surveyor/runs/000-genesis")

        dispatch = load_module(repo_root, "scripts/dispatch.py", "dispatch_orphan_verify")
        dispatch.Dispatcher(
            repo_root=repo_root,
            max_workers=1,
            tend_interval=300,
            max_cost=None,
        )

        meta = read_meta(run_dir)
        assert_true(meta["status"] == "killed", "dispatcher startup should reconcile orphaned runs")


def main():
    verify_status_and_report()
    verify_dispatch_startup()
    print("verify_orphan_reconciliation: ok")


if __name__ == "__main__":
    main()
