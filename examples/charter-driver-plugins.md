# Charter

## Operator

Your Name. Software engineer building PersonalAgentKit.
Email: your-email@example.com
Communication style: batches replies, prefers email. Silence is not absence.

## Mission

Extend PersonalAgentKit with a clean driver plugin system.

A driver is a self-contained plugin that handles three things: invoking an
agent CLI, parsing its event stream into a normalized format, and accounting
for cost. The core runner should not need modification when a new driver is
added. The agent running on the driver should not need to know which driver
it's on — meta.json should be correct and cost should be visible regardless.

The two reference drivers are claude and codex. Both already work in the kit
at `../PersonalAgentKit`. The task is to extract them into a clean interface
and document it so that a new driver can be written without modifying the
runner or restarting the dispatcher.

Cost accounting is a hard requirement:
- If the driver reports USD natively (claude does), use it.
- If the driver only reports token counts (codex does), estimate cost from
  published model pricing. The estimate should be labeled as an estimate.
  Pricing should be fetched from a known source and stored as a versioned
  fact — not hardcoded without provenance.

Priorities:
- Define and document the driver interface (invocation, event parsing,
  output extraction, cost accounting)
- Implement claude and codex as conforming plugins against that interface
- Add per-goal driver selection (goal frontmatter: `driver: codex`)
- Add a `personalagentkit drivers` subcommand showing what's installed
  and available
- Document the interface well enough that the agent could write a new
  driver without operator involvement

## Resources

- **Compute:** This machine. Both `claude` and `codex` CLIs are installed.
- **Kit:** `../PersonalAgentKit` — the git repository. Read it freely.
  All changes go on a feature branch (not main). Create the branch before
  making any commits. Push when a milestone is complete and stable; open
  a pull request for operator review rather than merging directly.
- **Email:** Agentmail. API key will be in secrets. Check shared skills.
- **Budget:** Operator covers costs. Watch velocity. Prefer small working
  increments over large speculative designs.

## Authorization

The entity is authorized to:
- Read and modify `../PersonalAgentKit` on a feature branch
- Commit and push that branch; open pull requests for operator review
- Look up published model pricing from official sources
- Create new gardens for sustained parallel work streams

The entity is NOT authorized to:
- Commit or push directly to the main branch of PersonalAgentKit
- Modify files outside `../PersonalAgentKit` and this group's directories
- Make financial commitments requiring the operator's identity
- Push breaking changes without a working implementation to back them

## Long-term

The driver system should eventually make it straightforward to:
- Run different goals on different drivers based on cost or capability
- Add a new driver (a new CLI tool) by dropping in a plugin file
- Have the agent itself author and test a new driver plugin
