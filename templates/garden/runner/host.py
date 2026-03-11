from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner.plugin_api import DriverPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_DRIVER_DIR = REPO_ROOT / "runner" / "drivers"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_module(path: Path):
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    module_name = f"runner_dynamic_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load driver module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugin(path: Path) -> DriverPlugin:
    module = load_module(path)
    plugin = getattr(module, "PLUGIN", None)
    if plugin is None and hasattr(module, "get_plugin"):
        plugin = module.get_plugin()
    if plugin is None or not hasattr(plugin, "config"):
        raise RuntimeError(f"driver module does not expose PLUGIN/get_plugin with config: {path}")
    return plugin


def iter_driver_files() -> list[tuple[Path, bool]]:
    files: list[tuple[Path, bool]] = []
    seen: set[Path] = set()
    search_dirs: list[tuple[Path, bool]] = [(BUILTIN_DRIVER_DIR, True)]
    plugin_path = os.environ.get("PAK_DRIVER_PLUGIN_PATH", "")
    for raw_entry in plugin_path.split(os.pathsep):
        entry = raw_entry.strip()
        if entry:
            search_dirs.append((Path(entry), False))

    for directory, is_builtin in search_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*_driver.py")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append((resolved, is_builtin))
    return files


def discover_plugins() -> tuple[dict[str, DriverPlugin], list[str]]:
    plugins: dict[str, DriverPlugin] = {}
    plugin_sources: dict[str, Path] = {}
    warnings: list[str] = []
    for path, is_builtin in iter_driver_files():
        try:
            plugin = load_plugin(path)
        except Exception as exc:
            if is_builtin:
                raise
            warnings.append(f"skipping external driver plugin {path}: {exc}")
            continue

        name = plugin.config.name
        existing = plugin_sources.get(name)
        if existing is not None:
            if is_builtin:
                raise RuntimeError(f"duplicate built-in driver name {name!r}: {existing} and {path}")
            warnings.append(
                f"skipping external driver plugin {path}: duplicate driver name {name!r} already provided by {existing}"
            )
            continue

        plugins[name] = plugin
        plugin_sources[name] = path
    return plugins, warnings


def available_plugins() -> dict[str, DriverPlugin]:
    plugins, warnings = discover_plugins()
    for warning in warnings:
        print(f"runner.host: WARNING: {warning}", file=sys.stderr)
    return plugins


def parse_iso8601(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_completion_time(*, run_dir: Path, completed_at: str | None) -> str | None:
    if completed_at:
        return completed_at

    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    meta_completed_at = data.get("completed_at")
    if isinstance(meta_completed_at, str) and meta_completed_at:
        return meta_completed_at
    return None


def derive_duration_ms(*, run_dir: Path, completed_at: str | None) -> int | None:
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    started_at = parse_iso8601(data.get("started_at"))
    ended_at = parse_iso8601(completed_at or data.get("completed_at"))
    if started_at is None or ended_at is None:
        return None
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def resolve_driver(*, requested_driver: str | None, requested_model: str | None) -> dict[str, str]:
    plugins = available_plugins()
    driver_name = requested_driver or os.environ.get("PAK_DRIVER") or "claude"
    plugin = plugins.get(driver_name)
    if plugin is None:
        supported = ", ".join(sorted(plugins))
        raise SystemExit(f"unknown driver: {driver_name} (supported: {supported})")

    model = requested_model or os.environ.get("PAK_MODEL") or plugin.config.default_model
    return {
        "driver": plugin.config.name,
        "model": model,
        "binary": plugin.config.binary,
        "agent": model or plugin.config.name,
    }


def parse_events(events_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not events_path.exists():
        return events
    for line in events_path.read_text().splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def has_terminal_event(events: list[dict[str, Any]]) -> bool:
    for event in reversed(events):
        event_type = event.get("type")
        if event_type in {"watchdog_killed", "result", "turn.completed"}:
            return True
    return False


def enrich_normalized_result(result: dict[str, Any]) -> dict[str, Any]:
    cost = dict(result.get("cost") or {})
    pricing = dict(cost.get("pricing") or {})
    pricing.setdefault("source", "provider-native")
    pricing.setdefault("provider", None)
    pricing.setdefault("model", None)
    pricing.setdefault("version", None)
    pricing.setdefault("retrieved_at", None)
    pricing.setdefault("notes", None)
    if pricing["source"] == "local-estimate" and pricing["retrieved_at"] is None:
        pricing["retrieved_at"] = utc_now_iso()
    cost = {
        "input_tokens": int(cost.get("input_tokens", 0) or 0),
        "output_tokens": int(cost.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(cost.get("cache_read_tokens", 0) or 0),
        "cache_write_tokens": int(cost.get("cache_write_tokens", 0) or 0),
        "actual_usd": cost.get("actual_usd"),
        "estimated_usd": cost.get("estimated_usd"),
        "pricing": pricing,
    }
    return {
        "output": result.get("output") or "no output",
        "cost": cost,
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
    }


def write_run_output(*, run_dir: Path, output: str) -> Path:
    output_path = run_dir / "_stdout.md"
    output_path.write_text(f"{output}\n", encoding="utf-8")
    return output_path


def classify_goal_type(*, run_dir: Path) -> str:
    meta_path = run_dir / "meta.json"
    slug = run_dir.name
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        goal_file = data.get("goal_file")
        if isinstance(goal_file, str) and goal_file:
            slug = Path(goal_file).stem

    normalized_slug = slug.lower()
    normalized_slug = re.sub(r"^\d+[-_]+", "", normalized_slug)
    tokens = [token for token in re.split(r"[-_]+", normalized_slug) if token]
    if not tokens:
        return "build"

    first_token = tokens[0]
    last_token = tokens[-1]

    if first_token == "integrate":
        return "integrate"
    if first_token == "retrospective":
        return "retrospective"
    if first_token == "tend":
        return "tend"
    if first_token == "genesis":
        return "genesis"
    if first_token == "dispatch":
        return "dispatch"
    if first_token == "review":
        return "review"
    if first_token == "spike" or last_token == "spike":
        return "spike"
    if first_token == "fix":
        return "fix"
    return "build"


def reflection_required(*, run_dir: Path, status: str) -> bool:
    return status == "success" and classify_goal_type(run_dir=run_dir) in {"build", "fix", "review"}


def ensure_reflection_artifact(*, run_dir: Path, status: str, output: str) -> str | None:
    if not reflection_required(run_dir=run_dir, status=status):
        return None

    reflection_path = run_dir / "reflection.md"
    if reflection_path.is_file():
        return None

    print(f"personalagentkit: WARNING: reflection.md missing from {run_dir.name}", file=sys.stderr, flush=True)
    return None


def update_run_meta(*, run_dir: Path, normalized: dict[str, Any], completed_at: str | None = None) -> None:
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["completed_at"] = data.get("completed_at") or completed_at or utc_now_iso()
    data["status"] = normalized["status"]
    data["cost"] = normalized["cost"]
    data["num_turns"] = normalized["num_turns"]
    data["duration_ms"] = normalized["duration_ms"]
    if "notes" in normalized:
        data["notes"] = normalized["notes"]

    outputs = []
    if (run_dir / "reflection.md").is_file():
        outputs.append("reflection.md")
    data["outputs"] = outputs

    data.pop("zombie_cleaned_at", None)
    data.pop("zombie_note", None)
    meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def finalize_run_artifacts(
    *,
    driver: str,
    model: str,
    run_dir: Path,
    exit_code: int | None = None,
    watchdog_killed: bool = False,
    completed_at: str | None = None,
) -> dict[str, Any]:
    plugins = available_plugins()
    plugin = plugins.get(driver)
    if plugin is None:
        supported = ", ".join(sorted(plugins))
        raise SystemExit(f"unknown driver: {driver} (supported: {supported})")

    events_path = run_dir / "events.jsonl"
    events = parse_events(events_path)
    normalized = enrich_normalized_result(plugin.parse_events(events=events, model=model))

    if watchdog_killed or any(event.get("type") == "watchdog_killed" for event in events):
        status = "killed"
    elif exit_code is not None:
        status = "success" if exit_code == 0 else "failure"
    elif has_terminal_event(events):
        status = "success"
    else:
        status = "running"

    resolved_completed_at = completed_at
    if status != "running":
        resolved_completed_at = resolve_completion_time(run_dir=run_dir, completed_at=completed_at) or utc_now_iso()
        if normalized["duration_ms"] is None:
            normalized["duration_ms"] = derive_duration_ms(run_dir=run_dir, completed_at=resolved_completed_at)

    output_path = write_run_output(run_dir=run_dir, output=normalized["output"])
    normalized.update(
        {
            "status": status,
            "driver": plugin.config.name,
            "model": model,
            "binary": plugin.config.binary,
            "output_path": str(output_path),
            "events_path": str(events_path),
            "stderr_path": str(run_dir / "stderr.txt"),
        }
    )

    ensure_reflection_artifact(run_dir=run_dir, status=status, output=normalized["output"])

    if normalized["status"] != "running":
        update_run_meta(run_dir=run_dir, normalized=normalized, completed_at=resolved_completed_at)

    return normalized


def run_with_watchdog(
    *,
    command: list[str],
    prompt: str,
    env: dict[str, str],
    cwd: Path,
    events_path: Path,
    stderr_path: Path,
    idle_timeout: int,
) -> tuple[int, bool]:
    poll_interval = 1.0
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as events_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=events_handle,
            stderr=stderr_handle,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()

        last_size = events_path.stat().st_size if events_path.exists() else 0
        last_change = time.monotonic()
        watchdog_killed = False

        while True:
            exit_code = process.poll()
            current_size = events_path.stat().st_size if events_path.exists() else 0
            if current_size != last_size:
                last_size = current_size
                last_change = time.monotonic()

            if exit_code is not None:
                return exit_code, watchdog_killed

            if time.monotonic() - last_change >= idle_timeout:
                watchdog_killed = True
                events_handle.write('{"type":"watchdog_killed","reason":"no events for %ss"}\n' % idle_timeout)
                events_handle.flush()
                process.terminate()
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    exit_code = process.wait()
                return exit_code, watchdog_killed

            time.sleep(poll_interval)


def invoke_driver(*, driver: str, model: str, run_dir: Path, prompt: str, idle_timeout: int) -> dict[str, Any]:
    plugins = available_plugins()
    plugin = plugins.get(driver)
    if plugin is None:
        supported = ", ".join(sorted(plugins))
        raise SystemExit(f"unknown driver: {driver} (supported: {supported})")

    command = plugin.build_command(model=model)
    env = plugin.prepare_env(os.environ.copy())
    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.txt"

    exit_code, watchdog_killed = run_with_watchdog(
        command=command,
        prompt=prompt,
        env=env,
        cwd=REPO_ROOT,
        events_path=events_path,
        stderr_path=stderr_path,
        idle_timeout=idle_timeout,
    )
    return finalize_run_artifacts(
        driver=driver,
        model=model,
        run_dir=run_dir,
        exit_code=exit_code,
        watchdog_killed=watchdog_killed,
        completed_at=utc_now_iso(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PersonalAgentKit driver host")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--driver", default=None)
    resolve_parser.add_argument("--model", default=None)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    invoke_parser = subparsers.add_parser("invoke")
    invoke_parser.add_argument("--driver", required=True)
    invoke_parser.add_argument("--model", required=True)
    invoke_parser.add_argument("--run-dir", required=True)
    invoke_parser.add_argument("--idle-timeout", type=int, default=600)

    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--driver", required=True)
    recover_parser.add_argument("--model", required=True)
    recover_parser.add_argument("--run-dir", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "resolve":
        print(json.dumps(resolve_driver(requested_driver=args.driver, requested_model=args.model)))
        return 0

    if args.command == "list":
        payload = [
            {
                "driver": plugin.config.name,
                "binary": plugin.config.binary,
                "default_model": plugin.config.default_model,
            }
            for plugin in available_plugins().values()
        ]
        if args.json:
            print(json.dumps(sorted(payload, key=lambda item: item["driver"])))
        else:
            for item in sorted(payload, key=lambda item: item["driver"]):
                print(f"{item['driver']}\t{item['binary']}\t{item['default_model']}")
        return 0

    if args.command == "invoke":
        prompt = sys.stdin.read()
        result = invoke_driver(
            driver=args.driver,
            model=args.model,
            run_dir=Path(args.run_dir),
            prompt=prompt,
            idle_timeout=args.idle_timeout,
        )
        print(json.dumps(result))
        return 0

    if args.command == "recover":
        result = finalize_run_artifacts(
            driver=args.driver,
            model=args.model,
            run_dir=Path(args.run_dir),
        )
        result["recoverable"] = result["status"] != "running"
        print(json.dumps(result))
        return 0

    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
