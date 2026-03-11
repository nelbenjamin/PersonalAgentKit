# Dispatcher Hooks

Dispatcher hooks are optional executable files placed in `hooks/`.

Contract:

- The dispatcher rescans `hooks/` while it is running. Adding a new executable
  hook does not require a dispatcher restart.
- Declare the polling interval in a header comment:

  ```sh
  # interval: 300
  ```

- If no interval is declared, the dispatcher uses the garden tend interval.
- Exit `0` when nothing happened.
- Exit `1` when something actionable happened. The hook should write its result
  somewhere the agent will see it, usually `inbox/`.
- Any other exit code or unhandled error is logged and ignored. Hook failures
  are non-fatal.

Notes:

- Hooks do not consume dispatcher worker slots.
- Hook schedules are tracked in memory. Restarting the dispatcher resets the
  per-hook timer state.
- Gardens without a `hooks/` directory keep the legacy behavior unchanged.
- Existing `scripts/read-email` polling still works for older gardens; hooks are
  the extensible path for new background checks.

Reference template:

- `hooks/fetch-agentmail.sh` reads Agentmail using the shared
  `secrets/agentmail-api-key.txt` convention.
- It sources `config/agentmail.env` when present.
- On first use, it can run its companion `hooks/setup-agentmail.sh`
  to discover or create the shared inbox from the Agentmail API and persist
  `config/agentmail.env` without adding setup logic to `personalagentkit`.
- `hooks/setup-agentmail.sh` ignores older agent-specific inboxes and uses one
  shared inbox for the whole group, keyed by a fixed Agentmail `client_id`.
- If shared-inbox creation fails, the companion setup falls back to the first
  listed inbox; if no usable inbox can be listed, it prints manual
  `config/agentmail.env` guidance to stderr and exits `0` so the optional hook
  stays inert.
- An explicit `AGENTMAIL_INBOX_ID` environment variable still overrides the
  persisted config for older gardens or one-off debugging.

Related helper:

- `./scripts/personalagentkit publish-github` reads repository defaults from
  `config/github.env` and the token from `secrets/github-token.txt`.
- It only pushes the current branch to the configured HTTPS remote and opens a
  pull request with `curl`; it does not introduce broader release automation.
- If `secrets/github-token.txt` is missing or empty, it prints a skip message
  and exits without prompting.
