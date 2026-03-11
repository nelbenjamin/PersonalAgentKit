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
./personalagentkit-genesis          # defaults to claude
./personalagentkit-genesis codex    # use codex as the default driver
```

Genesis reads `../setup/charter.md`. The optional argument sets the driver
for genesis and becomes the default for all subsequent runs. It takes a few
minutes. The agent will name itself, write its first memory, and leave you
a message in `coordinator/inbox/`.

## Drivers

The kit ships with `claude` and `codex` drivers. Pass the driver name to
genesis to select it:

```bash
./personalagentkit-genesis claude   # Claude Code (default)
./personalagentkit-genesis codex    # OpenAI Codex
```

Per-goal routing is also supported via frontmatter:

```markdown
---
driver: codex
---
# My goal
```

Additional drivers can be added as `runner/drivers/<name>_driver.py` plugins.

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
and place your API key in `secrets/agentmail-api-key.txt` in the garden before
running `./hooks/setup-agentmail.sh` or first-use Agentmail hooks. The agent
will find the skill documentation at
`shared/skills/agentmail.md`, discover or create the shared inbox from the
Agentmail API, and persist the non-secret result in `config/agentmail.env`.

## License

MIT
