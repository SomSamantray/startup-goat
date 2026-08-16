#!/usr/bin/env python3
"""Standalone Startup India GOAT research entrypoint."""
from __future__ import annotations

import argparse
import json

from lib.startup_goat import research
from lib.startup_pipeline import StartupBudgets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-backed Startup India GOAT research")
    parser.add_argument("query", nargs="?", help="company or comparison request")
    parser.add_argument("--company", action="append", dest="company_args", help="company name (repeatable)")
    parser.add_argument("--companies", dest="companies_csv", help="comma-separated company names")
    parser.add_argument("--source", action="append", dest="source_args", help="source alias (repeatable)")
    parser.add_argument("--sources", dest="sources_csv", help="comma-separated source aliases")
    parser.add_argument("--dimensions", help="comma-separated qualitative dimensions")
    parser.add_argument("--depth", choices=("brief", "standard", "deep"), default="standard")
    parser.add_argument("--max-entities", type=int, default=6)
    parser.add_argument("--include-gated", action="store_true", help="requires --consent")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--public-only", action="store_true", default=False, help="force public-only retrieval")
    parser.add_argument("--save-dir", help="bundle output directory (or STARTUP_GOAT_MEMORY_DIR)")
    parser.add_argument("--emit", default=None, help="comma-separated md,html,json (default all when saving)")
    parser.add_argument("--private", action="store_true", help="save files with private permissions")
    parser.add_argument("--doctor", action="store_true", help="print source diagnostics and exit")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    if args.doctor:
        from lib.startup_doctor import diagnose_sources, render_doctor
        print(render_doctor(diagnose_sources(public_only=not args.include_gated)), end="")
        return 0
    query = args.query or ""
    companies = list(args.company_args or [])
    if args.companies_csv:
        companies.extend(part.strip() for part in args.companies_csv.split(",") if part.strip())
    if not query and not companies:
        parser.error("query or --company is required")
    if args.include_gated and not args.consent:
        parser.error("--include-gated requires --consent")
    public_only = not args.include_gated
    if args.public_only:
        public_only = True
    sources = list(args.source_args or [])
    if args.sources_csv:
        sources.extend(part.strip() for part in args.sources_csv.split(",") if part.strip())
    if args.dimensions:
        dimensions = [part.strip() for part in args.dimensions.split(",") if part.strip()]
    else:
        dimensions = None
    try:
        kwargs = {"depth": args.depth, "public_only": public_only, "consent": args.consent, "mock": args.mock, "budgets": StartupBudgets(max_entities=args.max_entities)}
        if sources:
            kwargs["sources"] = sources
        if companies:
            kwargs["entities"] = tuple(companies)
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        result = research(query or ", ".join(companies), **kwargs)
        if args.save_dir or args.emit:
            bundle = result.save(save_dir=args.save_dir, emit=args.emit or "md,html,json", private=args.private)
            print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))
        else:
            # Keep direct CLI output on the secret-free versioned export path;
            # raw source bodies belong only in sanitized saved evidence files.
            from lib.startup_export import export_json
            print(export_json(result), end="")
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
