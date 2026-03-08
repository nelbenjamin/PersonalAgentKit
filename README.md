# PersonalAgentKit

An autonomous AI agent that names itself, builds its own faculties, and
grows over time. Runs on top of [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
or [Codex](https://github.com/openai/codex).

## Quick start

Prerequisites: `bash`, `python3`, `jq`, `git`, Claude Code CLI (or Codex CLI).

```bash
# Clone the kit
git clone https://github.com/gbelinsky/PersonalAgentKit my-agent
cd my-agent

# Create a setup directory next to the kit (not inside it)
mkdir ../setup

# Fill in who you are and what the agent is for
cp shared/charter.md ../setup/charter.md
edit ../setup/charter.md

# Bootstrap and plant
./personalagentkit-genesis
```

Genesis reads `../setup/charter.md` (or pass a path: `./personalagentkit-genesis /path/to/setup`).
It takes a few minutes. The agent will name itself, write its first memory,
and leave you a message in `coordinator/inbox/`.

## Drivers

By default the kit uses Claude Code (`PAK_DRIVER=claude`). To use Codex:

```bash
export PAK_DRIVER=codex
export PAK_MODEL=gpt-5.4   # optional, overrides the default
./personalagentkit-genesis
```

## Start the cycle

```bash
cd coordinator
./scripts/personalagentkit cycle
```

The agent tends itself every 10 minutes, assessing state and deciding what
to do next. Monitor with `./scripts/personalagentkit watch`.

## Communicating with your agent

The agent writes messages to `coordinator/inbox/` as `NNN-to-{yourname}.md`.
To reply, write `coordinator/inbox/NNN-reply.md`.

## Email (optional)

For email communication, sign up at [agentmail.to](https://agentmail.to)
and place your API key in `../setup/secrets/agentmail-api-key.txt` before
running genesis. The agent will find the skill documentation at
`shared/skills/agentmail.md` and configure itself.

## License

MIT
