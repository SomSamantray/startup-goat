# Configuration

`startup-india-goat` defaults to public-only research. Configuration is optional unless a requested source requires credentials or an explicitly authorized browser session.

## Per-run behavior

The slash command accepts natural language. State the company or companies, dimensions, depth, time horizon, and output audience in the request. Public research may proceed without confirmation. The skill asks before reading browser cookies, using a gated session, or sending data to a paid/third-party provider.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `STARTUP_GOAT_MEMORY_DIR` | Artifact directory; default `~/Documents/StartupIndiaGOAT/`. |
| `AUTH_TOKEN` + `CT0` | Existing X browser-cookie pair, optional and consent-gated. |
| `LINKEDIN_ACCESS_TOKEN` | Explicit LinkedIn bearer token for permitted company research, optional. |
| `TRACXN_ACCESS_TOKEN` | Explicit Tracxn token when supported by the user's plan, optional. |
| `BRAVE_API_KEY` | Optional Web search backend credential. |
| `PARALLEL_API_KEY` | Optional Web search backend credential. |
| `OPENAI_API_KEY` | Optional fallback/agent integration credential. |
| `XAI_API_KEY` | Optional X/Web integration credential. |
| `OPENROUTER_API_KEY` | Optional model/provider credential. |

Secrets must be supplied through the host's secret configuration. Never put real values in prompts, source fixtures, reports, or logs. Missing optional credentials produce a visible coverage limitation rather than a failed claim. If the user explicitly enables the optional ScrapeCreators social enrichment path, its provider documentation advertises 10,000 free calls; this is not required for public-only startup research.

## Direct engine compatibility

The copied engine retains its bounded scripting flags for development and offline tests: `--no-browser-cookies`, `--preflight`, `--save-dir <path>`, `--output`, `--publish-html`, `--publish`, `--publish-password`, and `--record-fixtures`. The equivalent library command is `library feed --publish`; see `docs/reference/eval.md`. `LAST30DAYS_PUBLISH_PASSWORD` is read only through the existing secret configuration path. `LAST30DAYS_REPORT_CACHE_TTL_SECONDS` defaults to `3600`; set it to `0` to disable report-cache reuse.

The reused Reddit backend accepts `LAST30DAYS_REDDIT_BACKEND=scrapecreators` and the thinness floor `LAST30DAYS_REDDIT_SC_MIN_ITEMS`. These are engine compatibility knobs, not requirements for Startup India GOAT public-only research.

## Security compatibility notes

Codex ChatGPT auth is intentionally not used as an OpenAI fallback. Folder-mode hosts such as Codex desktop do not trust hidden project config by default; `LAST30DAYS_TRUST_PROJECT_CONFIG=1` is required for the reused engine's project configuration. Browser-cookie setup is opt-in: `setup --allow-browser-cookies` is the only compatibility path, and unset means no browser-cookie reads.

## Source access states

Reports distinguish `public`, `private-session`, `login-required`, `paywalled`, `captcha`, `quota-exhausted`, `browser-unavailable`, `not-applicable`, and `unknown`, plus retrieval outcomes such as `auth-failed`, `rate-limited`, `timeout`, `unreachable`, and `schema-drift`.

LinkedIn and Tracxn require an explicit token or an allowlist-only browser capture. Browser captures may contain selected visible structured fields and public links only; cookies, storage, headers, request bodies, hidden fields, and raw HTML are rejected. Unset = no browser-cookie reads.

## Artifact policy

The preflight command runs without reading browser cookies, writing setup/config/report files, or running research. It does not read browser-cookie values.

A complete run writes Markdown, HTML, versioned JSON, sanitized raw evidence, and a manifest. Group runs additionally write a comparison index and per-company artifacts. Filenames use deterministic slugs and collision-safe run IDs. The manifest is written last and records partial or failed source outcomes. Private evidence keeps artifacts private.
