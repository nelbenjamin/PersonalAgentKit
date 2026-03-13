#!/usr/bin/env python3
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def scaffold_repo(tmp_root: Path):
    for rel in ["goals", "runs", "inbox", "tmp", "scripts", "schema", "runner"]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    shutil.copy2(REPO_ROOT / "scripts" / "dispatch.py", tmp_root / "scripts" / "dispatch.py")
    shutil.copy2(REPO_ROOT / "schema" / "run.schema.json", tmp_root / "schema" / "run.schema.json")
    shutil.copytree(REPO_ROOT / "runner", tmp_root / "runner", dirs_exist_ok=True)
    write_file(
        tmp_root.parent / "shared" / "charter.md",
        "# Charter\n\n## Operator\n\nGabriel Example\nEmail: operator@example.com\n",
    )


def scaffold_agentmail_repo(tmp_root: Path):
    scaffold_repo(tmp_root)
    for rel in ["config", "hooks", "memory", "secrets"]:
        (tmp_root / rel).mkdir(parents=True, exist_ok=True)

    shutil.copy2(REPO_ROOT / "scripts" / "personalagentkit", tmp_root / "scripts" / "personalagentkit")
    shutil.copy2(REPO_ROOT / "hooks" / "fetch-agentmail.sh", tmp_root / "hooks" / "fetch-agentmail.sh")
    shutil.copy2(REPO_ROOT / "hooks" / "setup-agentmail.sh", tmp_root / "hooks" / "setup-agentmail.sh")
    (tmp_root / "scripts" / "personalagentkit").chmod(
        (tmp_root / "scripts" / "personalagentkit").stat().st_mode | stat.S_IXUSR
    )
    (tmp_root / "hooks" / "fetch-agentmail.sh").chmod(
        (tmp_root / "hooks" / "fetch-agentmail.sh").stat().st_mode | stat.S_IXUSR
    )
    (tmp_root / "hooks" / "setup-agentmail.sh").chmod(
        (tmp_root / "hooks" / "setup-agentmail.sh").stat().st_mode | stat.S_IXUSR
    )


def assert_equal(actual, expected, message: str):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def run_cmd(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(args, cwd=cwd, env=command_env, text=True, capture_output=True)


class AgentmailHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        state = self.server.state

        if parsed.path == "/v0/inboxes":
            self._send_json(
                {
                    "count": len(state["inboxes"]),
                    "inboxes": state["inboxes"],
                }
            )
            return

        for inbox in state["inboxes"]:
            inbox_id = inbox["inbox_id"]
            inbox_path = f"/v0/inboxes/{urllib.parse.quote(inbox_id, safe='@')}"
            messages = state["messages"].get(inbox_id, [])

            if parsed.path == f"{inbox_path}/messages":
                self._send_json({"count": len(messages), "messages": messages})
                return

            for message in messages:
                message_path = urllib.parse.quote(message["message_id"], safe="")
                if parsed.path == f"{inbox_path}/messages/{message_path}":
                    self._send_json(state["details"][inbox_id][message["message_id"]])
                    return

        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        state = self.server.state

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw_body.decode() or "{}")

        for inbox in state["inboxes"]:
            inbox_id = inbox["inbox_id"]
            inbox_path = f"/v0/inboxes/{urllib.parse.quote(inbox_id, safe='@')}"
            if parsed.path == f"{inbox_path}/messages/send":
                state["sent_messages"].append(
                    {
                        "inbox_id": inbox_id,
                        "payload": payload,
                    }
                )
                self._send_json(
                    {
                        "message_id": f"<sent-{len(state['sent_messages'])}@example.com>",
                        "thread_id": f"thread-sent-{len(state['sent_messages'])}",
                    }
                )
                return

        if parsed.path != "/v0/inboxes":
            self.send_error(404)
            return

        client_id = payload.get("client_id")
        if state.get("create_status") is not None:
            self.send_error(state["create_status"])
            return
        for inbox in state["inboxes"]:
            if inbox.get("client_id") == client_id and client_id:
                state["create_requests"].append(payload)
                self._send_json(inbox)
                return

        inbox = {
            "inbox_id": "pak-shared@agentmail.to",
            "display_name": payload.get("display_name"),
            "created_at": "2026-03-10T00:10:00Z",
            "updated_at": "2026-03-10T00:10:00Z",
            "client_id": client_id,
        }
        state["inboxes"].append(inbox)
        state["messages"]["pak-shared@agentmail.to"] = [
            {
                "message_id": "<message-3@example.com>",
                "from": "Operator <operator@example.com>",
                "subject": "Shared inbox test",
                "preview": "shared preview",
                "labels": ["inbox"],
                "thread_id": "thread-shared",
                "created_at": "2026-03-10T00:10:00Z",
            }
        ]
        state["details"]["pak-shared@agentmail.to"] = {
            "<message-3@example.com>": {
                "message_id": "<message-3@example.com>",
                "from": "Operator <operator@example.com>",
                "subject": "Shared inbox test",
                "text": "shared detail",
                "labels": ["inbox"],
                "thread_id": "thread-shared",
                "created_at": "2026-03-10T00:10:00Z",
            }
        }
        state["create_requests"].append(payload)
        self._send_json(inbox)

    def log_message(self, format, *args):
        return

    def _send_json(self, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class AgentmailServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), AgentmailHandler)
        self.state = {
            "inboxes": [
                {
                    "inbox_id": "defiantcircle232@agentmail.to",
                    "display_name": "AgentMail",
                    "created_at": "2026-03-09T00:00:00Z",
                    "updated_at": "2026-03-09T00:00:00Z",
                    "client_id": None,
                },
                {
                    "inbox_id": "cipher-agent@agentmail.to",
                    "display_name": "AgentMail",
                    "created_at": "2026-03-10T00:00:00Z",
                    "updated_at": "2026-03-10T00:00:00Z",
                    "client_id": None,
                },
                {
                    "inbox_id": "agent-cipher@agentmail.to",
                    "display_name": "AgentMail",
                    "created_at": "2026-03-10T00:00:01Z",
                    "updated_at": "2026-03-10T00:00:01Z",
                    "client_id": None,
                },
                {
                    "inbox_id": "override-choice@agentmail.to",
                    "display_name": "AgentMail",
                    "created_at": "2026-03-10T00:00:02Z",
                    "updated_at": "2026-03-10T00:00:02Z",
                    "client_id": None,
                },
            ],
            "messages": {
                "override-choice@agentmail.to": [
                    {
                        "message_id": "<message-2@example.com>",
                        "from": "Operator <operator@example.com>",
                        "subject": "Override test",
                        "preview": "override preview",
                        "labels": ["inbox"],
                        "thread_id": "thread-override",
                        "created_at": "2026-03-10T00:05:00Z",
                    }
                ],
            },
            "details": {
                "override-choice@agentmail.to": {
                    "<message-2@example.com>": {
                        "message_id": "<message-2@example.com>",
                        "from": "Operator <operator@example.com>",
                        "subject": "Override test",
                        "text": "override detail",
                        "labels": ["inbox"],
                        "thread_id": "thread-override",
                        "created_at": "2026-03-10T00:05:00Z",
                    }
                },
            },
            "create_requests": [],
            "create_status": None,
            "sent_messages": [],
        }


def main():
    dispatch = load_module(REPO_ROOT / "scripts" / "dispatch.py", "dispatch_hooks")
    agentmail_server = AgentmailServer()
    agentmail_thread = threading.Thread(target=agentmail_server.serve_forever, daemon=True)
    agentmail_thread.start()
    agentmail_base_url = f"http://127.0.0.1:{agentmail_server.server_port}/v0"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_repo(repo_root)

            dispatcher = dispatch.Dispatcher(
                repo_root=repo_root,
                max_workers=1,
                tend_interval=30,
                max_cost=None,
                retro_interval=3600,
            )

            assert_equal(dispatcher._discover_hooks(), [], "no hooks directory should be a no-op")
            assert_equal(dispatcher._run_hooks(now=100.0), False, "no hooks should produce no signal")

            write_file(
                repo_root / "hooks" / "interval-hook.sh",
                "#!/usr/bin/env bash\n# interval: 10\nprintf run >> tmp/hook.log\n",
                executable=True,
            )
            write_file(
                repo_root / "hooks" / "ignored.txt",
                "# interval: 1\nprintf ignored >> tmp/hook.log\n",
                executable=False,
            )

            assert_equal(dispatcher._run_hooks(now=110.0), False, "interval hook should not signal work")
            assert_equal((repo_root / "tmp" / "hook.log").read_text(), "run", "executable hook should run")

            assert_equal(dispatcher._run_hooks(now=115.0), False, "hook should respect interval")
            assert_equal(
                (repo_root / "tmp" / "hook.log").read_text(),
                "run",
                "hook should not rerun before interval",
            )

            assert_equal(dispatcher._run_hooks(now=121.0), False, "hook should rerun after interval")
            assert_equal(
                (repo_root / "tmp" / "hook.log").read_text(),
                "runrun",
                "hook should rerun once interval elapses",
            )

            write_file(
                repo_root / "hooks" / "actionable.sh",
                "#!/usr/bin/env bash\n# interval: 5\necho hello > inbox/001-from-test.md\nexit 1\n",
                executable=True,
            )
            assert_equal(dispatcher._run_hooks(now=122.0), True, "exit 1 should signal actionable work")
            assert (repo_root / "inbox" / "001-from-test.md").exists()

            write_file(
                repo_root / "hooks" / "broken.sh",
                "#!/usr/bin/env bash\n# interval: 1\nexit 7\n",
                executable=True,
            )
            assert_equal(dispatcher._run_hooks(now=123.0), False, "unexpected hook exits are non-fatal")

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_repo(repo_root)

            write_file(
                repo_root / "hooks" / "during-sleep.sh",
                """#!/usr/bin/env bash
# interval: 2
mkdir -p tmp
count=0
if [ -f tmp/sleep-hook-count ]; then
  count=$(cat tmp/sleep-hook-count)
fi
count=$((count + 1))
printf '%s\n' "$count" > tmp/sleep-hook-count
printf run\\n >> tmp/sleep-hook.log
if [ "$count" -ge 2 ]; then
  touch .personalagentkit-stop
fi
""",
                executable=True,
            )

            dispatcher = dispatch.Dispatcher(
                repo_root=repo_root,
                max_workers=1,
                tend_interval=30,
                max_cost=None,
                retro_interval=3600,
            )
            wake_at = datetime.now(timezone.utc) + timedelta(seconds=4)

            dispatcher._surface_inbox = lambda: None
            dispatcher._gardener_thread = lambda: None
            dispatcher._retrospective_thread = lambda: None
            dispatcher._fill_slots = lambda entries: 0
            dispatcher._scan_queue = lambda: ([], 1, wake_at)

            thread = threading.Thread(target=dispatcher.run, daemon=True)
            thread.start()
            thread.join(timeout=15)
            if thread.is_alive():
                raise AssertionError("dispatcher did not exit after hook-triggered stop")

            sleep_hook_count = repo_root / "tmp" / "sleep-hook-count"
            assert sleep_hook_count.exists(), "time-gated wait hook should have run"
            runs = int(sleep_hook_count.read_text().strip())
            if runs < 2:
                raise AssertionError(
                    f"time-gated wait should continue polling hooks: expected >=2 runs, got {runs}"
                )

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(
                repo_root / "memory" / "MEMORY.md",
                "# Coordinator Notes\n\nKeep inbox selection deterministic.\n\nI am Cipher.\n",
            )

            setup_result = run_cmd(
                [str(repo_root / "hooks" / "setup-agentmail.sh")],
                cwd=repo_root,
                env={"AGENTMAIL_BASE_URL": agentmail_base_url},
            )
            assert_equal(
                setup_result.returncode,
                0,
                "hook-owned setup should create a shared inbox when only agent-specific inboxes exist",
            )
            config_file = repo_root / "config" / "agentmail.env"
            assert config_file.exists(), "hook-owned setup should create config/agentmail.env"
            config_text = config_file.read_text()
            assert "AGENTMAIL_INBOX_ID=pak-shared@agentmail.to" in config_text
            assert "setup via hooks/setup-agentmail.sh ready" in setup_result.stdout
            assert "create failure falls back to first listed inbox" in setup_result.stdout
            assert_equal(
                len(agentmail_server.state["create_requests"]),
                1,
                "hook-owned setup should create the shared inbox exactly once",
            )
            assert_equal(
                agentmail_server.state["create_requests"][0]["client_id"],
                "personalagentkit-shared-inbox-v1",
                "hook-owned setup should use the fixed shared inbox client_id",
            )

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            config_file = repo_root / "config" / "agentmail.env"
            write_file(
                config_file,
                "export AGENTMAIL_INBOX_ID=pak-shared@agentmail.to\n",
            )

            setup_result = run_cmd(
                [str(repo_root / "hooks" / "setup-agentmail.sh")],
                cwd=repo_root,
                env={"AGENTMAIL_BASE_URL": "http://127.0.0.1:9/v0"},
            )
            assert_equal(
                setup_result.returncode,
                0,
                "hook-owned setup should reuse persisted config without re-querying Agentmail",
            )
            assert "AGENTMAIL_INBOX_ID=pak-shared@agentmail.to" in config_file.read_text()

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")

            hook_result = run_cmd(
                [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                cwd=repo_root,
                env={"AGENTMAIL_BASE_URL": agentmail_base_url},
            )
            assert_equal(hook_result.returncode, 1, "fetch-agentmail should signal actionable work")
            config_file = repo_root / "config" / "agentmail.env"
            assert config_file.exists(), "fetch-agentmail should auto-create config/agentmail.env"
            inbox_files = sorted((repo_root / "inbox").glob("*.md"))
            assert_equal(len(inbox_files), 1, "fetch-agentmail should write one inbox file")
            inbox_text = inbox_files[0].read_text()
            assert "message_id: \"<message-3@example.com>\"" in inbox_text
            assert "shared detail" in inbox_text
            assert "setup via hooks/setup-agentmail.sh ready" in hook_result.stdout

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")

            hook_result = run_cmd(
                [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                cwd=repo_root,
                env={"AGENTMAIL_BASE_URL": agentmail_base_url},
            )
            assert_equal(
                hook_result.returncode,
                0,
                "fetch-agentmail should stay inert when no API key or persisted config is available",
            )
            assert not (repo_root / "config" / "agentmail.env").exists(), (
                "missing-key inert path should not create config/agentmail.env"
            )
            assert_equal(
                sorted((repo_root / "inbox").glob("*.md")),
                [],
                "missing-key inert path should not write inbox files",
            )

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            saved_state = copy.deepcopy(agentmail_server.state)
            agentmail_server.state["inboxes"] = [
                inbox
                for inbox in agentmail_server.state["inboxes"]
                if inbox["inbox_id"] != "pak-shared@agentmail.to"
            ]
            agentmail_server.state["create_status"] = 422
            agentmail_server.state["messages"]["defiantcircle232@agentmail.to"] = [
                {
                    "message_id": "<message-1@example.com>",
                    "from": "Operator <operator@example.com>",
                    "subject": "Fallback inbox test",
                    "preview": "fallback preview",
                    "labels": ["inbox"],
                    "created_at": "2026-03-09T00:10:00Z",
                }
            ]
            agentmail_server.state["details"]["defiantcircle232@agentmail.to"] = {
                "<message-1@example.com>": {
                    "message_id": "<message-1@example.com>",
                    "from": "Operator <operator@example.com>",
                    "subject": "Fallback inbox test",
                    "text": "fallback detail",
                    "labels": ["inbox"],
                    "created_at": "2026-03-09T00:10:00Z",
                }
            }

            try:
                hook_result = run_cmd(
                    [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                    cwd=repo_root,
                    env={"AGENTMAIL_BASE_URL": agentmail_base_url},
                )
            finally:
                agentmail_server.state.clear()
                agentmail_server.state.update(saved_state)
            assert_equal(
                hook_result.returncode,
                1,
                "fetch-agentmail should fall back to the first listed inbox when shared inbox create fails",
            )
            assert "source=fallback:list-first" in hook_result.stdout
            config_text = (repo_root / "config" / "agentmail.env").read_text()
            assert "AGENTMAIL_INBOX_ID=defiantcircle232@agentmail.to" in config_text
            inbox_files = sorted((repo_root / "inbox").glob("*.md"))
            assert_equal(len(inbox_files), 1, "fallback inbox path should still fetch one message")
            assert "fallback detail" in inbox_files[0].read_text()

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            saved_state = copy.deepcopy(agentmail_server.state)
            agentmail_server.state["inboxes"] = []
            agentmail_server.state["create_status"] = 422

            try:
                hook_result = run_cmd(
                    [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                    cwd=repo_root,
                    env={"AGENTMAIL_BASE_URL": agentmail_base_url},
                )
            finally:
                agentmail_server.state.clear()
                agentmail_server.state.update(saved_state)
            assert_equal(
                hook_result.returncode,
                0,
                "fetch-agentmail should stay inert when setup cannot create or list any inbox",
            )
            assert "export AGENTMAIL_INBOX_ID=<id>" in hook_result.stderr
            assert "config/agentmail.env" in hook_result.stderr
            assert not (repo_root / "config" / "agentmail.env").exists()
            assert_equal(sorted((repo_root / "inbox").glob("*.md")), [], "manual-config inert path should not write inbox files")

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            write_file(repo_root / "inbox" / "001-to-gabriel.md", "Question for Gabriel\n")
            saved_state = copy.deepcopy(agentmail_server.state)
            agentmail_server.state["inboxes"] = [
                {
                    "inbox_id": "pak-shared@agentmail.to",
                    "display_name": "AgentMail",
                    "created_at": "2026-03-10T00:00:00Z",
                    "updated_at": "2026-03-10T00:00:00Z",
                    "client_id": "personalagentkit-shared-inbox-v1",
                }
            ]
            agentmail_server.state["messages"]["pak-shared@agentmail.to"] = [
                {
                    "message_id": "<sent-message@example.com>",
                    "from": "PersonalAgentKit Shared Inbox <pak-shared@agentmail.to>",
                    "subject": "[coordinator] Question",
                    "preview": "Question for Gabriel",
                    "labels": ["sent"],
                    "thread_id": "thread-reply",
                    "created_at": "2026-03-10T00:10:00Z",
                },
                {
                    "message_id": "<reply-message@example.com>",
                    "from": "Gabriel Example <operator@example.com>",
                    "subject": "Re: [coordinator] Question",
                    "preview": "Real reply body",
                    "labels": ["inbox"],
                    "thread_id": "thread-reply",
                    "created_at": "2026-03-10T00:11:00Z",
                },
                {
                    "message_id": "<unrelated-message@example.com>",
                    "from": "Another Person <another@example.com>",
                    "subject": "Unrelated inbound",
                    "preview": "Unrelated note",
                    "labels": ["inbox"],
                    "thread_id": "thread-other",
                    "created_at": "2026-03-10T00:12:00Z",
                },
            ]
            agentmail_server.state["details"]["pak-shared@agentmail.to"] = {
                "<sent-message@example.com>": {
                    "message_id": "<sent-message@example.com>",
                    "from": "PersonalAgentKit Shared Inbox <pak-shared@agentmail.to>",
                    "subject": "[coordinator] Question",
                    "text": "Question for Gabriel\n",
                    "labels": ["sent"],
                    "thread_id": "thread-reply",
                    "created_at": "2026-03-10T00:10:00Z",
                },
                "<reply-message@example.com>": {
                    "message_id": "<reply-message@example.com>",
                    "from": "Gabriel Example <operator@example.com>",
                    "subject": "Re: [coordinator] Question",
                    "text": "Real reply body\n",
                    "labels": ["inbox"],
                    "thread_id": "thread-reply",
                    "created_at": "2026-03-10T00:11:00Z",
                },
                "<unrelated-message@example.com>": {
                    "message_id": "<unrelated-message@example.com>",
                    "from": "Another Person <another@example.com>",
                    "subject": "Unrelated inbound",
                    "text": "Unrelated note\n",
                    "labels": ["inbox"],
                    "thread_id": "thread-other",
                    "created_at": "2026-03-10T00:12:00Z",
                },
            }

            try:
                hook_result = run_cmd(
                    [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                    cwd=repo_root,
                    env={"AGENTMAIL_BASE_URL": agentmail_base_url},
                )
            finally:
                agentmail_server.state.clear()
                agentmail_server.state.update(saved_state)
            assert_equal(
                hook_result.returncode,
                1,
                "fetch-agentmail should archive operator replies as NNN-reply and preserve unrelated inbound mail",
            )
            reply_file = repo_root / "inbox" / "001-reply.md"
            assert reply_file.exists(), "real operator replies should map back to the pending operator outbox entry"
            reply_text = reply_file.read_text()
            assert "message_id: \"<reply-message@example.com>\"" in reply_text
            assert "thread_id: \"thread-reply\"" in reply_text
            assert "Real reply body" in reply_text
            inbox_files = sorted(path.name for path in (repo_root / "inbox").glob("*.md"))
            assert_equal(
                inbox_files,
                [
                    "001-reply.md",
                    "001-to-gabriel.md",
                    "002-from-personalagentkit-shared-inbox-pak-shared-agentmail-to.md",
                    "003-from-another-person-another-example-com.md",
                ],
                "reply normalization should clear the pending thread without changing generic archiving for other inbound mail",
            )
            dispatcher = dispatch.Dispatcher(
                repo_root=repo_root,
                max_workers=1,
                tend_interval=30,
                max_cost=None,
                retro_interval=3600,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                dispatcher._surface_inbox()
            if "001-to-gabriel.md" in buf.getvalue():
                raise AssertionError("dispatcher tend surfacing should stop showing pending operator mail once reply exists")

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            write_file(
                repo_root / "config" / "agentmail.env",
                "export AGENTMAIL_INBOX_ID=pak-shared@agentmail.to\n",
            )

            hook_result = run_cmd(
                [str(repo_root / "hooks" / "fetch-agentmail.sh")],
                cwd=repo_root,
                env={
                    "AGENTMAIL_BASE_URL": agentmail_base_url,
                    "AGENTMAIL_INBOX_ID": "override-choice@agentmail.to",
                },
            )
            assert_equal(
                hook_result.returncode,
                1,
                "fetch-agentmail should honor explicit AGENTMAIL_INBOX_ID over persisted config",
            )
            inbox_files = sorted((repo_root / "inbox").glob("*.md"))
            assert_equal(len(inbox_files), 1, "override fetch should write one inbox file")
            inbox_text = inbox_files[0].read_text()
            assert "message_id: \"<message-2@example.com>\"" in inbox_text
            assert "override detail" in inbox_text

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)
            write_file(repo_root / "secrets" / "agentmail-api-key.txt", "test-key\n")
            write_file(repo_root / "memory" / "MEMORY.md", "I am Cipher.\n")
            write_file(
                repo_root / "config" / "agentmail.env",
                "export AGENTMAIL_INBOX_ID=pak-shared@agentmail.to\n",
            )

            dispatcher = dispatch.Dispatcher(
                repo_root=repo_root,
                max_workers=1,
                tend_interval=30,
                max_cost=None,
                retro_interval=3600,
            )
            dispatcher._last_completed_run = {
                "run_id": "023-build-idle-operator-email",
                "status": "success",
                "completed_at": "2026-03-12T22:30:00Z",
                "goal_title": "Build Idle Operator Email",
            }

            sent_before = len(agentmail_server.state["sent_messages"])
            old_base_url = os.environ.get("AGENTMAIL_BASE_URL")
            os.environ["AGENTMAIL_BASE_URL"] = agentmail_base_url
            try:
                sent = dispatcher._send_idle_operator_email()
            finally:
                if old_base_url is None:
                    os.environ.pop("AGENTMAIL_BASE_URL", None)
                else:
                    os.environ["AGENTMAIL_BASE_URL"] = old_base_url
            assert_equal(sent, True, "idle-email should send through the existing Agentmail transport")
            sent_after = len(agentmail_server.state["sent_messages"])
            assert_equal(sent_after, sent_before + 1, "idle-email should emit exactly one Agentmail send request")
            payload = agentmail_server.state["sent_messages"][-1]["payload"]
            assert_equal(payload["to"], ["operator@example.com"], "idle-email should target the operator email from the charter")
            assert_equal(
                payload["subject"],
                f"[{repo_root.name}] system idle",
                "idle-email should use a human-readable idle-status subject",
            )
            assert "023-build-idle-operator-email (success)" in payload["text"]
            assert "Build Idle Operator Email" in payload["text"]
            assert "The system is idle." in payload["text"]

        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            scaffold_agentmail_repo(repo_root)

            dispatcher = dispatch.Dispatcher(
                repo_root=repo_root,
                max_workers=1,
                tend_interval=30,
                max_cost=None,
                retro_interval=3600,
            )

            send_calls: list[str] = []

            def fake_send() -> bool:
                send_calls.append(dispatcher._last_completed_run["run_id"])
                return True

            dispatcher._send_idle_operator_email = fake_send
            assert_equal(
                dispatcher._maybe_send_idle_operator_email(),
                False,
                "idle-email should not send before any completion is recorded",
            )

            dispatcher._last_completed_run = {
                "run_id": "010-first",
                "status": "success",
                "completed_at": "2026-03-12T22:00:00Z",
                "goal_title": "First",
            }
            dispatcher._idle_notification_pending = True
            assert_equal(
                dispatcher._maybe_send_idle_operator_email(),
                True,
                "idle-email should send once when the queue first transitions to idle after a completion",
            )
            assert_equal(
                dispatcher._maybe_send_idle_operator_email(),
                False,
                "idle-email should not resend while the system remains idle for the same completion",
            )

            dispatcher._last_completed_run = {
                "run_id": "011-second",
                "status": "failure",
                "completed_at": "2026-03-12T22:10:00Z",
                "goal_title": "Second",
            }
            dispatcher._idle_notification_pending = True
            assert_equal(
                dispatcher._maybe_send_idle_operator_email(),
                True,
                "idle-email should re-arm only after a newer completion occurs",
            )
            assert_equal(
                send_calls,
                ["010-first", "011-second"],
                "idle-email dedupe should key off the most recent completed run",
            )
    finally:
        agentmail_server.shutdown()
        agentmail_server.server_close()

    print("verify_dispatch_hooks: ok")


if __name__ == "__main__":
    main()
