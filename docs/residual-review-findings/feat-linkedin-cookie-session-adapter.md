# Known Residuals — LinkedIn Cookie-Session Adapter

Review run: ce-code-review on branch `feat/linkedin-cookie-session-adapter` (base `92278c2`), 2026-08-17.

Accepted findings that remain unresolved after the review-fix pass. These are deliberate scope decisions or pre-existing issues not introduced by this change; recorded for durability.

## Accepted residuals

1. **Mid-run cookie expiry has no automatic failover** (adversarial, P3)
   - The plan deliberately chose no-retry on 999/429/authwall (typed access states, no unbounded retries). If a session expires mid-group-run, later entities report `auth-failed`/`rate-limited` and the group is flagged partial. The bearer-token lane is restored as a separate credential path but is not auto-failed-over on auth-failed.
   - Mitigation: the typed outcome (`auth-failed`, `fix_hint: use a fresh cookie set`) tells the user exactly what happened; a re-run with fresh cookies recovers.

2. **Authwall marker set overlaps ordinary product copy** (adversarial, P3)
   - `_AUTHWALL_MARKERS` includes "login required" / "please log in" which can appear in unrelated page text. The adapter mirrors the existing `startup_web` access-marker set, so this is consistent with repo convention. A false authwall yields `auth-failed` (fail-closed), never fabricated evidence.

3. **Page-post items carry `url=''`** (adversarial, P3)
   - Posts are best-effort secondary evidence; without a stable per-post URL the item_id (derived from content) is the dedupe key. Acceptable per the plan's posts-are-partial caveat.

4. **Slug origin is not recoverable from normalized handles** (maintainability, P2)
   - `identity.handles` stores bare normalized slugs, so a non-LinkedIn first handle may be threaded as a company slug. Mitigated: the adapter's `_name_matches` verification rejects a wrong-company page as `schema-drift` (fail-closed), so no wrong evidence binds. A LinkedIn-specific handle field is deferred.

5. **`StartupPublicBase.failed()` embeds `str(exc)` in outcome detail** (security, P1, pre-existing)
   - Pre-existing in unchanged code, not introduced by this diff. The cookie adapter never routes through `failed()` (it uses `outcome()` with static details), so no credential can leak via this path from the new adapter. Hardening `failed()` is a follow-up.

6. **`test_opener_uses_no_env_proxy` passes vacuously** (correctness residual)
   - `build_opener(ProxyHandler({}))` drops the empty handler entirely, so the assertion "no ProxyHandler" passes for the right reason but would not catch a regression that reintroduces env-proxy handling. The safety property (env proxies never apply) is verified; the test is a weak guard.

7. **Cookie values persist as plain strings in process memory for the run** (security residual)
   - No zeroization after use. Out of scope for this diff's contract (in-memory-only, never persisted); consistent with how the existing token adapter handles credentials.
