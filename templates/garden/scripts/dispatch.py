#!/usr/bin/env python3
"""
dispatch.py — concurrent personalagentkit dispatcher

Replaces the bash cmd_cycle loop with:
  - N parallel worker threads (one subprocess per goal)
  - 1 gardener thread (tend on timer + on quiet garden)
  - Operator sentinels: .personalagentkit-pause, .personalagentkit-stop
  - Priority queue: goals sorted by (priority, NNN)
"""

import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(order=True)
class GoalEntry:
    priority: int
    nnn: int
    goal_rel: str = field(compare=False)
    assigned_to: str = field(compare=False)


class Dispatcher:
    def __init__(
        self,
        repo_root: Path,
        max_workers: int,
        tend_interval: int,
        max_cost: Optional[float],
        retro_interval: int = 14400,
    ):
        self.repo_root = repo_root
        self.max_workers = max_workers
        self.tend_interval = tend_interval
        self.max_cost = max_cost
        self.retro_interval = retro_interval

        self.lock = threading.Lock()
        self.active_slots = 0
        self.in_progress: set[str] = set()
        self.cycle_cost: float = 0.0
        self.slot_freed = threading.Event()
        self.quiet_event = threading.Event()
        self.gardener_running = False
        self.retrospective_running = False
        self._stop_requested = False
        self._recent_completions = 0
        self._startup_gardener_run_id: Optional[str] = None

        # On startup, scan all plants for live runs to restore in-memory state.
        # Prevents concurrent dispatch when the dispatcher restarts while a run
        # is still active. Gardener runs set gardener_running=True; other plant
        # runs are added to in_progress so they won't be dispatched again.
        plants_dir = self.repo_root / "plants"
        if plants_dir.is_dir():
            now_utc = datetime.now(timezone.utc)
            for plant_dir in plants_dir.iterdir():
                if not plant_dir.is_dir():
                    continue
                plant_name = plant_dir.name
                runs_dir = plant_dir / "runs"
                if not runs_dir.is_dir():
                    continue
                for run_dir in runs_dir.iterdir():
                    if not run_dir.is_dir():
                        continue
                    run_id = run_dir.name
                    meta_path = run_dir / "meta.json"
                    if not meta_path.exists():
                        continue
                    try:
                        data = json.loads(meta_path.read_text())
                        if data.get("status") != "running":
                            continue
                        started_raw = data.get("started_at", "")
                        if not started_raw:
                            continue
                        start_dt = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
                        age_s = (now_utc - start_dt).total_seconds()
                        if age_s >= 600:
                            continue  # zombie — existing zombie detection will handle it
                        print(
                            f"personalagentkit: startup scan: found live run {run_id}, treating as active",
                            flush=True,
                        )
                        if plant_name == "gardener":
                            self.gardener_running = True
                            self._startup_gardener_run_id = run_id
                        else:
                            goal_rel = f"goals/{run_id}.md"
                            self.in_progress.add(goal_rel)
                            self.active_slots += 1
                            t = threading.Thread(
                                target=self._monitor_restored_run,
                                args=(plant_name, run_id, goal_rel),
                                daemon=True,
                            )
                            t.start()
                    except Exception:
                        pass

    # ── sentinel helpers ──────────────────────────────────────────────────────

    def _pause_set(self) -> bool:
        return (self.repo_root / ".personalagentkit-pause").exists()

    def _stop_set(self) -> bool:
        return (self.repo_root / ".personalagentkit-stop").exists() or self._stop_requested

    def _check_sentinels(self) -> str:
        """Returns 'stop', 'pause', or 'ok'."""
        if self._stop_set():
            return "stop"
        if self._pause_set():
            return "pause"
        return "ok"

    # ── run detection ─────────────────────────────────────────────────────────

    def _has_run(self, nnn: str, plant: str = "") -> bool:
        """True if a run directory with this NNN prefix exists.

        If plant is specified, only checks that plant's runs directory.
        This prevents gardener tend runs (e.g., 056-tend) from blocking
        goals assigned to other plants (e.g., 056-simplelogin → builder).
        """
        if plant:
            plant_runs = self.repo_root / "plants" / plant / "runs"
            return plant_runs.exists() and bool(list(plant_runs.glob(f"{nnn}-*")))
        pattern = str(self.repo_root / "runs" / f"{nnn}-*")
        if glob.glob(pattern):
            return True
        for plant_runs in (self.repo_root / "plants").glob("*/runs/"):
            if list(plant_runs.glob(f"{nnn}-*")):
                return True
        return False

    def _check_dep(self, dep: str) -> str:
        """Check dependency status. Returns 'satisfied', 'pending', or 'impossible'.

        Dependency syntax:
          NNN-slug          — satisfied when run succeeds (default, backward compatible)
          NNN-slug:done     — satisfied when run completes with any status
          NNN-slug:failed   — satisfied only when run fails
          NNN-slug:killed   — satisfied only when run is killed
          NNN-slug:success  — explicit success (same as no qualifier)
        """
        dep = dep.strip()
        if not dep:
            return "satisfied"

        # Parse optional status qualifier
        required_status = "success"
        if ":" in dep:
            dep, required_status = dep.rsplit(":", 1)

        if dep and dep[0].isdigit():
            pattern = dep
        else:
            pattern = f"*-{dep}"

        terminal_statuses = {"success", "failure", "killed"}

        def check_dir(runs_dir: Path):
            """Returns (found_terminal, matched) for best match in this dir."""
            for run_dir in runs_dir.glob(f"{pattern}/"):
                meta = run_dir / "meta.json"
                if meta.exists():
                    try:
                        data = json.loads(meta.read_text())
                        status = data.get("status", "")
                        if status not in terminal_statuses:
                            return "pending"
                        if required_status == "done":
                            return "satisfied"
                        if status == required_status:
                            return "satisfied"
                        # Terminal status but wrong one — impossible
                        return "impossible"
                    except Exception:
                        pass
            return None  # no run found

        for search_dir in [self.repo_root / "runs"] + list(
            (self.repo_root / "plants").glob("*/")
        ):
            runs_dir = search_dir if search_dir.name == "runs" else search_dir / "runs"
            result = check_dir(runs_dir)
            if result is not None:
                return result
        return "pending"

    def _is_dep_satisfied(self, dep: str) -> bool:
        """Backward-compatible wrapper."""
        return self._check_dep(dep) == "satisfied"

    # ── queue scan ────────────────────────────────────────────────────────────

    def _scan_queue(self) -> tuple[list[GoalEntry], int, Optional[datetime]]:
        """
        Returns (runnable_entries_sorted, blocked_count, earliest_not_before).
        Skips goals already in self.in_progress.
        earliest_not_before is the soonest time-gated goal, or None if no time gates.
        """
        entries: list[GoalEntry] = []
        blocked = 0
        earliest_not_before: Optional[datetime] = None

        goals_dir = self.repo_root / "goals"
        for goal_path in sorted(goals_dir.glob("[0-9][0-9][0-9]-*.md")):
            base = goal_path.stem
            nnn = base[:3]
            nnn_int = int(nnn)

            if str(goal_path.relative_to(self.repo_root)) in self.in_progress:
                continue

            # Parse frontmatter first (needed for plant-aware _has_run check)
            assigned_to = ""
            depends_on_raw = ""
            requires_raw = ""
            not_before_raw = ""
            priority = 5
            try:
                text = goal_path.read_text()
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 2:
                        fm = parts[1]
                        for line in fm.splitlines():
                            if line.startswith("assigned_to:"):
                                assigned_to = line.split(":", 1)[1].strip()
                            elif line.startswith("depends_on:"):
                                depends_on_raw = line.split(":", 1)[1].strip()
                            elif line.startswith("requires:"):
                                requires_raw = line.split(":", 1)[1].strip()
                            elif line.startswith("not_before:"):
                                not_before_raw = line.split(":", 1)[1].strip()
                            elif line.startswith("priority:"):
                                try:
                                    priority = int(line.split(":", 1)[1].strip())
                                except ValueError:
                                    pass
            except Exception:
                pass

            # Skip if already run — check only the assigned plant's runs (if specified)
            # so gardener tend runs don't block builder/scout goals with the same NNN
            if self._has_run(nnn, plant=assigned_to):
                continue

            # Check not_before time gate
            if not_before_raw:
                try:
                    not_before_dt = datetime.fromisoformat(not_before_raw.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) < not_before_dt:
                        blocked += 1
                        if earliest_not_before is None or not_before_dt < earliest_not_before:
                            earliest_not_before = not_before_dt
                        continue
                except Exception:
                    pass

            # Check dependencies
            if depends_on_raw:
                deps = [d.strip() for d in depends_on_raw.strip("[]").split(",") if d.strip()]
                dep_results = [self._check_dep(d) for d in deps]
                if "impossible" in dep_results:
                    # Auto-cancel: a dependency resolved to the wrong status
                    impossible_deps = [d for d, r in zip(deps, dep_results) if r == "impossible"]
                    cancelled = goal_path.with_suffix(".cancelled")
                    goal_path.rename(cancelled)
                    print(
                        f"personalagentkit: auto-cancel {base} — impossible dep: {', '.join(impossible_deps)}",
                        flush=True,
                    )
                    # Best-effort git commit
                    try:
                        import subprocess as _sp
                        _sp.run(
                            ["git", "-C", str(self.repo_root), "add", str(cancelled)],
                            capture_output=True,
                        )
                        _sp.run(
                            ["git", "-C", str(self.repo_root), "commit", "-m",
                             f"auto-cancel: {base} (impossible dep)"],
                            capture_output=True,
                        )
                    except Exception:
                        pass
                    continue
                if "pending" in dep_results:
                    blocked += 1
                    continue

            # Check capability gaps (named: capability-gap-<name>.md)
            if assigned_to and requires_raw:
                reqs = [r.strip() for r in requires_raw.strip("[]").split(",") if r.strip()]
                plant_dir = self.repo_root / "plants" / assigned_to
                blocked_by_gap = []
                for req in reqs:
                    if (plant_dir / f"capability-gap-{req}.md").exists():
                        blocked_by_gap.append(req)
                if blocked_by_gap:
                    print(
                        f"personalagentkit: skip {base} — {assigned_to} has capability gap: {', '.join(blocked_by_gap)}",
                        flush=True,
                    )
                    blocked += 1
                    continue

            goal_rel = f"goals/{base}.md"
            entries.append(GoalEntry(priority, nnn_int, goal_rel, assigned_to))

        return sorted(entries), blocked, earliest_not_before

    # ── inbox surfacing ───────────────────────────────────────────────────────

    def _surface_inbox(self):
        inbox = self.repo_root / "inbox"
        if not inbox.is_dir():
            return
        pending = []
        for msg in sorted(inbox.glob("*-to-operator.md")):
            base = msg.stem
            nnn = ""
            for ch in base:
                if ch.isdigit():
                    nnn += ch
                else:
                    break
            reply = inbox / f"{nnn}-reply.md"
            if not reply.exists():
                pending.append(msg)
        if pending:
            print("personalagentkit: ── inbox ────────────────────────────────────────────────", flush=True)
            for msg in pending:
                print(f"personalagentkit: pending: {msg}", flush=True)
                print("---", flush=True)
                try:
                    print(msg.read_text(), flush=True)
                except Exception:
                    pass
                print("---", flush=True)
            print("personalagentkit: ────────────────────────────────────────────────────────", flush=True)

    # ── inbox polling ─────────────────────────────────────────────────────────

    def _poll_inbox(self):
        """Run scripts/read-email to archive any new replies before dispatching."""
        read_email = self.repo_root / "scripts" / "read-email"
        if not read_email.exists():
            return
        try:
            result = subprocess.run(
                [str(read_email)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            for line in result.stdout.splitlines():
                if line.strip():
                    print(f"personalagentkit: {line}", flush=True)
        except Exception as e:
            print(f"personalagentkit: read-email failed (non-fatal): {e}", flush=True)

    # ── running plant check ───────────────────────────────────────────────────

    def _plant_has_running_run(self, plant: str) -> tuple[bool, str]:
        """Check if a plant already has an active run by reading meta.json files.

        Returns (is_running, run_id). Uses filesystem state rather than in-memory
        flags so it survives dispatcher restarts while a run is still active.

        Note: zombie detection is only applied for the gardener plant (coder and
        reviewer runs are not expected to be long-running background daemons).
        """
        plant_runs = self.repo_root / "plants" / plant / "runs"
        if not plant_runs.is_dir():
            return False, ""

        # Find the most recently modified meta.json
        latest_run_id = ""
        latest_mtime = 0.0
        for run_dir in plant_runs.iterdir():
            if not run_dir.is_dir():
                continue
            meta = run_dir / "meta.json"
            if not meta.exists():
                continue
            try:
                mtime = meta.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_run_id = run_dir.name
            except Exception:
                pass

        if not latest_run_id:
            return False, ""

        meta = plant_runs / latest_run_id / "meta.json"
        try:
            data = json.loads(meta.read_text())
            if data.get("status") == "running":
                # Zombie detection: if started_at is more than 10 minutes ago,
                # the run is a zombie (crashed mid-run, left status=running).
                # Threshold is 600s because the watchdog kills any process that
                # exceeds that timeout — so any run older than 600s is guaranteed stuck.
                started_raw = data.get("started_at", "")
                is_zombie = False
                age_seconds = None
                if started_raw:
                    try:
                        started_dt = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
                        age_seconds = (datetime.now(timezone.utc) - started_dt).total_seconds()
                        if age_seconds >= 600:  # 10 minutes = watchdog timeout
                            is_zombie = True
                    except Exception:
                        # Malformed started_at — can't determine age, treat as zombie to unblock
                        is_zombie = True
                else:
                    # No started_at — can't verify age, treat as zombie to unblock
                    is_zombie = True

                if is_zombie:
                    age_str = f"{int(age_seconds / 60)}m" if age_seconds is not None else "?"
                    print(
                        f"personalagentkit: zombie run detected: {latest_run_id} "
                        f"(status=running but started {age_str} ago) — marking failed",
                        flush=True,
                    )
                    try:
                        data["status"] = "failed"
                        data["zombie_cleaned_at"] = datetime.now(timezone.utc).isoformat()
                        data["zombie_note"] = "Cleaned by dispatcher zombie detection (status=running but process not alive)"
                        meta.write_text(json.dumps(data, indent=2))
                    except Exception as e:
                        print(f"personalagentkit: warning: could not update zombie meta.json: {e}", flush=True)
                    return False, ""

                return True, latest_run_id
        except Exception:
            pass

        return False, ""

    # ── work detection ────────────────────────────────────────────────────────

    def _has_work(self, since: float) -> tuple[bool, str]:
        """Return (has_work, reason). Used to suppress idle timer-triggered tends.

        Returns True (fail open) on any exception.
        Checks:
          1. Unrun goals in goals/ (runnable or blocked)
          2. In-progress plant goals
          3. Inbox files newer than `since` timestamp
          4. Recent plant goal completions since last tend
        """
        # Check 1: unrun goals
        try:
            entries, blocked, _ = self._scan_queue()
            if entries:
                return True, f"{len(entries)} runnable goal(s) in queue"
            if blocked > 0:
                return True, f"{blocked} blocked goal(s) in queue"
        except Exception as e:
            return True, f"queue check failed (fail open): {e}"

        # Check 2: in-progress plant goals
        try:
            with self.lock:
                in_prog = set(self.in_progress)
            if in_prog:
                return True, f"in-progress goals: {', '.join(sorted(in_prog))}"
        except Exception as e:
            return True, f"in-progress check failed (fail open): {e}"

        # Check 3: inbox files newer than last tend
        try:
            inbox_dir = self.repo_root / "inbox"
            if inbox_dir.is_dir():
                for msg in inbox_dir.glob("*.md"):
                    try:
                        if msg.stat().st_mtime > since:
                            return True, f"new inbox message: {msg.name}"
                    except Exception:
                        pass
        except Exception as e:
            return True, f"inbox check failed (fail open): {e}"

        # Check 4: recent completions since last tend
        try:
            with self.lock:
                recent = self._recent_completions
            if recent > 0:
                return True, f"{recent} recent completion(s) since last tend"
        except Exception as e:
            return True, f"recent completions check failed (fail open): {e}"

        return False, "no queue, no active goals, no new inbox messages, no recent completions"

    # ── worker thread ─────────────────────────────────────────────────────────

    def _auto_scaffold_plant(self, plant_name: str):
        plant_dir = self.repo_root / "plants" / plant_name
        if plant_dir.exists():
            return
        print(f"personalagentkit: auto-scaffolding plant: {plant_name}", flush=True)
        for subdir in ["goals", "runs", "memory"]:
            (plant_dir / subdir).mkdir(parents=True, exist_ok=True)
        src = self.repo_root / "MOTIVATION.md"
        dst = plant_dir / "MOTIVATION.md"
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text())

    def _worker(self, entry: GoalEntry):
        goal_rel = entry.goal_rel
        assigned_to = entry.assigned_to
        telos = str(self.repo_root / "scripts" / "personalagentkit")

        try:
            if assigned_to:
                self._auto_scaffold_plant(assigned_to)
                cmd = [telos, "plant-run", assigned_to, goal_rel]
                label = f"{assigned_to}/{goal_rel}"
            else:
                cmd = [telos, "run", goal_rel]
                label = goal_rel

            print(f"personalagentkit: dispatch → {label}", flush=True)
            result = subprocess.run(cmd, cwd=str(self.repo_root))

            # Accumulate cost if tracking
            if self.max_cost is not None:
                goal_id = Path(goal_rel).stem
                if assigned_to:
                    meta_path = (
                        self.repo_root / "plants" / assigned_to / "runs" / goal_id / "meta.json"
                    )
                else:
                    meta_path = self.repo_root / "runs" / goal_id / "meta.json"
                try:
                    data = json.loads(meta_path.read_text())
                    run_cost = float(data.get("cost", {}).get("actual_usd", 0) or 0)
                    with self.lock:
                        self.cycle_cost += run_cost
                except Exception:
                    pass

        finally:
            with self.lock:
                self.active_slots -= 1
                self.in_progress.discard(goal_rel)
                self._recent_completions += 1
            self.slot_freed.set()

    # ── restored-run monitor thread ───────────────────────────────────────────

    def _monitor_restored_run(self, plant_name: str, run_id: str, goal_rel: str):
        """Poll a startup-restored non-gardener run until terminal, then release slot."""
        terminal_statuses = {"success", "abandoned", "failure", "killed"}
        meta_path = self.repo_root / "plants" / plant_name / "runs" / run_id / "meta.json"
        while not self._stop_set():
            time.sleep(5)
            try:
                data = json.loads(meta_path.read_text())
                if data.get("status") in terminal_statuses:
                    with self.lock:
                        self.active_slots -= 1
                        self.in_progress.discard(goal_rel)
                    self.slot_freed.set()
                    print(
                        f"personalagentkit: startup-restored run {run_id} ({plant_name})"
                        " completed — slot released",
                        flush=True,
                    )
                    return
            except Exception:
                pass

    # ── gardener thread ───────────────────────────────────────────────────────

    def _gardener_thread(self):
        last_tend = 0.0
        telos = str(self.repo_root / "scripts" / "personalagentkit")
        while not self._stop_set():
            now = time.time()
            time_due = (now - last_tend) >= self.tend_interval
            quiet = self.quiet_event.wait(timeout=1)
            self.quiet_event.clear()

            trigger = "timer" if time_due else "quiet-event"
            if (time_due or quiet) and not self.gardener_running:
                with self.lock:
                    self.gardener_running = True
                should_tend = True
                try:
                    self._poll_inbox()

                    # Suppress tends when there is nothing to do, regardless of
                    # trigger source (timer or quiet-event). The quiet-event path
                    # was previously always allowed through, which caused tend-chains
                    # after every goal completion even with no follow-on work.
                    force_file = self.repo_root / ".personalagentkit-force-tend"
                    if force_file.exists():
                        try:
                            force_file.unlink()
                        except Exception:
                            pass
                        print("personalagentkit: .personalagentkit-force-tend sentinel — forcing tend", flush=True)
                    else:
                        has_work, reason = self._has_work(since=last_tend)
                        if not has_work:
                            print(
                                "personalagentkit: skipping tend — nothing to do "
                                "(no queue, no inbox, no active goals)",
                                flush=True,
                            )
                            last_tend = time.time()
                            should_tend = False

                    if should_tend:
                        # Filesystem-level guard: skip if gardener plant already has a
                        # running tend. The in-memory gardener_running flag can't catch
                        # races across dispatcher restarts or near-simultaneous triggers.
                        already_running, running_run_id = self._plant_has_running_run("gardener")
                        if already_running:
                            print(
                                f"personalagentkit: skipping dispatch for gardener: already running {running_run_id}",
                                flush=True,
                            )
                            should_tend = False

                    if should_tend:
                        print("personalagentkit: gardener tending...", flush=True)
                        with self.lock:
                            count_covered = self._recent_completions
                        subprocess.run([telos, "tend", "--trigger", trigger], cwd=str(self.repo_root))
                        last_tend = time.time()
                        with self.lock:
                            self._recent_completions = max(0, self._recent_completions - count_covered)
                finally:
                    with self.lock:
                        self.gardener_running = False
                self.slot_freed.set()  # wake main loop to re-scan

            # If gardener_running was set by startup scan, poll the restored run
            # for terminal status and clear the flag once it completes.
            elif self._startup_gardener_run_id and self.gardener_running:
                startup_run_id = self._startup_gardener_run_id
                meta_path = (
                    self.repo_root / "plants" / "gardener" / "runs"
                    / startup_run_id / "meta.json"
                )
                try:
                    data = json.loads(meta_path.read_text())
                    if data.get("status") not in (None, "running"):
                        with self.lock:
                            self.gardener_running = False
                        self._startup_gardener_run_id = None
                        print(
                            f"personalagentkit: startup-restored gardener run {startup_run_id}"
                            " completed — clearing gardener_running",
                            flush=True,
                        )
                        self.slot_freed.set()
                except Exception:
                    pass

    # ── retrospective thread ─────────────────────────────────────────────────

    def _should_run_retrospective(self, min_new_runs: int = 2) -> tuple[bool, str]:
        """Return (should_run, reason).

        Scans all plant run directories for completed retrospective runs to find
        the most recent one's started_at timestamp, then counts substantive
        completed runs (non-tend, non-retrospective) since that timestamp.
        Returns False if fewer than min_new_runs exist.
        """
        terminal_statuses = {"success", "abandoned", "failure", "killed"}

        # Collect all run meta.json paths across all plants and the root runs dir
        search_dirs = [self.repo_root / "runs"] + list(
            (self.repo_root / "plants").glob("*/runs/")
        )

        latest_retro_started_at: Optional[datetime] = None

        for runs_dir in search_dirs:
            if not runs_dir.is_dir():
                continue
            for run_dir in runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                if not run_dir.name.endswith("-retrospective"):
                    continue
                meta = run_dir / "meta.json"
                if not meta.exists():
                    continue
                try:
                    data = json.loads(meta.read_text())
                    if data.get("status") not in terminal_statuses:
                        continue
                    started_raw = data.get("started_at", "")
                    if not started_raw:
                        continue
                    started_dt = datetime.fromisoformat(started_raw.replace("Z", "+00:00"))
                    if latest_retro_started_at is None or started_dt > latest_retro_started_at:
                        latest_retro_started_at = started_dt
                except Exception:
                    pass

        if latest_retro_started_at is None:
            return True, "no previous retrospective found — running first retrospective"

        # Count substantive completed runs since the last retrospective
        new_run_count = 0
        for runs_dir in search_dirs:
            if not runs_dir.is_dir():
                continue
            for run_dir in runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                name = run_dir.name
                # Skip tends and retrospectives — they don't produce synthesis material
                if name.endswith("-tend") or name.endswith("-retrospective"):
                    continue
                meta = run_dir / "meta.json"
                if not meta.exists():
                    continue
                try:
                    data = json.loads(meta.read_text())
                    if data.get("status") not in terminal_statuses:
                        continue
                    completed_raw = data.get("completed_at", "")
                    if not completed_raw:
                        continue
                    completed_dt = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                    if completed_dt > latest_retro_started_at:
                        new_run_count += 1
                except Exception:
                    pass

        if new_run_count < min_new_runs:
            return (
                False,
                f"only {new_run_count} new run(s) since last retrospective at "
                f"{latest_retro_started_at.isoformat()} (need {min_new_runs})",
            )
        return (
            True,
            f"{new_run_count} new run(s) since last retrospective at "
            f"{latest_retro_started_at.isoformat()}",
        )

    def _retrospective_thread(self):
        last_retro = 0.0
        telos = str(self.repo_root / "scripts" / "personalagentkit")
        while not self._stop_set():
            time.sleep(10)
            now = time.time()
            if (now - last_retro) < self.retro_interval:
                continue
            # Don't run if gardener is already running
            with self.lock:
                if self.gardener_running or self.retrospective_running:
                    continue
                self.retrospective_running = True
            try:
                should_run, reason = self._should_run_retrospective()
                if not should_run:
                    print(
                        f"personalagentkit: skipping retrospective — {reason}",
                        flush=True,
                    )
                    last_retro = time.time()
                    continue
                print(f"personalagentkit: retrospective starting ({reason})...", flush=True)
                subprocess.run([telos, "retrospective"], cwd=str(self.repo_root))
                last_retro = time.time()
            finally:
                with self.lock:
                    self.retrospective_running = False

    # ── fill slots ────────────────────────────────────────────────────────────

    def _fill_slots(self, entries: list[GoalEntry]) -> int:
        """Launch workers up to max_workers. Returns number launched."""
        launched = 0
        for entry in entries:
            with self.lock:
                if self.active_slots >= self.max_workers:
                    break
                if entry.goal_rel in self.in_progress:
                    continue
                # Check cost cap
                if self.max_cost is not None and self.cycle_cost >= self.max_cost:
                    break
                self.active_slots += 1
                self.in_progress.add(entry.goal_rel)
            t = threading.Thread(target=self._worker, args=(entry,), daemon=True)
            t.start()
            launched += 1
        return launched

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self._surface_inbox()

        print(
            f"personalagentkit: dispatch starting (workers={self.max_workers}, "
            f"tend_interval={self.tend_interval}s, "
            f"retro_interval={self.retro_interval}s"
            + (f", max_cost=${self.max_cost:.2f}" if self.max_cost else "")
            + ")",
            flush=True,
        )

        # Start gardener thread
        gthread = threading.Thread(target=self._gardener_thread, daemon=True)
        gthread.start()

        # Start retrospective thread
        rthread = threading.Thread(target=self._retrospective_thread, daemon=True)
        rthread.start()

        while True:
            # Check sentinels
            sentinel = self._check_sentinels()
            if sentinel == "stop":
                print("personalagentkit: stop sentinel detected — waiting for in-flight goals...", flush=True)
                # Wait for active workers to finish
                while True:
                    with self.lock:
                        active = self.active_slots
                    if active == 0:
                        break
                    self.slot_freed.wait(timeout=5)
                    self.slot_freed.clear()
                # Wait for gardener tend to finish if running
                while True:
                    with self.lock:
                        if not self.gardener_running:
                            break
                    time.sleep(1)
                # Wait for retrospective to finish if running
                while True:
                    with self.lock:
                        if not self.retrospective_running:
                            break
                    time.sleep(1)
                print("personalagentkit: dispatcher stopped cleanly", flush=True)
                return
            if sentinel == "pause":
                print("personalagentkit: pause sentinel set — sleeping (run ./scripts/personalagentkit resume to continue)", flush=True)
                time.sleep(5)
                continue

            # Cost cap check
            if self.max_cost is not None:
                with self.lock:
                    current_cost = self.cycle_cost
                if current_cost >= self.max_cost:
                    with self.lock:
                        active = self.active_slots
                    if active == 0:
                        print(
                            f"personalagentkit: cost cap reached (${current_cost:.2f} / ${self.max_cost:.2f})",
                            flush=True,
                        )
                        return

            # Scan queue and fill slots
            entries, blocked, earliest_nb = self._scan_queue()
            launched = self._fill_slots(entries)

            with self.lock:
                active = self.active_slots

            # Check quiet / done conditions
            if active == 0 and not entries:
                # If gardener is already mid-tend, wait for it to finish first
                # before deciding the garden is truly exhausted or stalled.
                with self.lock:
                    gardener_busy = self.gardener_running
                if gardener_busy:
                    print("personalagentkit: waiting for gardener to finish tending...", flush=True)
                    while True:
                        with self.lock:
                            if not self.gardener_running:
                                break
                        time.sleep(1)
                    entries2, blocked2, earliest_nb2 = self._scan_queue()
                    if entries2:
                        continue
                    earliest_nb = earliest_nb2
                    if blocked2 > 0 and earliest_nb is None:
                        print(
                            f"personalagentkit: stalled — {blocked2} goal(s) blocked by unmet dependencies",
                            flush=True,
                        )
                        return
                    if blocked2 == 0:
                        pass  # fall through to quiet-garden signal
                    # else: has time-gated goals, fall through to sleep logic

                if blocked > 0 and earliest_nb is None:
                    # Blocked by deps/caps only — gardener last tend
                    self.quiet_event.set()
                    print("personalagentkit: blocked goals — signaling gardener for final tend...", flush=True)

                    deadline = time.time() + 30
                    while time.time() < deadline:
                        with self.lock:
                            if self.gardener_running:
                                break
                        time.sleep(0.5)
                    print("personalagentkit: waiting for gardener tend to complete...", flush=True)
                    while True:
                        with self.lock:
                            if not self.gardener_running:
                                break
                        time.sleep(1)

                    entries2, blocked2, earliest_nb2 = self._scan_queue()
                    if entries2:
                        continue
                    earliest_nb = earliest_nb2
                    if earliest_nb is None:
                        print(
                            f"personalagentkit: stalled — {blocked2} goal(s) blocked by unmet dependencies",
                            flush=True,
                        )
                        return
                    # else: has time-gated goals, fall through to sleep logic

                # If there are time-gated goals, sleep until the earliest one opens
                if earliest_nb is not None:
                    wait_secs = (earliest_nb - datetime.now(timezone.utc)).total_seconds()
                    if wait_secs > 0:
                        print(
                            f"personalagentkit: {blocked} goal(s) time-gated — "
                            f"sleeping until {earliest_nb.isoformat()} "
                            f"({wait_secs:.0f}s)",
                            flush=True,
                        )
                        # Sleep in short intervals so sentinels are still checked
                        wake_time = time.time() + wait_secs
                        while time.time() < wake_time:
                            if self._stop_set() or self._pause_set():
                                break
                            time.sleep(min(30, wake_time - time.time()))
                    continue

                if blocked == 0:
                    # Quiet garden — signal gardener and wait for it to complete
                    self.quiet_event.set()
                    print("personalagentkit: garden is quiet — signaling gardener...", flush=True)

                    # Wait for gardener to start (up to 30s)
                    deadline = time.time() + 30
                    while time.time() < deadline:
                        with self.lock:
                            if self.gardener_running:
                                break
                        time.sleep(0.5)

                    # Wait for gardener to finish, however long it takes
                    print("personalagentkit: waiting for gardener tend to complete...", flush=True)
                    while True:
                        with self.lock:
                            if not self.gardener_running:
                                break
                        time.sleep(1)

                    # Re-scan now that tend is complete
                    entries2, blocked2, earliest_nb2 = self._scan_queue()
                    if entries2:
                        continue
                    if earliest_nb2 is not None:
                        earliest_nb = earliest_nb2
                        continue  # loop back to hit the time-gate sleep
                    # Queue still empty after tend — stay alive, poll email
                    # periodically, and let the gardener try again on schedule.
                    # If email arrives, trigger an immediate tend so Vigil can
                    # read and respond without waiting for the full interval.
                    self._poll_inbox()
                    print(
                        f"personalagentkit: queue empty after tend — idling "
                        f"(polling email every 60s, tend every {self.tend_interval}s)",
                        flush=True,
                    )
                    wake_time = time.time() + self.tend_interval
                    last_poll = time.time()
                    while time.time() < wake_time:
                        if self._stop_set() or self._pause_set():
                            break
                        self.slot_freed.wait(timeout=min(30, wake_time - time.time()))
                        self.slot_freed.clear()
                        # Check if new goals appeared (e.g. from external submit)
                        new_entries, _, _ = self._scan_queue()
                        if new_entries:
                            break
                        # Poll email every 60s — new mail triggers immediate tend
                        if time.time() - last_poll >= 60:
                            self._poll_inbox()
                            last_poll = time.time()
                            # Check if read-email created new inbox files
                            inbox_dir = self.repo_root / "inbox"
                            if inbox_dir.is_dir():
                                for msg in sorted(inbox_dir.glob("*-reply.md")):
                                    # If there's a recent reply, wake gardener
                                    try:
                                        age = time.time() - msg.stat().st_mtime
                                        if age < 120:  # reply less than 2 min old
                                            print(
                                                f"personalagentkit: new operator reply detected — waking gardener",
                                                flush=True,
                                            )
                                            self.quiet_event.set()
                                            wake_time = 0  # break outer loop
                                            break
                                    except Exception:
                                        pass
                    continue

            # Clear quiet if slots are active
            if active > 0:
                self.quiet_event.clear()

            self.slot_freed.wait(timeout=5)
            self.slot_freed.clear()


def _acquire_pid_lock(pid_file: Path) -> bool:
    """Acquire the PID file lock. Returns True if we became the owner, False if another live process holds it."""
    import atexit

    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            # Check if that process is alive
            os.kill(existing_pid, 0)
            # Process is alive — we are a duplicate
            print(
                f"dispatch.py: already running as PID {existing_pid} — exiting",
                flush=True,
            )
            return False
        except (ValueError, ProcessLookupError):
            # Dead or invalid PID — stale file, take over
            print(
                f"dispatch.py: stale PID file (dead process) — taking over",
                flush=True,
            )
        except PermissionError:
            # Process exists but we can't signal it — treat as alive
            try:
                existing_pid = int(pid_file.read_text().strip())
                print(
                    f"dispatch.py: already running as PID {existing_pid} (no signal permission) — exiting",
                    flush=True,
                )
            except Exception:
                pass
            return False

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    def _remove_pid_file():
        try:
            if pid_file.exists() and pid_file.read_text().strip() == str(os.getpid()):
                pid_file.unlink()
        except Exception:
            pass

    atexit.register(_remove_pid_file)
    return True


def main():
    parser = argparse.ArgumentParser(description="PersonalAgentKit concurrent dispatcher")
    parser.add_argument("--repo-root", required=True, help="Path to repo root")
    parser.add_argument("--workers", type=int, default=2, help="Max concurrent goals")
    parser.add_argument("--tend-interval", type=int, default=300, help="Gardener interval (seconds)")
    parser.add_argument("--max-cost", type=float, default=None, help="Stop when cycle cost exceeds this")
    parser.add_argument("--retro-interval", type=int, default=14400, help="Retrospective interval (seconds, default 4h)")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"dispatch.py: repo-root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    # Single-instance enforcement via PID file
    pid_file = repo_root / "tmp" / "dispatch.pid"
    if not _acquire_pid_lock(pid_file):
        sys.exit(0)

    dispatcher = Dispatcher(
        repo_root=repo_root,
        max_workers=args.workers,
        tend_interval=args.tend_interval,
        max_cost=args.max_cost,
        retro_interval=args.retro_interval,
    )

    # On SIGINT: touch .personalagentkit-stop for clean shutdown
    def handle_sigint(sig, frame):
        print("\npersonalagentkit: SIGINT — setting stop sentinel for clean shutdown...", flush=True)
        (repo_root / ".personalagentkit-stop").touch()
        dispatcher._stop_requested = True

    def handle_sigterm(sig, frame):
        print("\npersonalagentkit: SIGTERM — setting stop sentinel for clean shutdown...", flush=True)
        dispatcher._stop_requested = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigterm)

    dispatcher.run()


if __name__ == "__main__":
    main()
