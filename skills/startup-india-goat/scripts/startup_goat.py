#!/usr/bin/env python3
"""Startup India GOAT command-line entrypoint.

The Python API is the canonical integration surface; this wrapper keeps direct
execution useful for scripting without changing the generic last30days CLI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Direct execution places ``scripts`` on sys.path, so ``lib`` is importable.
from lib.startup_goat import research  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-backed Startup India GOAT research")
    parser.add_argument("query", help="company or comparison request")
    parser.add_argument("--source", action="append", dest="sources", help="source alias (repeatable)")
    parser.add_argument("--depth", choices=("brief", "standard", "deep"), default="standard")
    parser.add_argument("--max-entities", type=int, default=6)
    parser.add_argument("--include-gated", action="store_true", help="requires --consent")
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.include_gated and not args.consent:
            parser.error("--include-gated requires --consent")
        from lib.startup_pipeline import StartupBudgets
        result = research(args.query, sources=args.sources, depth=args.depth,
                          public_only=not args.include_gated, consent=args.consent,
                          mock=args.mock, budgets=StartupBudgets(max_entities=args.max_entities))
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
