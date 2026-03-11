#!/usr/bin/env bash
# interval: 300

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export REPO_ROOT
export AGENTMAIL_API_KEY_FILE="${AGENTMAIL_API_KEY_FILE:-$REPO_ROOT/secrets/agentmail-api-key.txt}"
export AGENTMAIL_INBOX_DIR="${AGENTMAIL_INBOX_DIR:-$REPO_ROOT/inbox}"
export AGENTMAIL_CONFIG_FILE="${AGENTMAIL_CONFIG_FILE:-$REPO_ROOT/config/agentmail.env}"
export AGENTMAIL_BASE_URL="${AGENTMAIL_BASE_URL:-https://api.agentmail.to/v0}"
export AGENTMAIL_INBOX_ID="${AGENTMAIL_INBOX_ID:-}"

if [[ -z "$AGENTMAIL_INBOX_ID" && -f "$AGENTMAIL_CONFIG_FILE" ]]; then
  # Persistent non-secret tool config belongs in config/.
  # Source only when the caller did not explicitly override AGENTMAIL_INBOX_ID.
  # shellcheck disable=SC1090
  source "$AGENTMAIL_CONFIG_FILE"
  export AGENTMAIL_INBOX_ID="${AGENTMAIL_INBOX_ID:-}"
fi

if [[ -z "$AGENTMAIL_INBOX_ID" && -x "$REPO_ROOT/hooks/setup-agentmail.sh" ]]; then
  if [[ -s "$AGENTMAIL_API_KEY_FILE" ]]; then
    "$REPO_ROOT/hooks/setup-agentmail.sh"
    if [[ -f "$AGENTMAIL_CONFIG_FILE" ]]; then
      # shellcheck disable=SC1090
      source "$AGENTMAIL_CONFIG_FILE"
      export AGENTMAIL_INBOX_ID="${AGENTMAIL_INBOX_ID:-}"
    fi
  elif [[ -f "$AGENTMAIL_API_KEY_FILE" ]]; then
    echo "fetch-agentmail: Agentmail API key file is empty; leaving hook inert" >&2
  else
    echo "fetch-agentmail: Agentmail API key file not configured; leaving hook inert" >&2
  fi
fi

python3 - <<'PY'
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = lowered.strip("-")
    return lowered or "unknown-sender"


def read_known_message_ids(inbox_dir: Path) -> set[str]:
    known: set[str] = set()
    for path in inbox_dir.glob("*.md"):
        try:
            lines = path.read_text().splitlines()
        except Exception:
            continue
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:40]:
            if line.strip() == "---":
                break
            if line.startswith("message_id:"):
                known.add(line.split(":", 1)[1].strip().strip('"'))
                break
    return known


def next_nnn(inbox_dir: Path) -> int:
    highest = 0
    for path in inbox_dir.glob("*.md"):
        match = re.match(r"^(\d{3,})-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def request_json(url: str, api_key: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


repo_root = Path(os.environ["REPO_ROOT"])
api_key_file = Path(os.environ["AGENTMAIL_API_KEY_FILE"])
inbox_dir = Path(os.environ["AGENTMAIL_INBOX_DIR"])
inbox_id = os.environ["AGENTMAIL_INBOX_ID"].strip()

if not inbox_id:
    print("fetch-agentmail: no inbox id available after config/setup", file=sys.stderr)
    sys.exit(0)

if not api_key_file.exists():
    print(
        f"fetch-agentmail: missing API key file: {api_key_file}",
        file=sys.stderr,
    )
    sys.exit(0)

api_key = api_key_file.read_text().strip()
if not api_key:
    print(
        f"fetch-agentmail: API key file is empty: {api_key_file}",
        file=sys.stderr,
    )
    sys.exit(0)

inbox_dir.mkdir(parents=True, exist_ok=True)
known_ids = read_known_message_ids(inbox_dir)
counter = next_nnn(inbox_dir)

base = os.environ["AGENTMAIL_BASE_URL"].rstrip("/") + "/inboxes"
quoted_inbox = urllib.parse.quote(inbox_id, safe="@")

try:
    listing = request_json(f"{base}/{quoted_inbox}/messages", api_key)
except urllib.error.HTTPError as exc:
    print(f"fetch-agentmail: agentmail HTTP error: {exc.code}", file=sys.stderr)
    sys.exit(2)
except Exception as exc:
    print(f"fetch-agentmail: request failed: {exc}", file=sys.stderr)
    sys.exit(2)

messages = listing.get("messages") or []
new_count = 0

for message in sorted(messages, key=lambda item: item.get("created_at", "")):
    message_id = (message.get("message_id") or "").strip()
    if not message_id or message_id in known_ids:
        continue

    detail = {}
    try:
        quoted_message = urllib.parse.quote(message_id, safe="")
        detail = request_json(f"{base}/{quoted_inbox}/messages/{quoted_message}", api_key)
    except Exception:
        detail = {}

    sender = str(detail.get("from") or message.get("from") or "unknown sender")
    subject = str(detail.get("subject") or message.get("subject") or "")
    created_at = str(detail.get("created_at") or message.get("created_at") or "")
    labels = detail.get("labels") or message.get("labels") or []
    body = (
        detail.get("text")
        or detail.get("body_text")
        or detail.get("body")
        or message.get("preview")
        or ""
    )
    if not isinstance(body, str):
        body = json.dumps(body, indent=2)

    filename = f"{counter:03d}-from-{slugify(sender)}.md"
    content = "\n".join(
        [
            "---",
            f"message_id: {json.dumps(message_id)}",
            f"from: {json.dumps(sender)}",
            f"subject: {json.dumps(subject)}",
            f"created_at: {json.dumps(created_at)}",
            f"labels: {json.dumps(labels)}",
            'source: "agentmail"',
            "---",
            "",
            body.rstrip(),
            "",
        ]
    )
    (inbox_dir / filename).write_text(content)
    print(f"fetch-agentmail: wrote {filename}")
    known_ids.add(message_id)
    counter += 1
    new_count += 1

sys.exit(1 if new_count else 0)
PY
