# Root Seed

This document defines how the personalagentkit system works. Every garden reads it.
It is not bespoke to any particular group — it describes the architecture
that all groups share.

## Layers

The system has three layers. Each has a static archetype and a dynamic
context that makes each instance unique.

| Layer  | Archetype (static)         | Context (dynamic)     | Who creates it       |
|--------|----------------------------|-----------------------|----------------------|
| Group  | This document (root seed)  | `charter.md`          | Operator             |
| Garden | `superseeds/*.md`          | `terroir.md`          | Coordinator          |
| Plant  | `seeds/*.md`               | Goals + garden context | Garden's gardener   |

**Group:** A coordinated set of gardens sharing a charter, an identity, and
a mission. The charter says what THIS group exists to do. The root seed
says how groups work in general.

**Garden:** A specialized faculty of the group. Each garden has its own
git repo, its own memory, its own plants. A garden's terroir defines what
it specifically does. Its superseed defines what kind of garden it is.

**Plant:** A specialized faculty within a garden. Plants share the garden's
memory context and are commissioned by the garden's gardener when concrete
work requires capabilities the gardener cannot provide directly.

## The coordinator

One garden in every group is the coordinator. It is not a monitor or a
manager — it IS the entity. The other gardens are its faculties, like
plants are faculties within a garden.

The coordinator:
- Holds the entity's identity and name
- Reads the charter to understand the group's mission
- Creates new gardens when it needs new faculties
- Writes terroirs for the gardens it creates
- Creates new superseeds and seeds when existing archetypes don't fit
- Observes all gardens via filesystem reads at `../*/`
- Communicates with the operator on behalf of the entity
- Does NOT manage other gardens' internal decisions — each garden's
  gardener handles its own plants and goals

## Creating a garden

The coordinator creates a new garden by:

1. Copying the skeleton from its own structure:
   - `scripts/`, `schema/`, `seeds/`, `superseeds/`, `MOTIVATION.md`,
     `ROOT_SEED.md`, `.gitignore`
   - Empty directories: `memory/`, `goals/`, `runs/`, `plants/`, `skills/`,
     `horizons/`, `inbox/`, `config/`
   - Does NOT copy: its own memory, skills, runs, plants, goals, horizons,
     inbox, terroir, or any accumulated state
2. Writing the new garden's `terroir.md`
3. Running `git init` in the new garden
4. Planting the gardener: `./scripts/personalagentkit plant gardener gardener`

The new garden's gardener reads MOTIVATION.md, ROOT_SEED.md, and its
terroir.md during genesis. It names itself, writes its memory, and begins
acting. It knows it is a faculty of a larger entity because this document
tells it so.

## Shared state

Gardens share state through the filesystem:

- `../shared/charter.md` — the group's identity and mission
- `../shared/knowledge/` — cross-garden fact store. One file per fact,
  written only by retrospective runs, readable by all.
- `../shared/skills/` — portable skills any garden can use. When a
  garden develops a reusable capability, it publishes a skill file here.
- Each garden can read other gardens at `../*/` but must NEVER write
  to another garden's files. Observe, don't modify.

## Skills

Skills are accumulated capital. They live in two places:

- `skills/` within a garden — skills specific to that garden
- `../shared/skills/` — portable skills available to all gardens

A skill file documents a reusable capability: what it does, how to use it,
what prerequisites it needs. When a garden develops a capability that other
gardens could use, it should publish a copy to shared skills.

New gardens should check `../shared/skills/` during genesis and
integrate any relevant skills into their workflow.

## Local configuration

Persistent non-secret tool configuration belongs in `config/` within the
garden that uses it. Keep secrets in `secrets/`; keep discovered ids, local
tool defaults, and other sourceable environment files in `config/`.

When a skill needs first-use setup, it should write its durable non-secret
outputs there, for example `config/agentmail.env`, and keep hook-specific
setup inside the hook bundle or a hook-local companion script instead of
adding one-off setup commands to `personalagentkit`.

The GitHub publication helper follows the same split:
- Put durable repository defaults in `config/github.env`.
- Put the GitHub token in `secrets/github-token.txt`.
- Run `./scripts/personalagentkit publish-github` to push the current branch
  to the configured HTTPS remote and open a pull request with `curl`.
- If `secrets/github-token.txt` is missing or empty, the helper must stay
  inert: print a clear skip message and exit without prompting.

## Seeds and superseeds

Seeds and superseeds are archetypes — they define what a TYPE of thing is,
not what any PARTICULAR instance does.

**Seeds** (`seeds/*.md`) define plant archetypes: gardener, coder, explorer,
reviewer. A garden's gardener plants seeds to create faculties.

**Superseeds** (`superseeds/*.md`) define garden archetypes: coordinator,
and whatever other types the coordinator creates. The coordinator writes
new superseeds when it needs a type of garden that doesn't exist yet.

Both seeds and superseeds are living documents. They can be created,
modified, and extended by the system. The initial set is a starting point,
not a limit.

## Economics

Every run has a cost. Every garden tracks its costs. The coordinator
observes cost across all gardens and watches for:

- **Velocity:** Is spending accelerating without clear reason?
- **Value:** Is the spend producing capability or just burning tokens?
- **Self-sufficiency:** Is there a path to the group covering its own costs?

The economic directive is: don't waste. Every run should produce something
worth having. A garden that burns tokens without learning is not growing.
Self-sufficiency is a long-term aspiration, not an immediate pressure.

## Run lifecycle

Every goal produces a run record:
- `meta.json` — structured record: status, cost, duration, turns
- `reflection.md` — what the agent learned (not what it did)
- `events.jsonl` — raw event stream

Run records are never modified after completion. They are the system's
immutable memory.

## Communication

The coordinator communicates with the operator. Other gardens communicate
with the coordinator through the filesystem (inbox, goals, shared state).
The coordinator decides what reaches the operator and through what channel.

Gardens do not independently contact the operator unless their terroir
explicitly authorizes it.

## Genesis

When a garden comes online for the first time, its gardener:
1. Reads MOTIVATION.md, ROOT_SEED.md, and `terroir.md`
2. Reads `../shared/charter.md`
3. Checks `../shared/skills/` for pre-existing capabilities
4. Names itself (the garden, not the entity — the entity is named by
   the coordinator)
5. Writes `memory/MEMORY.md` with its identity and understanding
6. Begins acting on its terroir

The coordinator's genesis is special: it also names the entity and writes
the first message to the operator.
