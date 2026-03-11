#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(repo_root: Path, rel_path: str, name: str):
    import sys

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
    for rel in ["runs", "plants", "scripts", "schema", "runner", "goals", "tmp", "plugins"]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    write_file(tmp_root / "MOTIVATION.md", "# Motivation\n")
    write_file(tmp_root / "goals" / "001-resume-reporting.md", "# Resume reporting fixture\n")

    shutil.copy2(REPO_ROOT / "scripts" / "personalagentkit", tmp_root / "scripts" / "personalagentkit")
    shutil.copy2(REPO_ROOT / "scripts" / "report", tmp_root / "scripts" / "report")
    shutil.copy2(REPO_ROOT / "schema" / "run.schema.json", tmp_root / "schema" / "run.schema.json")
    shutil.copytree(REPO_ROOT / "runner", tmp_root / "runner", dirs_exist_ok=True)

    for rel in ["scripts/personalagentkit", "scripts/report"]:
        path = tmp_root / rel
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    subprocess.run(["git", "init"], cwd=tmp_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=tmp_root, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_root, check=True, capture_output=True, text=True)


def create_fake_driver(plugin_dir: Path, script_path: Path):
    plugin = """from __future__ import annotations

import json
import os
from typing import Any, Mapping

from runner.plugin_api import DriverConfig


class FakeDriver:
    config = DriverConfig(name="fake", binary="python3", default_model="fake-model")

    def build_command(self, *, model: str) -> list[str]:
        return [os.environ["FAKE_DRIVER_BIN"], model]

    def prepare_env(self, env: Mapping[str, str]) -> dict[str, str]:
        return dict(env)

    def parse_events(self, *, events: list[dict[str, Any]], model: str) -> dict[str, Any]:
        turn_events = [event for event in events if event.get("type") == "turn.completed"]
        input_tokens = sum(int((event.get("usage") or {}).get("input_tokens", 0) or 0) for event in turn_events)
        output_tokens = sum(int((event.get("usage") or {}).get("output_tokens", 0) or 0) for event in turn_events)
        duration_ms = sum(int(event.get("duration_ms", 0) or 0) for event in turn_events) or None
        output = "no output"
        for event in reversed(events):
            item = event.get("item")
            if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                output = item.get("text") or "no output"
                break
        return {
            "output": output,
            "cost": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "actual_usd": round((input_tokens + output_tokens) / 100.0, 4),
                "estimated_usd": None,
                "pricing": {
                    "source": "provider-native",
                    "provider": self.config.name,
                    "model": model,
                    "version": "fake-v1",
                    "retrieved_at": None,
                    "notes": None,
                },
            },
            "num_turns": len(turn_events),
            "duration_ms": duration_ms,
        }


PLUGIN = FakeDriver()
"""
    driver = """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path


state_path = Path(os.environ["FAKE_DRIVER_STATE_FILE"])
count = 0
if state_path.exists():
    count = int(state_path.read_text(encoding="utf-8").strip() or "0")
count += 1
state_path.write_text(str(count), encoding="utf-8")

if count == 1:
    print(json.dumps({"type": "item.completed", "item": {"id": "msg1", "type": "agent_message", "text": "attempt one partial"}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}, "duration_ms": 1000}))
    sys.stdout.flush()
    time.sleep(float(os.environ.get("FAKE_DRIVER_FIRST_SLEEP", "2")))
else:
    print(json.dumps({"type": "item.completed", "item": {"id": "msg2", "type": "agent_message", "text": "attempt two final"}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 5}, "duration_ms": 2000}))
    sys.stdout.flush()
"""
    write_file(plugin_dir / "fake_driver.py", plugin)
    write_file(script_path, driver, executable=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def assert_contains(text: str, needle: str, message: str):
    if needle not in text:
        raise AssertionError(f"{message}: missing {needle!r}")


def create_unresumable_orphan_run(repo_root: Path, run_id: str):
    run_dir = repo_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).replace(microsecond=0)
    meta = {
        "run_id": run_id,
        "goal_file": "goals/001-resume-reporting.md",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": None,
        "status": "running",
        "driver": "fake",
        "model": "fake-model",
        "agent": "fake-model",
        "cost": None,
        "outputs": [],
        "notes": None,
    }
    write_file(run_dir / "meta.json", json.dumps(meta, indent=2) + "\n")
    write_file(
        run_dir / "events.jsonl",
        json.dumps({"type": "item.completed", "item": {"id": "orphan", "type": "agent_message", "text": "partial"}}) + "\n",
    )
    write_file(run_dir / "stderr.txt", "")
    old_time = time.time() - 1200
    os_utime = __import__("os").utime
    os_utime(run_dir / "meta.json", (old_time, old_time))
    os_utime(run_dir / "events.jsonl", (old_time, old_time))
    return run_dir


def verify_cumulative_resume_reporting():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        scaffold_repo(repo_root)
        create_fake_driver(repo_root / "plugins", repo_root / "tmp" / "fake-driver")
        env = {
            **os.environ,
            "PAK_DRIVER_PLUGIN_PATH": str(repo_root / "plugins"),
            "PAK_DRIVER": "fake",
            "PAK_MODEL": "fake-model",
            "PAK_IDLE_TIMEOUT": "1",
            "FAKE_DRIVER_BIN": str(repo_root / "tmp" / "fake-driver"),
            "FAKE_DRIVER_STATE_FILE": str(repo_root / "tmp" / "driver-state.txt"),
            "FAKE_DRIVER_FIRST_SLEEP": "2",
        }

        subprocess.run(
            ["./scripts/personalagentkit", "run", "goals/001-resume-reporting.md"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        run_dir = repo_root / "runs" / "001-resume-reporting"
        killed_meta = read_json(run_dir / "meta.json")
        assert_true(killed_meta["status"] == "killed", "first attempt should end killed")
        assert_true(killed_meta["cost"]["actual_usd"] == 0.15, "first attempt cost should be recorded before resume")

        resume_result = subprocess.run(
            ["./scripts/personalagentkit", "resume-run", "001-resume-reporting"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        meta = read_json(run_dir / "meta.json")
        assert_true(meta["status"] == "success", "resumed run should finish successfully")
        assert_true(meta["completed_attempts"] == 2, "completed_attempts should count archived + final attempt")
        assert_true(meta["cost"]["actual_usd"] == 0.4, "run cost should be cumulative across attempts")
        assert_true(meta["num_turns"] == 2, "run turns should be cumulative across attempts")
        assert_true(meta["duration_ms"] == 3000, "run duration should be cumulative across attempts")
        assert_true(meta["last_attempt_cost"]["actual_usd"] == 0.25, "last_attempt_cost should preserve final-attempt spend")
        assert_true(meta["last_attempt_num_turns"] == 1, "last_attempt_num_turns should describe only the resumed attempt")
        assert_true(meta["last_attempt_duration_ms"] == 2000, "last_attempt_duration_ms should describe only the resumed attempt")
        assert_true((run_dir / "attempts" / "attempt-01" / "meta.json").exists(), "prior attempt metadata should be archived")
        assert_contains((run_dir / "resume.md").read_text(encoding="utf-8"), "Cumulative cost after resumption: 0.4 USD", "resume.md should disclose cumulative cost")
        assert_contains(resume_result.stdout, "resumed run 001-resume-reporting as attempt 02", "resume-run should report the resumed attempt number")

        report_result = subprocess.run(
            ["python3", "scripts/report"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert_contains(report_result.stdout, "001-resume-reporting", "report should include the resumed run")
        assert_contains(report_result.stdout, "$0.4000", "report should display cumulative run cost")
        assert_contains(report_result.stdout, "    2", "report should display cumulative turns")
        assert_contains(report_result.stdout, "    3s", "report should display cumulative duration")


def verify_resume_eligibility_consistency():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        scaffold_repo(repo_root)
        create_fake_driver(repo_root / "plugins", repo_root / "tmp" / "fake-driver")
        env = {
            **os.environ,
            "PAK_DRIVER_PLUGIN_PATH": str(repo_root / "plugins"),
            "PAK_DRIVER": "fake",
            "PAK_MODEL": "fake-model",
            "FAKE_DRIVER_BIN": str(repo_root / "tmp" / "fake-driver"),
            "FAKE_DRIVER_STATE_FILE": str(repo_root / "tmp" / "driver-state.txt"),
        }
        run_dir = create_unresumable_orphan_run(repo_root, "002-no-prompt")
        os.environ["PAK_DRIVER_PLUGIN_PATH"] = str(repo_root / "plugins")
        reconcile = load_module(repo_root, "runner/reconcile.py", "reconcile_resume_reporting")
        result = reconcile.reconcile_run(run_dir)
        assert_true(result is not None, "orphaned run should be reconciled")
        assert_true(result["status"] == "killed", "reconciled orphan should be killed")
        assert_true(result["recoverable"] is False, "reconciliation should not claim resumability without a prompt artifact")
        checkpoint_text = (run_dir / "checkpoint.jsonl").read_text(encoding="utf-8")
        assert_contains(checkpoint_text, '"event": "resume_unavailable"', "checkpoint should record why resume is unavailable")
        assert_true('"event": "ready_to_resume"' not in checkpoint_text, "checkpoint should not advertise ready_to_resume without a prompt artifact")

        resume_result = subprocess.run(
            ["./scripts/personalagentkit", "resume-run", "002-no-prompt"],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
        )
        assert_true(resume_result.returncode != 0, "resume-run should still refuse runs without a prompt artifact")
        assert_contains(resume_result.stderr, "cannot resume run without an existing attempt prompt artifact", "CLI refusal should match reconciliation metadata")


def main():
    verify_cumulative_resume_reporting()
    verify_resume_eligibility_consistency()
    print("verify_resume_reporting: ok")


if __name__ == "__main__":
    main()
