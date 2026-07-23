#!/usr/bin/env python3
"""
refresh_cve_db.py — Refresh the offline NuGet CVE database.

Pulls the latest NuGet vulnerabilities from OSV.dev and writes them to a local
JSON file in the format consumed by `review.py --cve-check`.

Usage:
  python scripts/refresh_cve_db.py                       # default: scripts/review/cve-db/nuget-cve.json
  python scripts/refresh_cve_db.py ./cve-db/nuget.json   # custom output path
  python scripts/refresh_cve_db.py --output PATH         # explicit --output flag
  python scripts/refresh_cve_db.py --quiet               # only print errors
  python scripts/refresh_cve_db.py --help                # show help

Exit codes:
  0  success
  1  refresh failed (network / write error / no records)
  2  invalid CLI arguments
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make scripts/ importable so we can reuse the implementation in review/nuget.py
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from review.nuget import refresh_cve_db  # noqa: E402


DEFAULT_OUTPUT = SCRIPTS_DIR / "review" / "cve-db" / "nuget-cve.json.gz"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="refresh_cve_db.py",
        description="Refresh the offline NuGet CVE database from OSV.dev.",
    )
    p.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--output",
        "-o",
        dest="output_flag",
        default=None,
        help="Output JSON path (overrides positional argument).",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress informational output, only print errors.",
    )
    p.add_argument(
        "--retry",
        type=int,
        default=0,
        metavar="N",
        help="Number of retry attempts on transient network errors "
             "(exponential backoff: 2s, 4s, 8s...). 4xx errors are not retried. "
             "Default: 0.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="SEC",
        help="Per-request timeout in seconds. Default: 30.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = args.output_flag or args.output
    if not output_path:
        print("error: output path is required", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Refreshing CVE database → {output_path}")

    result = refresh_cve_db(output_path, retries=args.retry, timeout=args.timeout)

    if result.get("error"):
        print(f"error: {result['error']}", file=sys.stderr)
        if result.get("retries_used"):
            print(f"  (after {result['retries_used']} retr{'y' if result['retries_used'] == 1 else 'ies'})",
                  file=sys.stderr)
        return 1

    updated = result.get("updated", 0)
    if updated == 0:
        print("warning: 0 vulnerabilities written — OSV returned no records.", file=sys.stderr)
        return 1

    if not args.quiet:
        msg = f"OK: {updated} vulnerabilities written to {result.get('path', output_path)}"
        if result.get("retries_used"):
            msg += f" (after {result['retries_used']} retr{'y' if result['retries_used'] == 1 else 'ies'})"
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
