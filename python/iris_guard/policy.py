"""The policy: which facts block a buy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Optional

from .types import GuardSummary


@dataclass(frozen=True)
class Policy:
    """Thresholds of the guard; ``None`` turns a rule off. The same defaults as the TypeScript package.

    - Bundle 10%: a bundle sitting on a tenth of the supply can dump it on the first buyers.
    - Dev 10%: a pump.fun dev's own launch buy is usually a few percent; ten or more is a loaded gun.
    - Dev dump 5 minutes: a dev who is done selling within minutes of the launch ran a pump and dump.
    - Insiders 20%: wallets linked to the dev by money, together, holding a fifth of the supply.
    - Risk 70: the score at which Iris itself calls a token HIGH risk.
    - Launch tools: Proxima and BlockX exist to launch, bundle and dump tokens from fleets of wallets.
    - Serial launches: a warning only; many honest devs launch more than once.
    """

    max_bundle_held_pct: Optional[float] = 10
    max_dev_held_pct: Optional[float] = 10
    dev_dump_within_seconds: Optional[float] = 300
    max_insider_held_pct: Optional[float] = 20
    max_risk_score: Optional[float] = 70
    block_launch_tools: bool = True
    block_likely_launch_tools: bool = True
    max_creator_launches: Optional[int] = None
    #: Your own rule: return a reason to block, or None to let it through.
    custom: Optional[Callable[[GuardSummary], Optional[str]]] = None

    def with_(self, **overrides) -> "Policy":
        return replace(self, **overrides)


DEFAULT_POLICY = Policy()


def _pct(n: float) -> str:
    return f"{n:.1f}%"


def _num(n: float) -> str:
    return f"{n:g}"


def _duration(seconds: float) -> str:
    if seconds < 120:
        return f"{round(seconds)} s"
    if seconds < 7200:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def evaluate(summary: GuardSummary, policy: Policy = DEFAULT_POLICY) -> tuple[bool, list[str], list[str]]:
    """Applies ``policy`` to what a check found: (allow, reasons to block, warnings)."""
    reasons: list[str] = []
    warnings: list[str] = []

    def at(value, limit) -> bool:
        return value is not None and limit is not None and value >= limit

    s = summary
    if s.launch_tool and s.launch_tool_verdict and s.launch_tool_verdict != "none":
        likely = s.launch_tool_verdict == "likely"
        what = f"Launch tool{' (likely)' if likely else ''}: {s.launch_tool}"
        if policy.block_launch_tools and (not likely or policy.block_likely_launch_tools):
            reasons.append(what)
        else:
            warnings.append(what)

    if s.bundled and at(s.bundle_held_pct, policy.max_bundle_held_pct):
        reasons.append(f"Bundle still holds {_pct(s.bundle_held_pct)} of the supply (max {_num(policy.max_bundle_held_pct)}%)")
    elif s.bundled:
        warnings.append("Bundled launch" if s.bundle_held_pct is None else f"Bundled launch, the bundle holds {_pct(s.bundle_held_pct)} now")

    if at(s.dev_held_pct, policy.max_dev_held_pct):
        reasons.append(f"Dev still holds {_pct(s.dev_held_pct)} of the supply (max {_num(policy.max_dev_held_pct)}%)")

    if s.dev_dump_seconds is not None and policy.dev_dump_within_seconds is not None and s.dev_dump_seconds <= policy.dev_dump_within_seconds:
        reasons.append(f"Dev dumped {_duration(s.dev_dump_seconds)} after launch (limit {_duration(policy.dev_dump_within_seconds)})")
    elif s.dev_sold:
        warnings.append("Dev sold")

    if at(s.insider_held_pct, policy.max_insider_held_pct):
        reasons.append(f"Wallets linked to the dev hold {_pct(s.insider_held_pct)} of the supply (max {_num(policy.max_insider_held_pct)}%)")

    if at(s.risk_score, policy.max_risk_score):
        reasons.append(f"Iris risk score {_num(s.risk_score)}/100 (max {_num(policy.max_risk_score)})")

    if s.creator_launches is not None and s.creator_launches > 1:
        line = f"Creator launched {s.creator_launches} tokens"
        if at(s.creator_launches, policy.max_creator_launches):
            reasons.append(f"{line} (max {policy.max_creator_launches})")
        else:
            warnings.append(line)

    if policy.custom is not None:
        custom = policy.custom(summary)
        if custom:
            reasons.append(custom)

    return not reasons, reasons, warnings
