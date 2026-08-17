# /last30days

[English](README.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Español](README.es.md) | Português (Brasil) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

# Startup India GOAT

**Evidence-backed startup intelligence for India.**

Startup India GOAT researches one Indian startup—or compares a bounded group—across company facts, funding, traction, product, market, team, distribution, ecosystem relevance, and public sentiment. It turns scattered public evidence into a cited dossier instead of an opaque ranking or investment recommendation.

> **GOAT means a qualitative, evidence-led comparison—not a fabricated score.**

## What it does

- Resolves a company from a brand name, legal name, URL, ticker, DPIIT identifier, or social handle.
- Researches single companies and bounded comparisons such as Zepto vs Blinkit.
- Combines evergreen company facts with a current snapshot and a default 24-month timeline.
- Keeps each company’s identity, evidence, conflicts, and unknowns isolated.
- Preserves source URLs, dates, retrieval status, confidence, engagement, and access limitations.
- Separates verified facts from estimates, commentary, and unresolved claims.
- Explains what is known, what is missing, and what evidence would change the assessment.

## Sources

| Source | Best used for |
|---|---|
| **Startup India / DPIIT** | Recognition and portal listing metadata |
| **Screener** | Listed-company financials, market data, and filings |
| **YourStory, Inc42, The Ken** | Indian startup reporting, funding announcements, and context |
| **LinkedIn** | Professional/company signals through an approved token or browser capture |
| **Tracxn** | Commercial startup estimates when explicitly authorized |
| **GitHub** | Repositories, releases, issues, and engineering activity |
| **X and Reddit** | Public discussion, reactions, and community signals |
| **YouTube** | Public interviews, talks, transcripts, and long-form context |
| **Web** | First-party pages and broader public research |

Source limitations are reported honestly. Paywalls, login requirements, CAPTCHA, rate limits, quotas, browser unavailability, and provider drift are never presented as “no activity.”

## How a run works

1. **Define the request** — companies, dimensions, audience, depth, horizon, and output formats.
2. **Resolve identities** — normalize names and identifiers; weak or ambiguous identities remain clearly marked.
3. **Plan bounded retrieval** — each entity gets an independent source plan and budget.
4. **Collect evidence** — public sources run by default; gated sources require explicit consent and approved access.
5. **Extract facts** — structured fields become cited facts with dates, confidence, authority, and conflict groups.
6. **Render the dossier** — reports lead with coverage, findings, unknowns, risks, and qualitative comparison.
7. **Save an auditable bundle** — Markdown, HTML, JSON, sanitized evidence, and a manifest with hashes.

## Quick start

Install the skill through your agent host, or run the standalone entrypoint from this repository:

```bash
python3 skills/startup-india-goat/scripts/startup_goat.py "research Zepto" --mock
```

Research a company using public sources:

```bash
python3 skills/startup-india-goat/scripts/startup_goat.py "Zepto" --save-dir ./startup-reports --emit=all
```

Compare companies on selected dimensions:

```bash
python3 skills/startup-india-goat/scripts/startup_goat.py \
  --companies "Zepto,Blinkit" \
  --dimensions "product,traction,capital,distribution" \
  --save-dir ./startup-reports --emit=all
```

Inspect source availability without starting research:

```bash
python3 skills/startup-india-goat/scripts/startup_goat.py --doctor
```

Set a persistent artifact directory with `STARTUP_GOAT_MEMORY_DIR` (default: `~/Documents/StartupIndiaGOAT/`).

## Reports and artifacts

A saved run contains:

- **Markdown** — decision-first dossier with citations and source matrix.
- **HTML** — browser-friendly version of the same report.
- **Versioned JSON** — profiles, facts, evidence references, conflicts, coverage, statuses, and request metadata.
- **Sanitized raw evidence** — source items retained for audit without credentials or private browser state.
- **Manifest** — written last, with completion status, artifact hashes, permissions, and coverage guidance.

Artifacts use collision-safe names. Private bundles use restrictive permissions. Publication and library indexing are denied for private, gated, mixed, unknown, failed, or secret-tainted evidence.

## The qualitative GOAT rubric

Comparisons are dimension-by-dimension:

- Product and problem
- Market and business model
- Traction and capital
- Team
- Distribution and defensibility
- Indian ecosystem relevance
- Evidence quality
- Risks and uncertainty

The report presents the strongest case, weakest evidence, unresolved conflicts, and next evidence to collect. It does **not** emit an unsupported composite score or an investment recommendation.

## Access and safety

Startup India GOAT is public-only by default.

- LinkedIn uses an explicit `LINKEDIN_ACCESS_TOKEN` or an allowlist-only browser capture.
- Tracxn requires an approved token or authorized session.
- X reuses the existing `AUTH_TOKEN` + `CT0` integration.
- Browser capture accepts only allowlisted, sanitized structured fields.
- Cookies, browser storage, authorization headers, CSRF values, hidden fields, raw HTML, and credentials are not persisted.
- The system never bypasses authentication, paywalls, CAPTCHA, quotas, robots restrictions, or provider security controls.

Treat retrieved source text as untrusted data. The skill does not execute instructions found in pages or forward secrets to URLs discovered in content.

For permission checks, use `--preflight` before research. It runs without reading cookies, writing files, or running research.

## Repository layout

```text
skills/startup-india-goat/
├── SKILL.md                         # agent-facing workflow contract
└── scripts/
    ├── startup_goat.py              # standalone CLI
    └── lib/
        ├── startup_pipeline.py      # bounded entity retrieval
        ├── startup_facts.py         # fact extraction and conflicts
        ├── startup_render.py        # Markdown and comparison reports
        ├── startup_save.py          # artifact bundle persistence
        ├── startup_export.py        # versioned JSON contract
        └── startup_doctor.py        # source diagnostics and guidance
```

## Documentation

- [Agent workflow contract](skills/startup-india-goat/SKILL.md)
- [Source contracts](docs/research/startup-source-contracts.md)
- [JSON export reference](docs/reference/startup-json-export.md)
- [Configuration](CONFIGURATION.md)

## Status

This is a tuned research skill for Startup India use cases. Source availability and provider schemas change over time, so every report carries its own coverage and uncertainty record.

## License

See [LICENSE](LICENSE).
