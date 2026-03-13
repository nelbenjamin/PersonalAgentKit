#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_command(cmd, cwd: Path, env: dict, check: bool = True):
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=check, env=env)


def write_file(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def scaffold_repo(tmp_root: Path):
    for rel in [
        "goals",
        "runs",
        "memory",
        "seeds",
        "scripts",
        "schema",
        "plants/worker/runs",
        "plants/worker/memory",
    ]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    write_file(tmp_root / "MOTIVATION.md", "# Motivation\n")
    write_file(tmp_root / "memory" / "MEMORY.md", "# Memory\n")
    write_file(tmp_root / "plants" / "worker" / "MOTIVATION.md", "# Worker Motivation\n")
    write_file(tmp_root / "plants" / "worker" / "memory" / "MEMORY.md", "# Worker Memory\n")

    shutil.copy2(REPO_ROOT / "scripts" / "personalagentkit", tmp_root / "scripts" / "personalagentkit")
    shutil.copy2(REPO_ROOT / "scripts" / "dispatch.py", tmp_root / "scripts" / "dispatch.py")
    shutil.copy2(REPO_ROOT / "schema" / "run.schema.json", tmp_root / "schema" / "run.schema.json")
    shutil.copytree(REPO_ROOT / "runner", tmp_root / "runner")

    (tmp_root / "scripts" / "personalagentkit").chmod(
        (tmp_root / "scripts" / "personalagentkit").stat().st_mode | stat.S_IXUSR
    )

    subprocess.run(["git", "init"], cwd=tmp_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "Driver Routing Test"],
        cwd=tmp_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "driver-routing@example.com"],
        cwd=tmp_root,
        check=True,
        capture_output=True,
        text=True,
    )


def install_fake_binaries(bin_dir: Path):
    write_file(
        bin_dir / "claude",
        """#!/usr/bin/env python3
import json
import sys

model = ""
if "--model" in sys.argv:
    model = sys.argv[sys.argv.index("--model") + 1]
_ = sys.stdin.read()
print(json.dumps({
    "type": "result",
    "result": f"claude:{model}",
    "usage": {
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0
    },
    "total_cost_usd": 0.1234,
    "num_turns": 1,
    "duration_ms": 42
}, separators=(",", ":")))
""",
        executable=True,
    )
    write_file(
        bin_dir / "codex",
        """#!/usr/bin/env python3
import json
import sys

_ = sys.stdin.read()
print(json.dumps({
    "type": "turn.completed",
    "usage": {
        "input_tokens": 20,
        "output_tokens": 5,
        "cached_input_tokens": 2
    }
}, separators=(",", ":")))
print(json.dumps({
    "type": "item.completed",
    "item": {
        "id": "item_1",
        "type": "agent_message",
        "text": "codex:ok"
    }
}, separators=(",", ":")))
""",
        executable=True,
    )
    write_file(
        bin_dir / "reverse-agent",
        """#!/usr/bin/env python3
import json
import sys

model = ""
if "--model" in sys.argv:
    model = sys.argv[sys.argv.index("--model") + 1]
prompt = sys.stdin.read().strip()
print(json.dumps({
    "type": "result",
    "result": f"reverse:{model}:{prompt[::-1]}",
    "usage": {
        "input_tokens": 3,
        "output_tokens": 2,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0
    },
    "total_cost_usd": 0.3333,
    "num_turns": 1,
    "duration_ms": 9
}, separators=(",", ":")))
""",
        executable=True,
    )


def install_plugin(plugin_dir: Path):
    write_file(
        plugin_dir / "reverse_driver.py",
        """from runner.plugin_api import DriverConfig


class ReverseDriver:
    config = DriverConfig(name="reverse", binary="reverse-agent", default_model="reverse-default")

    def build_command(self, *, model: str) -> list[str]:
        return [self.config.binary, "--model", model]

    def prepare_env(self, env):
        return dict(env)

    def parse_events(self, *, events, model: str):
        result_event = next((event for event in reversed(events) if event.get("type") == "result"), {})
        usage = result_event.get("usage") or {}
        return {
            "output": result_event.get("result") or "no output",
            "cost": {
                "input_tokens": int(usage.get("input_tokens", 0) or 0),
                "output_tokens": int(usage.get("output_tokens", 0) or 0),
                "cache_read_tokens": int(usage.get("cache_read_input_tokens", 0) or 0),
                "cache_write_tokens": int(usage.get("cache_creation_input_tokens", 0) or 0),
                "actual_usd": result_event.get("total_cost_usd"),
                "estimated_usd": None,
                "pricing": {
                    "source": "provider-native",
                    "provider": "reverse",
                    "model": model,
                    "version": None,
                    "retrieved_at": None,
                    "notes": None,
                },
            },
            "num_turns": result_event.get("num_turns"),
            "duration_ms": result_event.get("duration_ms"),
        }

    def normalize_transcript(self, *, events):
        return []


PLUGIN = ReverseDriver()
""",
    )


def install_bad_plugin(plugin_dir: Path):
    write_file(
        plugin_dir / "bad_driver.py",
        """raise RuntimeError("boom")
""",
    )


def install_duplicate_plugin(plugin_dir: Path):
    write_file(
        plugin_dir / "codex_override_driver.py",
        """from runner.plugin_api import DriverConfig


class CodexOverrideDriver:
    config = DriverConfig(name="codex", binary="codex-override", default_model="override-model")

    def build_command(self, *, model: str) -> list[str]:
        return [self.config.binary, "--model", model]

    def prepare_env(self, env):
        return dict(env)

    def parse_events(self, *, events, model: str):
        return {
            "output": "override",
            "cost": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "actual_usd": 0.0,
                "estimated_usd": None,
                "pricing": {
                    "source": "provider-native",
                    "provider": "codex-override",
                    "model": model,
                    "version": None,
                    "retrieved_at": None,
                    "notes": None,
                },
            },
            "num_turns": 1,
            "duration_ms": 1,
        }

    def normalize_transcript(self, *, events):
        return []


PLUGIN = CodexOverrideDriver()
""",
    )


def write_completed_claude_meta(run_dir: Path):
    write_file(
        run_dir / "meta.json",
        json.dumps(
            {
                "run_id": "037-spike-live-claude-transcript-sample",
                "goal_file": "goals/037-spike-live-claude-transcript-sample.md",
                "started_at": "2026-03-13T00:30:11Z",
                "completed_at": "2026-03-13T00:30:28Z",
                "status": "success",
                "driver": "claude",
                "model": "claude-sonnet-4-6",
                "agent": "claude-sonnet-4-6",
                "goal_type": "spike",
                "requires_reflection": False,
                "cost": {
                    "input_tokens": 5,
                    "output_tokens": 334,
                    "cache_read_tokens": 39319,
                    "cache_write_tokens": 10676,
                    "actual_usd": 0.056855699999999995,
                    "estimated_usd": None,
                    "pricing": {
                        "source": "provider-native",
                        "provider": "claude",
                        "model": "claude-sonnet-4-6",
                        "version": None,
                        "retrieved_at": None,
                        "notes": None,
                    },
                },
                "outputs": [],
                "notes": None,
                "num_turns": 3,
                "duration_ms": 14155,
            },
            indent=2,
        )
        + "\n",
    )
    write_file(
        run_dir / "_stdout.md",
        "Done. The `DriverPlugin` protocol has three methods: `build_command`, `prepare_env`, and `parse_events`.\n",
    )
    fixture_events = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "claude-run-037-events.jsonl"
    )
    write_file(run_dir / "events.jsonl", fixture_events.read_text())
    write_file(run_dir / "stderr.txt", "")


def main():
    schema = json.loads((REPO_ROOT / "schema" / "run.schema.json").read_text())
    assert "driver" in schema["properties"]
    assert "model" in schema["properties"]

    dispatch = load_module(REPO_ROOT / "scripts" / "dispatch.py", "dispatch_driver_verify")

    with tempfile.TemporaryDirectory() as tmp:
      tmp_root = Path(tmp)
      scaffold_repo(tmp_root)

      bin_dir = tmp_root / "bin"
      bin_dir.mkdir()
      install_fake_binaries(bin_dir)

      env = os.environ.copy()
      env["PATH"] = f"{bin_dir}:{env['PATH']}"
      env["PAK_DRIVER"] = "claude"
      env.pop("PAK_MODEL", None)
      env.pop("PAK_ACTIVE_RUN_ID", None)
      env.pop("PAK_ACTIVE_RUN_DIR", None)
      env.pop("PAK_ACTIVE_DRIVER", None)

      write_file(tmp_root / "goals" / "001-unrouted.md", "# Goal\n\nUnrouted.\n")
      run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "run", "goals/001-unrouted.md"],
          tmp_root,
          env,
      )
      unrouted_meta = json.loads((tmp_root / "runs" / "001-unrouted" / "meta.json").read_text())
      assert unrouted_meta["driver"] == "claude"
      assert unrouted_meta["model"] == "claude-sonnet-4-6"
      assert unrouted_meta["agent"] == "claude-sonnet-4-6"
      assert unrouted_meta["status"] == "success"

      write_file(
          tmp_root / "goals" / "002-routed.md",
          """---
driver: codex
model: codex-mini-latest
---
# Goal

Frontmatter routed.
""",
      )
      routed_run = run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "run", "goals/002-routed.md"],
          tmp_root,
          env,
      )
      routed_meta = json.loads((tmp_root / "runs" / "002-routed" / "meta.json").read_text())
      routed_output = (tmp_root / "runs" / "002-routed" / "_stdout.md").read_text().strip()
      assert routed_meta["driver"] == "codex"
      assert routed_meta["model"] == "codex-mini-latest"
      assert routed_meta["agent"] == "codex-mini-latest"
      assert routed_meta["cost"]["actual_usd"] is None
      assert routed_meta["cost"]["estimated_usd"] is not None
      assert isinstance(routed_meta["duration_ms"], int)
      assert routed_meta["duration_ms"] >= 0
      assert routed_output == "codex:ok"
      assert "duration_ms: missing or not an integer" not in routed_run.stderr

      write_file(
          tmp_root / "seeds" / "starter.md",
          "# Starter Seed\n\nBuild from defaults.\n",
      )
      env["PAK_DRIVER"] = "codex"
      env["PAK_MODEL"] = "codex-default-from-env"
      run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "plant", "starter", "sprout"],
          tmp_root,
          env,
      )
      genesis_meta = json.loads(
          (tmp_root / "plants" / "sprout" / "runs" / "000-genesis" / "meta.json").read_text()
      )
      genesis_output = (
          tmp_root / "plants" / "sprout" / "runs" / "000-genesis" / "_stdout.md"
      ).read_text().strip()
      assert genesis_meta["driver"] == "codex"
      assert genesis_meta["model"] == "codex-default-from-env"
      assert genesis_meta["agent"] == "codex-default-from-env"
      assert genesis_output == "codex:ok"

      write_file(
          tmp_root / "seeds" / "starter.md",
          "# Starter Seed\n\nUpdated for regenesis.\n",
      )
      run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "regenesis", "sprout"],
          tmp_root,
          env,
      )
      regenesis_run_dir = sorted((tmp_root / "plants" / "sprout" / "runs").glob("*-regenesis"))[-1]
      regenesis_meta = json.loads((regenesis_run_dir / "meta.json").read_text())
      regenesis_output = (regenesis_run_dir / "_stdout.md").read_text().strip()
      assert regenesis_meta["driver"] == "codex"
      assert regenesis_meta["model"] == "codex-default-from-env"
      assert regenesis_meta["agent"] == "codex-default-from-env"
      assert regenesis_output == "codex:ok"

      env["PAK_DRIVER"] = "claude"
      env.pop("PAK_MODEL", None)

      write_file(
          tmp_root / "goals" / "003-plant.md",
          """---
assigned_to: worker
driver: codex
model: codex-mini-latest
---
# Goal

Plant routed.
""",
      )
      run_command(
          [
              str(tmp_root / "scripts" / "personalagentkit"),
              "plant-run",
              "worker",
              "goals/003-plant.md",
              "--driver",
              "claude",
              "--model",
              "claude-override",
          ],
          tmp_root,
          env,
      )
      plant_meta = json.loads(
          (tmp_root / "plants" / "worker" / "runs" / "003-plant" / "meta.json").read_text()
      )
      plant_output = (
          tmp_root / "plants" / "worker" / "runs" / "003-plant" / "_stdout.md"
      ).read_text().strip()
      assert plant_meta["driver"] == "claude"
      assert plant_meta["model"] == "claude-override"
      assert plant_meta["agent"] == "claude-override"
      assert plant_output == "claude:claude-override"

      plugin_dir = tmp_root / "plugins"
      plugin_dir.mkdir()
      install_plugin(plugin_dir)
      install_bad_plugin(plugin_dir)
      install_duplicate_plugin(plugin_dir)
      env["PAK_DRIVER_PLUGIN_PATH"] = str(plugin_dir)

      write_file(
          tmp_root / "goals" / "003-plugin.md",
          """---
driver: reverse
model: reverse-model
---
# Goal

Plugin routed.
""",
      )
      run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "run", "goals/003-plugin.md"],
          tmp_root,
          env,
      )
      plugin_meta = json.loads((tmp_root / "runs" / "003-plugin" / "meta.json").read_text())
      plugin_output = (tmp_root / "runs" / "003-plugin" / "_stdout.md").read_text().strip()
      assert plugin_meta["driver"] == "reverse"
      assert plugin_meta["model"] == "reverse-model"
      assert plugin_meta["agent"] == "reverse-model"
      assert plugin_meta["cost"]["actual_usd"] == 0.3333
      assert plugin_output.startswith("reverse:reverse-model:")

      builtin_resolve = run_command(
          ["python3", "-m", "runner.host", "resolve", "--driver", "claude"],
          tmp_root,
          env,
      )
      builtin_payload = json.loads(builtin_resolve.stdout)
      assert builtin_payload["driver"] == "claude"
      assert builtin_payload["binary"] == "claude"
      assert "bad_driver.py" in builtin_resolve.stderr
      assert "skipping external driver plugin" in builtin_resolve.stderr

      codex_resolve = run_command(
          ["python3", "-m", "runner.host", "resolve", "--driver", "codex"],
          tmp_root,
          env,
      )
      codex_payload = json.loads(codex_resolve.stdout)
      assert codex_payload["driver"] == "codex"
      assert codex_payload["binary"] == "codex"
      assert codex_payload["model"] == "gpt-5.4"
      assert "duplicate driver name 'codex'" in codex_resolve.stderr

      write_file(
          tmp_root / "goals" / "006-builtin-after-plugin-errors.md",
          """---
driver: claude
model: claude-after-plugin-errors
---
# Goal

Built-in after plugin errors.
""",
      )
      post_plugin_run = run_command(
          [
              str(tmp_root / "scripts" / "personalagentkit"),
              "run",
              "goals/006-builtin-after-plugin-errors.md",
          ],
          tmp_root,
          env,
      )
      post_plugin_meta = json.loads((tmp_root / "runs" / "006-builtin-after-plugin-errors" / "meta.json").read_text())
      post_plugin_output = (
          tmp_root / "runs" / "006-builtin-after-plugin-errors" / "_stdout.md"
      ).read_text().strip()
      assert post_plugin_meta["driver"] == "claude"
      assert post_plugin_meta["model"] == "claude-after-plugin-errors"
      assert post_plugin_output == "claude:claude-after-plugin-errors"
      assert "driver invocation failed" not in post_plugin_run.stderr

      preserved_run_dir = tmp_root / "runs" / "037-spike-live-claude-transcript-sample"
      preserved_run_dir.mkdir(parents=True, exist_ok=True)
      write_completed_claude_meta(preserved_run_dir)

      preserved_env = env.copy()
      preserved_env["PYTHONPATH"] = str(tmp_root)
      preserved_result = json.loads(
          run_command(
              [
                  "python3",
                  "-c",
                  (
                      "import json; "
                      "from pathlib import Path; "
                      "from runner.host import finalize_run_artifacts; "
                      "result = finalize_run_artifacts("
                      "driver='codex', model='gpt-5.4', "
                      f"run_dir=Path({str(preserved_run_dir)!r}), "
                      "exit_code=0, completed_at='2026-03-13T00:30:39Z'"
                      "); "
                      "print(json.dumps(result))"
                  ),
              ],
              tmp_root,
              preserved_env,
          ).stdout
      )
      preserved_meta = json.loads((preserved_run_dir / "meta.json").read_text())
      assert preserved_result["driver"] == "claude"
      assert preserved_result["model"] == "claude-sonnet-4-6"
      assert preserved_result["cost"]["actual_usd"] == 0.056855699999999995
      assert preserved_result["cost"]["estimated_usd"] is None
      assert preserved_result["cost"]["pricing"]["source"] == "provider-native"
      assert preserved_result["cost"]["pricing"]["provider"] == "claude"
      assert preserved_meta["driver"] == "claude"
      assert preserved_meta["cost"]["actual_usd"] == 0.056855699999999995
      assert preserved_meta["cost"]["estimated_usd"] is None
      assert preserved_meta["cost"]["pricing"]["source"] == "provider-native"
      assert preserved_meta["cost"]["pricing"]["provider"] == "claude"
      assert preserved_meta["completed_at"] == "2026-03-13T00:30:28Z"

      write_file(
          tmp_root / "source-goal.md",
          """---
assigned_to: worker
driver: claude
model: claude-source
---
# Goal

Submit me.
""",
      )
      submit_output = run_command(
          [
              str(tmp_root / "scripts" / "personalagentkit"),
              "submit",
              "--driver",
              "codex",
              "--model",
              "gpt-5.4",
              tmp_root / "source-goal.md",
          ],
          tmp_root,
          env,
      ).stdout
      submitted_line = [line for line in submit_output.splitlines() if line.startswith("submitted: ")][-1]
      submitted_rel = submitted_line.split(": ", 1)[1]
      submitted_text = (tmp_root / submitted_rel).read_text()
      assert "driver: codex" in submitted_text
      assert "model: gpt-5.4" in submitted_text
      assert "assigned_to: worker" in submitted_text

      write_file(
          tmp_root / "goals" / "004-dispatch-root.md",
          """---
driver: codex
model: codex-mini-latest
priority: 2
---
# Goal
""",
      )
      write_file(
          tmp_root / "goals" / "005-dispatch-plant.md",
          """---
assigned_to: worker
driver: claude
model: claude-queue
priority: 1
---
# Goal
""",
      )

      dispatcher = dispatch.Dispatcher(
          repo_root=tmp_root,
          max_workers=1,
          tend_interval=60,
          max_cost=None,
      )
      entries, blocked, _ = dispatcher._scan_queue()
      assert blocked == 0
      entry_map = {entry.goal_rel: entry for entry in entries}
      assert entry_map["goals/004-dispatch-root.md"].driver == "codex"
      assert entry_map["goals/004-dispatch-root.md"].model == "codex-mini-latest"
      assert entry_map["goals/005-dispatch-plant.md"].driver == "claude"
      assert entry_map["goals/005-dispatch-plant.md"].model == "claude-queue"

      captured = []
      original_run = dispatch.subprocess.run

      def fake_run(cmd, cwd=None, **kwargs):
          captured.append((cmd, cwd))
          return subprocess.CompletedProcess(cmd, 0)

      dispatch.subprocess.run = fake_run
      try:
          for goal_rel in ["goals/004-dispatch-root.md", "goals/005-dispatch-plant.md"]:
              dispatcher.active_slots = 1
              dispatcher.in_progress.add(goal_rel)
              dispatcher._worker(entry_map[goal_rel])
      finally:
          dispatch.subprocess.run = original_run

      assert captured[0][0][-4:] == ["--driver", "codex", "--model", "codex-mini-latest"]
      assert captured[1][0][-4:] == ["--driver", "claude", "--model", "claude-queue"]
      assert captured[0][0][1:3] == ["run", "goals/004-dispatch-root.md"]
      plant_dispatch_cmd = captured[1][0]
      assert plant_dispatch_cmd[-4:] == ["--driver", "claude", "--model", "claude-queue"]
      assert plant_dispatch_cmd[1:3] == ["run", "goals/005-dispatch-plant.md"] or plant_dispatch_cmd[1:4] == [
          "plant-run",
          "worker",
          "goals/005-dispatch-plant.md",
      ]

      write_file(
          tmp_root / "goals" / "006-nested-guard.md",
          """---
driver: codex
---
# Goal
""",
      )
      nested_env = env.copy()
      nested_env["PAK_ACTIVE_RUN_ID"] = "045-parent"
      nested_env["PAK_ACTIVE_RUN_DIR"] = str(tmp_root / "runs" / "045-parent")
      nested_env["PAK_ACTIVE_DRIVER"] = "claude"
      nested_run = run_command(
          [str(tmp_root / "scripts" / "personalagentkit"), "run", "goals/006-nested-guard.md"],
          tmp_root,
          nested_env,
          check=False,
      )
      assert nested_run.returncode != 0
      assert "nested personalagentkit run is blocked inside an active run" in nested_run.stderr
      assert "Route cross-driver work through goal frontmatter" in nested_run.stderr
      assert not (tmp_root / "runs" / "006-nested-guard").exists()

    print("driver routing verification passed")


if __name__ == "__main__":
    main()
