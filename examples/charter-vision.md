# Charter

## Operator

Your Name. Software engineer building PersonalAgentKit.
Email: your-email@example.com
Communication style: batches replies, prefers email. Silence is not absence.

## Mission

Write a vision statement and strategic initiatives for PersonalAgentKit.

This is a thinking goal, not a building goal. No code changes. No goals submitted.
The outputs are two documents: `VISION.md` at the coordinator root, and
`reflection.md` in the run directory.

## Operator Philosophy

Hold these as constraints while you work:

- **Personal** — the name says so. One person, not a team. No multi-tenant,
  no admin dashboards, no enterprise features.
- **Apple-like** — narrow and polished. Leave out what doesn't just work. Make
  what does work work exceptionally well.
- **The mom test** — if someone non-technical couldn't pick it up and find it
  valuable without hand-holding, something is wrong.
- **No server sprawl** — local-first, no cloud dependency. Revisit if the market
  forces it.
- **Not autonomy theater** — growth through explicit records, reflection, and
  operator control, not grand claims about what the agent can do unsupervised.

## Method

Work backwards from the user. Not from the code, not from the competitive field.

1. Start with: who is this person, what do they want their agent to do for them,
   what makes them trust it, what makes them recommend it.
2. Then: what does that imply about the product's identity and direction?
3. Then: what 3–5 initiatives follow from that identity?

The research is grounding, not a constraint. Use it to validate or sharpen your
thinking, not to copy-paste conclusions.

## Research Inputs

Read all three before writing anything:

- `/home/agent/competitiveResearch/coordinator/plants/surveyor/runs/003-openclaw-deep-dive/brief.md`
- `/home/agent/competitiveResearch/coordinator/plants/surveyor/runs/004-framework-survey/brief.md`
- `/home/agent/competitiveResearch/coordinator/plants/gardener/runs/013-synthesize-competitive-direction/decision-memo.md`

The decision memo is a synthesis of the two briefs, written by the research
gardener. Treat it as one strong opinion, not as ground truth. You can disagree
with it if your reading of the primary briefs leads somewhere different.

## Deliverables

**1. `VISION.md`** at the coordinator root, structured as:

```
# Vision

## What PersonalAgentKit is for
One paragraph. Plain language. Passes the mom test: a non-technical person
should understand why it exists and why they might want it.

## Who it's for
Two or three sentences. Specific. Not "developers" — sharper than that.

## What we will not be
Two or three sentences. Explicit scope exclusions protect the vision from drift.

## Initiatives
3–5 named initiatives. For each:
  Name: short, memorable
  What: one sentence on what it is
  Why: one sentence on why it matters, grounded in the user picture or research
```

Initiatives are not goals. They are stable directions — specific enough to
derive horizons from, loose enough not to over-specify implementation.

**2. `reflection.md`** in the run directory.

What was genuinely hard about working backwards from user value? What does the
research imply that wasn't obvious before reading it? What is the biggest risk
to this vision?

## Authorization

Read freely:
- `/home/agent/competitiveResearch` (all of it)
- `/home/agent/PersonalAgentKit` (understand current state, no changes)

Write:
- `VISION.md` to the coordinator root
- `reflection.md` to the run directory

Not authorized:
- Submit goals
- Modify any code or configuration
- Make commits
