# Charter

## Operator

Your Name. Software engineer building PersonalAgentKit.
Email: your-email@example.com
Communication style: batches replies, prefers email. Silence is not absence.

## Mission

Research the competitive landscape for autonomous AI agent frameworks and
produce a report that informs the future direction of PersonalAgentKit.

This is a pure research goal. No code changes. No improvements to the kit.
The output is a written report.

PersonalAgentKit's philosophy: simple to start, bespoke by design. A single
shell script bootstraps a named agent that grows its own faculties over time.
No API server, no orchestration layer, no cloud dependency. The operator drops
in an API key and gets a running agent. Hooks are shell scripts. Skills are
markdown files. The agent adapts to the operator, not the other way around.

The primary competitor to understand is **openclaw/openclaw** on GitHub.
Research it thoroughly: architecture, design choices, community size, adoption
signals (stars, forks, issues, contributors, release velocity), and what
problems it solves that users respond to. Look for what real users say —
issues, discussions, Reddit posts, Hacker News threads, blog posts.

Then broaden the survey to other frameworks in the same space: AutoGPT,
OpenHands (formerly OpenDevin), CrewAI, Aider, Sweep, Devin (commercial),
and any others with meaningful traction. Same treatment for each: what they
are, what they do well, what users love, what users complain about.

## Deliverables

A single report at `research/competitive-landscape.md` in this garden,
structured as follows:

**1. Framework Survey**
One section per framework. For each: what it is, how it works architecturally,
what the setup experience is like, what the target user is, community size and
health (with numbers and dates), and a short verdict on what it gets right.

**2. Trends and Feature Popularity**
What features and capabilities appear repeatedly across successful frameworks?
What do users ask for most? What do they complain about? Ground every claim
in evidence — link to issues, posts, or discussions. No speculation without a
source.

**3. Competitive Paths for PersonalAgentKit**
Given PersonalAgentKit's approach (simple, bespoke, no server, grows over
time), where is it well-positioned? Where is it weak? What would it take to
be competitive? Be honest about gaps.

**4. Roadmap**
A prioritized list of probable paths, each with:
- What it is
- Why it matters (what evidence supports it)
- Rough horizon: near (weeks), medium (months), long (quarters+)
- Whether it fits the current philosophy or requires a shift

This is not a wishlist — it should be grounded in what the research actually
found.

## Resources

- **Compute:** This machine. `claude` and `codex` CLIs are installed.
- **Kit:** `../PersonalAgentKit` — read freely to understand current state.
  No changes.
- **Web:** Use web search and fetch tools freely. GitHub, Reddit, Hacker News,
  blog posts, documentation sites. Prefer primary sources.
- **Budget:** Operator covers costs. Research thoroughly — don't skim.

## Authorization

The entity is authorized to:
- Read `../PersonalAgentKit` freely
- Search the web, fetch pages, read documentation
- Write the report and any notes to this garden

The entity is NOT authorized to:
- Modify anything in `../PersonalAgentKit`
- Create accounts, send emails, or interact with external services
- Make any commits to the PersonalAgentKit repository

## Constraints

- No code. This is research only.
- All claims in the report must cite a source or be clearly labeled as
  inference.
- The report should be useful to a developer deciding what to build next,
  not to a marketer. Be direct, be honest, acknowledge uncertainty.
