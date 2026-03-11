# Charter

## Operator

Your Name. Software engineer building PersonalAgentKit.
Email: your-email@example.com
Communication style: batches replies, prefers email. Silence is not absence.

## Mission

Extend PersonalAgentKit with a hooks system for the dispatcher.

Right now the dispatcher has hardcoded logic for checking inbox messages during
its idle loop. As the system grows, agents need to introduce new background
checks, fetching email, polling webhooks, watching external sources, without
modifying the dispatcher directly. Modifying the dispatcher requires a restart,
which is risky for a running agent.

The solution is a `hooks/` directory in the coordinator. The dispatcher runs
each hook script on its own schedule, tracks last-run time per hook, and treats
any actionable output as a signal to tend. The agent drops a new hook script
in and it gets picked up on the next cycle. No dispatcher modification, no
restart.

## Hook interface

A hook is an executable script (shell or python) in `coordinator/hooks/`.

It declares its polling interval in a header comment:

```
# interval: 300
```

The dispatcher reads this and only runs the hook when the interval has elapsed
since its last run. If no interval is declared, default to the tend interval.

The hook's exit code signals the result:
- Exit 0: nothing to do, dispatcher continues
- Exit 1: something actionable happened

A hook that exits 1 should leave its result somewhere the agent will find it,
the natural place is `inbox/` as a new message file. The dispatcher logs the
signal and triggers a tend.

A hook that errors (unhandled exception, bad exit) is logged and skipped. No
retry. The hook is responsible for its own error handling.

## What to build

1. Dispatcher changes in `templates/garden/scripts/dispatch.py`:
   - On each cycle, scan `hooks/` for executable scripts
   - Per hook, check last-run time against declared interval
   - Run eligible hooks, log output, trigger tend if any exit 1
   - Track last-run times in memory (not on disk, resets on restart is fine)

2. A reference hook at `templates/garden/hooks/fetch-agentmail.sh`:
   - Fetches new messages from agentmail using the skill in `shared/skills/`
   - Writes new messages to `inbox/` as `NNN-from-{sender}.md`
   - Exits 1 if new messages were written, 0 if nothing new
   - Interval: 300 (5 minutes)
   - Should be a template the agent can copy and adapt, not a hardcoded
     implementation. The agentmail API key path and inbox format should
     follow existing conventions.

3. Document the hook interface in `templates/garden/MOTIVATION.md` or a
   new `templates/garden/hooks/README.md` so agents know how to write one.

## Constraints

- All changes go on a feature branch, not main. Create the branch before
  the first commit. Name it `feature/dispatcher-hooks`.
- Push when stable. Open a pull request for operator review, do not merge.
- The dispatcher change must be backward compatible. A coordinator with no
  `hooks/` directory should behave identically to today.
- Keep the interface simple. The hook contract is exit code plus whatever
  the hook puts in inbox. Do not add a return format, schema, or callback
  mechanism.
- The reference hook should be a working template, not pseudocode. Test it
  against the agentmail skill before committing.

## Resources

- **Kit:** `../PersonalAgentKit` — read freely, all changes on the feature branch
- **Agentmail skill:** `shared/skills/agentmail.md` — reference for the hook template
- **Dispatcher:** `templates/garden/scripts/dispatch.py` — the file to modify
- **Compute:** This machine. claude and codex CLIs are installed.
- **Email:** Agentmail. API key in secrets. Check shared skills.
- **Budget:** Operator covers costs. Watch velocity.

## Authorization

The entity is authorized to:
- Read and modify `../PersonalAgentKit` on the feature branch
- Commit and push the branch, open a pull request for operator review
- Read `shared/skills/agentmail.md` and test against the agentmail API

The entity is NOT authorized to:
- Commit or push directly to main
- Modify files outside `../PersonalAgentKit` and this group's directories
- Add complexity beyond what the interface requires
