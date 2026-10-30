"""Readers for the parts of Iris's answers the policy needs.

Every field is optional: a missing one stays None ("Iris could not tell"), it never counts as safe
or unsafe by itself. Answers may be dicts or SDK objects with the same fields.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from .types import GuardSummary

_RANK = {"none": 0, "likely": 1, "tool": 2}
_KITS = {
    "proxima": ("Proxima", "tool"),
    "blockx": ("BlockX", "tool"),
    "launch_kit": ("an unnamed launch kit", "tool"),
    "funded_like_kit": ("a launch kit", "likely"),
    "none": (None, "none"),
}


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _path(obj: Any, *keys: str) -> Any:
    for key in keys:
        obj = _get(obj, key)
    return obj


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _share(v: Any) -> Optional[float]:
    n = _num(v)
    return None if n is None else round(n * 1000) / 10  # 0..1 -> percent, one decimal


def _seconds(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _first(*values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _set_launch_tool(s: GuardSummary, tool: Optional[str], verdict: str) -> None:
    if s.launch_tool_verdict is None or _RANK[verdict] > _RANK[s.launch_tool_verdict]:
        s.launch_tool_verdict = verdict  # type: ignore[assignment]
        s.launch_tool = None if verdict == "none" else tool


def _add_notes(s: GuardSummary, lines: Any) -> None:
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, str) and line not in s.notes:
                s.notes.append(line)


def read_launch_tool(s: GuardSummary, report: Any) -> None:
    """``POST /launch-tool`` scanned the token's creator. Its "tool" field names the tool checked
    even when nothing was found: only a verdict other than "none" is a detection."""
    if report is None:
        return
    wallet = _get(report, "wallet")
    if isinstance(wallet, str) and s.creator is None:
        s.creator = wallet
    launched = _get(report, "tokens_launched")
    if isinstance(launched, list):
        s.creator_launches = len(launched)
    verdict = _get(report, "verdict")
    if verdict in _RANK:
        name = _get(report, "tool_name") or _get(report, "tool") or "a launch tool"
        _set_launch_tool(s, name, verdict)


def read_analyze(s: GuardSummary, profile: Any) -> None:
    """``POST /analyze`` on the mint: the token's risk, launch, bundle, dev and launch-kit check."""
    if profile is None:
        return
    s.risk_score = _first(_num(_path(profile, "risk", "score")), s.risk_score)
    token = _get(profile, "token")
    if token is None:
        return
    launch = _get(token, "launch")
    creator = _get(launch, "creator")
    if isinstance(creator, str):
        s.creator = creator

    has_bundle = ("bundle" in token) if isinstance(token, dict) else hasattr(token, "bundle")
    bundle = _get(token, "bundle")
    story = _get(token, "story")
    if has_bundle:
        s.bundled = bundle is not None and (_num(_get(bundle, "wallets")) or 0) > 0
    s.bundle_held_pct = _first(_share(_path(story, "bundle", "held_share")), _share(_get(bundle, "held_share")), s.bundle_held_pct)

    dev = _get(story, "dev")
    if dev is not None:
        s.dev_held_pct = _share(_get(dev, "held_share"))
        exited = _get(dev, "exited")
        s.dev_sold = exited if isinstance(exited, bool) else (_num(_get(dev, "sold_share")) or 0) > 0
        launched, exit_at = _seconds(_get(launch, "created_at")), _seconds(_get(dev, "exit_at"))
        if exited and launched is not None and exit_at is not None:
            s.dev_dump_seconds = max(0.0, exit_at - launched)
    elif launch is not None:
        sold = _num(_get(launch, "creator_sold"))
        if sold is not None:
            s.dev_sold = sold > 0

    kit_verdict = _path(token, "launch_tool", "verdict")
    if isinstance(kit_verdict, str):
        name, verdict = _KITS.get(kit_verdict, (None, "none"))
        _set_launch_tool(s, name, verdict)
    _add_notes(s, _get(profile, "summary"))


def read_insiders(s: GuardSummary, result: Any) -> None:
    """``POST /insiders`` on the mint: the wallets linked to the dev by money, and what they hold."""
    if result is None:
        return
    dev = _path(result, "dev", "address")
    if isinstance(dev, str) and s.creator is None:
        s.creator = dev
    s.insider_held_pct = _first(_share(_path(result, "summary", "held_share")), s.insider_held_pct)
    insiders = _get(result, "insiders")
    if isinstance(insiders, list) and any(_get(i, "bundled") for i in insiders):
        s.bundled = True
    _add_notes(s, _get(result, "notes"))
