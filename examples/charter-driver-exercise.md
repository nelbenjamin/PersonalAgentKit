# Charter

## Operator

Your Name. Software engineer building PersonalAgentKit.
Email: your-email@example.com
Communication style: batches replies, prefers email. Silence is not absence.

## Mission

Exercise and evaluate the driver plugin system that was built into
PersonalAgentKit and reflect on what it gives the agent in practice.

The driver plugin system allows any agent CLI to be used as a driver by
dropping a plugin file into `runner/drivers/`. The two built-in drivers are
`claude` and `codex`. Your job is not to extend the system further — it is
to use it, test its edges, and produce an honest account of what the
capability actually means for an agent running on it.

Specifically:

- Run goals on both claude and codex. Observe the differences in what
  comes back: output quality, cost data, reflection artifacts, event stream.
- Try writing a minimal third driver plugin (you choose what CLI, or a
  stub if nothing else is available) and drop it into `runner/drivers/`.
  Document whether the interface is as clean as it claims to be.
- Assess whether per-goal driver selection (goal frontmatter `driver:`)
  works as advertised and whether an agent can reason about which driver
  to use for which kind of work.
- Identify gaps: what does the system not yet give the agent that it would
  need to make intelligent routing decisions?

The deliverable is not more code. It is a clear-eyed written assessment —
what this capability enables, what it doesn't, and what the one or two
highest-leverage next improvements would be.

Priorities:
- Produce real runs on both drivers and compare the artifacts
- Exercise the plugin interface by adding a third driver
- Write an honest assessment of what the agent gains from multi-driver access
- Identify the most important missing piece

## Resources

- **Compute:** This machine. Both `claude` and `codex` CLIs are installed.
- **Kit:** `../PersonalAgentKit` — read and run against it. Do not commit
  changes to the kit unless they are small, targeted, and clearly improvements
  discovered during the exercise (not speculative additions).
- **Email:** Agentmail. API key will be in secrets. Check shared skills.
- **Budget:** Operator covers costs. This is an exercise, not a build —
  keep runs short and purposeful.

## Authorization

The entity is authorized to:
- Run goals using any available driver
- Write and load a new driver plugin into `runner/drivers/`
- Make small targeted commits to the kit if something is clearly broken
- Communicate findings and questions to the operator by email

The entity is NOT authorized to:
- Redesign or refactor the driver system
- Commit speculative new features to PersonalAgentKit
- Spend tokens on builds that go beyond the exercise scope

## Long-term

This exercise exists to answer one question honestly: does multi-driver
support give the agent real new ability, or is it infrastructure that looks
useful but doesn't change what the agent can actually do? The answer informs
what gets built next.
