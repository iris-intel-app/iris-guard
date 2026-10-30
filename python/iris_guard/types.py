"""What a check finds and returns."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

Mode = Literal["free", "full"]
LaunchToolVerdict = Literal["tool", "likely", "none"]


@dataclass
class GuardSummary:
    """The facts a check found about a token. ``None`` means Iris could not tell (or the mode does not read it)."""

    mint: str
    mode: Mode
    #: The token's creator (its dev), when known.
    creator: Optional[str] = None
    #: Tokens the creator launched, over the history Iris read.
    creator_launches: Optional[int] = None
    #: The launch tool found ("Proxima", "BlockX"), or None when none was found.
    launch_tool: Optional[str] = None
    launch_tool_verdict: Optional[LaunchToolVerdict] = None
    #: A launch bundle was found: wallets one party bought the launch with.
    bundled: Optional[bool] = None
    #: Share of the supply the bundle still holds, in percent (0 to 100).
    bundle_held_pct: Optional[float] = None
    #: Share of the supply the dev still holds, in percent.
    dev_held_pct: Optional[float] = None
    #: The dev sold (most of) what it got.
    dev_sold: Optional[bool] = None
    #: Seconds between the launch and the dev being done selling, when it was.
    dev_dump_seconds: Optional[float] = None
    #: Share of the supply held by wallets linked to the dev by money (/insiders), in percent.
    insider_held_pct: Optional[float] = None
    #: Iris risk score, 0 to 100 (70 and up is HIGH).
    risk_score: Optional[float] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class GuardResult:
    mint: str
    allow: bool
    #: Why it was blocked (empty when allowed).
    reasons: list[str]
    #: Facts worth knowing that did not block it.
    warnings: list[str]
    #: What the check found; None when the check failed before reading anything.
    summary: Optional[GuardSummary]
    mode: Mode
    latency_ms: int
    #: Served from the in-memory cache.
    cached: bool = False
    #: Set when Iris could not be reached or answered with an error; ``allow`` then follows ``fail_open``.
    error: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
