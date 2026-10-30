"""``python -m iris_guard <mint>``: prints ALLOW or BLOCK with the reasons.

Exit code: 0 ALLOW, 1 BLOCK (or Iris failed, fail-closed), 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .guard import Guard
from .types import GuardResult


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="iris-guard",
        description="Checks a Solana token before you buy it. Prints ALLOW or BLOCK with the reasons. "
        "Exit code: 0 ALLOW, 1 BLOCK (or Iris failed, fail-closed), 2 bad usage.",
        epilog="Environment: IRIS_API_KEY (optional; get one at https://iriscan.app/pricing), IRIS_BASE_URL.",
    )
    p.add_argument("mint", help="the token mint")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--free", dest="mode", action="store_const", const="free", help="the launch-tool scan only, no credits spent")
    mode.add_argument("--full", dest="mode", action="store_const", const="full", help="adds /analyze and /insiders (needs IRIS_API_KEY)")
    p.add_argument("--no-insiders", action="store_true", help="full mode without the insider search (saves 2 credits)")
    p.add_argument("--fail-open", action="store_true", help="ALLOW when Iris errors or times out (default: BLOCK)")
    p.add_argument("--timeout", type=float, default=20.0, metavar="SECONDS", help="deadline for the whole check (default 20)")
    p.add_argument("--max-bundle", type=float, metavar="PCT", help="block when the bundle still holds this %% or more (default 10)")
    p.add_argument("--max-dev", type=float, metavar="PCT", help="block when the dev still holds this %% or more (default 10)")
    p.add_argument("--dump-within", type=float, metavar="SECONDS", help="block when the dev dumped within this many seconds (default 300)")
    p.add_argument("--max-risk", type=float, metavar="SCORE", help="block at this Iris risk score or more (default 70)")
    p.add_argument("--max-launches", type=int, metavar="N", help="block when the creator launched this many tokens or more (default off)")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    return p


def _print(result: GuardResult) -> None:
    print(f"{'ALLOW' if result.allow else 'BLOCK'} {result.mint} ({result.mode} mode, {result.latency_ms} ms)")
    for r in result.reasons:
        print(f"  - {r}")
    for w in result.warnings:
        print(f"  ! {w}")
    if result.mode == "free" and result.error is None:
        print("  Free mode reads launch tools only. Bundles, dev holdings and risk need a key: https://iriscan.app/pricing")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode == "full" and not os.environ.get("IRIS_API_KEY"):
        parser.error("--full needs IRIS_API_KEY")
    overrides = {
        k: v
        for k, v in {
            "max_bundle_held_pct": args.max_bundle,
            "max_dev_held_pct": args.max_dev,
            "dev_dump_within_seconds": args.dump_within,
            "max_risk_score": args.max_risk,
            "max_creator_launches": args.max_launches,
        }.items()
        if v is not None
    }
    with Guard(
        mode=args.mode,
        fail_open=args.fail_open,
        timeout=args.timeout,
        cache_ttl=0,
        insiders=not args.no_insiders,
        base_url=os.environ.get("IRIS_BASE_URL") or None,
        **overrides,
    ) as guard:
        result = guard.check(args.mint)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print(result)
    return 0 if result.allow else 1


if __name__ == "__main__":
    sys.exit(main())
