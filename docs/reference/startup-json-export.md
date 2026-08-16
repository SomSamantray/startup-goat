# Startup India GOAT JSON export

The standalone skill writes `startup-india-goat-json/1.0` when `--emit=json` is requested. The version is independent of the generic `last30days` export contract.

Top-level fields are `schema_version`, `contract`, `status`, `request`, `profiles`, `coverage`, and `artifacts`. Profiles contain entity-bound facts, evidence references, and conflict records. Raw source bodies and credentials are never included. Private or gated evidence is excluded from the agent export by default.

`status` is `complete`, `partial`, or `failed`; the bundle manifest records SHA-256 hashes and is written last. `coverage` distinguishes unavailable, gated, failed, quota, and schema-drift sources from genuine no-results outcomes.

```bash
python3 skills/startup-india-goat/scripts/startup_goat.py "Acme" \
  --sources startup-india,screener,yourstory --emit=json --save-dir ./startup-research
```
