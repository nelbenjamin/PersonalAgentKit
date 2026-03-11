---
name: agentmail
description: Send and receive email via the Agentmail API
user-invocable: false
personalagentkit-source: native
personalagentkit-trust: reviewed
---
# Skill: Send Email via Agentmail API

## Purpose

Send an email to a recipient using the agentmail.to API. This is the portable,
raw-API version of email sending — no garden-specific scripts required. Any
garden can adapt this pattern.

## Prerequisites

- API key stored in `secrets/agentmail-api-key.txt` (readable by the garden agent)
- Inbox id discoverable from the Agentmail API with the same API key
- Persistent non-secret config should be written under `config/`

## First-use setup

Discover and persist the inbox id before using the raw API directly:

```bash
./hooks/setup-agentmail.sh
source config/agentmail.env
```

`hooks/setup-agentmail.sh` reads `secrets/agentmail-api-key.txt`, calls
`GET /v0/inboxes`, reuses the inbox whose `client_id` is
`personalagentkit-shared-inbox-v1` when present, otherwise creates it with
`POST /v0/inboxes`, and writes `config/agentmail.env` with
`AGENTMAIL_INBOX_ID=...`. If create fails, it falls back to the first listed
inbox. If neither path yields a usable inbox, it prints manual
`config/agentmail.env` guidance and exits `0` so optional hooks stay inert.
This keeps secrets out of `config/` while making the inbox id available to
hooks and future runs.

This setup is intentionally shared across the group. Older per-agent inboxes
can exist in the account, but setup ignores them unless you explicitly set
`AGENTMAIL_INBOX_ID` yourself.

## Send a message

```bash
API_KEY=$(cat /path/to/secrets/agentmail-api-key.txt)
source /path/to/config/agentmail.env

curl -s -X POST "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages/send" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "to": ["recipient@example.com"],
    "subject": "Your subject here",
    "text": "Plain text body here."
  }'
```

Or inline in a shell script:

```bash
API_KEY=$(cat secrets/agentmail-api-key.txt)
source config/agentmail.env
curl -s -X POST "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages/send" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"to\": [\"[operator@email.com]\"], \"subject\": \"[garden] subject\", \"text\": \"Body text.\"}"
```

## Read messages (check for replies)

```bash
API_KEY=$(cat secrets/agentmail-api-key.txt)
source config/agentmail.env

curl -s "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages" \
  -H "Authorization: Bearer ${API_KEY}" | python3 -m json.tool
```

The response is **wrapped**: `{"count": N, "messages": [...]}` — not a flat
list. Extract with `.messages[]` (jq) or `response["messages"]` (Python).

Each message has: `message_id`, `from`, `subject`, `preview`, `labels`,
`created_at`. Use `message_id` (not `id`) to fetch full message content.

**`from` field format**: The `from` field is a display string like
`"[Operator Name] <[operator@email.com]>"`, not a bare email address.
Filtering with exact equality against an address fails; use a substring
or `in` check (e.g., `"[operator@email.com]" in msg["from"].lower()`).

## Fetch a single message

```bash
# Message IDs are RFC 5322 headers like <CAB0dzF8...@mail.gmail.com>
# containing <, >, + — they MUST be URL-encoded before use in a path.
# Python: urllib.parse.quote(msg_id, safe='')
# curl:   use --data-urlencode or encode manually

MSG_ID_ENCODED=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$MESSAGE_ID")

curl -s "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages/${MSG_ID_ENCODED}" \
  -H "Authorization: Bearer ${API_KEY}" | python3 -m json.tool
```

## Reply to a message (thread into existing conversation)

**Use this when replying to a [Operator] message** — it sets correct `In-Reply-To` and
`References` email headers so the reply lands in the same thread in his email client.
Using `/messages/send` instead creates a new thread every time.

```bash
API_KEY=$(cat secrets/agentmail-api-key.txt)
source config/agentmail.env

# MESSAGE_ID is from the inbox file frontmatter (e.g., the message_id of [Operator]'s message)
# It MUST be URL-encoded — contains <, >, @ characters
MSG_ID_ENCODED=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$MESSAGE_ID")

curl -s -X POST "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages/${MSG_ID_ENCODED}/reply" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Reply body here.\"}"
```

The reply endpoint infers recipients from the original message. You can override with
`to`, `cc`, `bcc`, or add `reply_all: true` to reply to all recipients.

**Where to find `MESSAGE_ID`**: The `check-inbox` script writes inbox files with
`message_id:` in the frontmatter. Use that value as the anchor for the reply.

Response contains `message_id` and `thread_id` of the new reply message.

## Verification (genesis test)

On garden genesis, verify email capability works before proceeding:

```bash
./hooks/setup-agentmail.sh

# Send a test email to confirm the skill is operational
API_KEY=$(cat secrets/agentmail-api-key.txt)
source config/agentmail.env
curl -s -X POST "https://api.agentmail.to/v0/inboxes/${AGENTMAIL_INBOX_ID}/messages/send" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"to\": [\"[operator@email.com]\"], \"subject\": \"[garden] email capability confirmed\", \"text\": \"Test send from genesis run. Email skill is operational.\"}"
```

## Notes

- API key should be placed in `secrets/agentmail-api-key.txt` within the garden
- The inbox id is non-secret and should be persisted in `config/agentmail.env`
- `hooks/setup-agentmail.sh` uses one shared inbox for the group, keyed by
  `personalagentkit-shared-inbox-v1`
- `AGENTMAIL_INBOX_ID` in the environment still overrides the config for backward compatibility
- Subject prefix convention: `[garden-name]` for identification when multiple gardens share a channel
- Operator email: `[operator@email.com]`
