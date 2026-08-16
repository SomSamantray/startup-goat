# Startup India GOAT

`startup-india-goat` is an agent skill for evidence-backed research on one Indian startup or a bounded group of startups. It accepts natural-language requests such as:

- `/startup-india-goat research Zepto`
- `/startup-india-goat compare Zepto and Blinkit on funding, traction, and customer sentiment`
- `/startup-india-goat who is the GOAT among Indian fintech startups?`

The skill combines the existing GitHub, Reddit, X, YouTube, and Web retrieval substrate with dedicated coverage for YourStory, Screener, The Ken, Inc42, Startup India, Tracxn, and LinkedIn when access is explicitly configured.

## Contract

Before retrieval it shows the entities, aliases, dimensions, time horizon, source set, authentication requirements, expected gaps, and output artifacts. Public-only research is the default. Browser cookies, gated sessions, paid providers, and tokens require explicit user consent. Authentication, paywall, CAPTCHA, quota, robots, or provider-drift limitations are reported honestly and never represented as “no activity.”

The default horizon combines evergreen facts with 24 months of dated developments. Group runs preserve per-company evidence and compare only requested dimensions. “GOAT” is a qualitative rubric covering product/problem, market, traction, capital, team, distribution/defensibility, business model, Indian ecosystem relevance, evidence quality, and risks; it does not emit an unsupported composite score.

## Artifacts

Each run saves Markdown, HTML, versioned JSON, sanitized raw evidence, and a manifest. Group runs also save a comparison index and per-company artifacts. Configure the directory with `STARTUP_GOAT_MEMORY_DIR` (default `~/Documents/StartupIndiaGOAT/`). The manifest is written last as the atomic completion marker.

## Installation

Claude Code:

```text
/plugin marketplace add mvanhorn/startup-india-goat-skill
/plugin install startup-india-goat
```

Agent Skills hosts:

```bash
npx skills add mvanhorn/startup-india-goat-skill -g
```

The direct Python engine is a scripting/development fallback; the slash command is the primary interface. See [`skills/startup-india-goat/SKILL.md`](skills/startup-india-goat/SKILL.md) and [`CONFIGURATION.md`](CONFIGURATION.md) for the complete contract and configuration.

## Safety

`--preflight` is a compatibility diagnostic that runs without reading cookies, writing files, or running research. It does not read browser-cookie values. The copied engine's `--no-browser-cookies` default remains fail-closed.

The skill does not bypass authentication, paywalls, CAPTCHAs, quotas, robots restrictions, or provider security controls. Credentials, cookies, private evidence, and browser-session material are never written to citations, logs, prompts, public artifacts, or fixtures.
