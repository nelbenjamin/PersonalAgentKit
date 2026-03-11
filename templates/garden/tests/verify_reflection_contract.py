#!/usr/bin/env python3
import json
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_file(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def scaffold_repo(tmp_root: Path):
    for rel in ["runs", "plants/worker/runs", "plants/worker/goals", "scripts", "schema", "runner"]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    write_file(tmp_root / "MOTIVATION.md", "# Motivation\n")
    write_file(tmp_root / "plants" / "worker" / "MOTIVATION.md", "# Worker Motivation\n")

    shutil.copy2(REPO_ROOT / "scripts" / "personalagentkit", tmp_root / "scripts" / "personalagentkit")
    shutil.copy2(REPO_ROOT / "scripts" / "report", tmp_root / "scripts" / "report")
    shutil.copy2(REPO_ROOT / "schema" / "run.schema.json", tmp_root / "schema" / "run.schema.json")
    shutil.copytree(REPO_ROOT / "runner", tmp_root / "runner", dirs_exist_ok=True)

    for rel in ["scripts/personalagentkit", "scripts/report"]:
        path = tmp_root / rel
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def create_run(
    repo_root: Path,
    run_rel: str,
    *,
    goal_file: str,
    status: str,
    goal_type: str | None,
    requires_reflection: bool | None,
    with_reflection: bool,
):
    run_dir = repo_root / run_rel
    run_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    meta = {
        "run_id": run_dir.name,
        "goal_file": goal_file,
        "started_at": now,
        "completed_at": now,
        "status": status,
        "driver": "codex",
        "model": "gpt-5.4",
        "agent": "gpt-5.4",
        "cost": {
            "input_tokens": 1,
            "output_tokens": 1,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "actual_usd": 0.01,
            "estimated_usd": None,
            "pricing": {
                "source": "provider-native",
                "provider": "openai",
                "model": "gpt-5.4",
                "version": None,
                "retrieved_at": None,
                "notes": None,
            },
        },
        "outputs": ["reflection.md"] if with_reflection else [],
        "num_turns": 1,
        "duration_ms": 1000,
        "notes": None,
    }
    if goal_type is not None:
        meta["goal_type"] = goal_type
    if requires_reflection is not None:
        meta["requires_reflection"] = requires_reflection

    write_file(run_dir / "meta.json", json.dumps(meta, indent=2) + "\n")
    write_file(run_dir / "_stdout.md", "output\n")
    write_file(run_dir / "stderr.txt", "")
    if with_reflection:
        write_file(run_dir / "reflection.md", "# Reflection\n")


def assert_contains(text: str, needle: str, message: str):
    if needle not in text:
        raise AssertionError(f"{message}: missing {needle!r}")


def assert_not_contains(text: str, needle: str, message: str):
    if needle in text:
        raise AssertionError(f"{message}: found unexpected {needle!r}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        repo_root = Path(tmp)
        scaffold_repo(repo_root)

        create_run(
            repo_root,
            "runs/001-legacy-build",
            goal_file="goals/001-legacy-build.md",
            status="success",
            goal_type=None,
            requires_reflection=None,
            with_reflection=False,
        )
        create_run(
            repo_root,
            "plants/worker/runs/002-fix-contract",
            goal_file="goals/002-fix-contract.md",
            status="success",
            goal_type="fix",
            requires_reflection=True,
            with_reflection=False,
        )
        create_run(
            repo_root,
            "plants/worker/runs/003-tend-ok",
            goal_file="goals/003-tend.md",
            status="success",
            goal_type="tend",
            requires_reflection=True,
            with_reflection=True,
        )
        create_run(
            repo_root,
            "runs/004-genesis-ok",
            goal_file="goals/004-genesis.md",
            status="success",
            goal_type="genesis",
            requires_reflection=False,
            with_reflection=False,
        )
        create_run(
            repo_root,
            "runs/005-verification-build",
            goal_file="goals/005-verification-build.md",
            status="success",
            goal_type="build",
            requires_reflection=True,
            with_reflection=True,
        )

        status_result = subprocess.run(
            ["./scripts/personalagentkit", "status"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        report_result = subprocess.run(
            ["python3", "scripts/report"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )

        required_issue = "worker/002-fix-contract  missing reflection"
        legacy_issue = "001-legacy-build  missing reflection"
        exempt_issue = "004-genesis-ok  missing reflection"
        verification_issue = "005-verification-build  missing reflection"

        assert_contains(status_result.stdout, required_issue, "status should report explicit reflection violations")
        assert_contains(report_result.stdout, required_issue, "report should report explicit reflection violations")
        assert_not_contains(status_result.stdout, legacy_issue, "status should not flag legacy runs with unspecified contract")
        assert_not_contains(report_result.stdout, legacy_issue, "report should not flag legacy runs with unspecified contract")
        assert_not_contains(status_result.stdout, exempt_issue, "status should not flag exempt runs")
        assert_not_contains(report_result.stdout, exempt_issue, "report should not flag exempt runs")
        assert_not_contains(status_result.stdout, verification_issue, "status should not flag verification harness runs that wrote reflection.md")
        assert_not_contains(report_result.stdout, verification_issue, "report should not flag verification harness runs that wrote reflection.md")

    print("verify_reflection_contract: ok")


if __name__ == "__main__":
    main()
