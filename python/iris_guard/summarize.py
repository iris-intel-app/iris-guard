"""Readers for the parts of Iris's answers the policy needs.

Each answer goes through the SDK's ``risk_summary`` first (bundle, dev, launch kit, risk score),
then the readers below add what the policy needs on top: the dev's dump time, the creator's
launches, the insiders' share and how sure the launch-kit verdict is. A missing field stays None
("Iris could not tell"); it never counts as safe or unsafe by itself. When two answers both give a
figure, the higher one is kept: a guard errs on the side of caution.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from iriscan import risk_summary

from .types import GuardSummary

_RANK = {"none": 0, "likely": 1, "tool": 2}


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


def _higher(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return b if a is None else a if b is None else max(a, b)


def _either(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    return True if a is True or b is True else (a if a is not None else b)


def _fold(s: GuardSummary, result: Any) -> Optional[str]:
    """Folds the SDK's ``risk_summary`` of one answer into the summary; returns the kit it named."""
    r = risk_summary(result)
    s.bundled = _either(s.bundled, r["bundled"])
    s.bundle_held_pct = _higher(s.bundle_held_pct, r["bundle_held_pct"])
    s.dev_sold = _either(s.dev_sold, r["dev_sold"])
    s.dev_held_pct = _higher(s.dev_held_pct, r["dev_held_pct"])
    s.risk_score = _higher(s.risk_score, r["risk_score"])
    _add_notes(s, r["notes"])
    return r["launch_tool"]


def _set_launch_tool(s: GuardSummary, tool: Optional[str], verdict: str) -> None:
    if s.launch_tool_verdict is None or _RANK[verdict] > _RANK[s.launch_tool_verdict]:
        s.launch_tool_verdict = verdict  # type: ignore[assignment]
        s.launch_tool = None if verdict == "none" else tool


def _add_notes(s: GuardSummary, lines: Any) -> None:
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, str) and line and line not in s.notes:
                s.notes.append(line)


def read_launch_tool(s: GuardSummary, report: Any) -> None:
    """``POST /launch-tool`` scanned the token's creator. Its "tool" field names the tool checked
    even when nothing was found: only a verdict other than "none" is a detection."""
    if not isinstance(report, dict):
        return
    name = _fold(s, report)
    wallet = _get(report, "wallet")
    if isinstance(wallet, str) and s.creator is None:
        s.creator = wallet
    launched = _get(report, "tokens_launched")
    if isinstance(launched, list):
        s.creator_launches = len(launched)
    verdict = _get(report, "verdict")
    if verdict in _RANK:
        _set_launch_tool(s, name or "a launch tool", verdict)


def read_analyze(s: GuardSummary, profile: Any) -> None:
    """``POST /analyze`` on the mint: the token's risk, launch, bundle, dev and launch-kit check."""
    if not isinstance(profile, dict):
        return
    kit_name = _fold(s, profile)
    token = _get(profile, "token")
    if not token:
        return
    launch = _get(token, "launch")
    creator = _get(launch, "creator")
    if isinstance(creator, str):
        s.creator = creator

    # The story reads what the bundle and the dev hold from their balances now, when it can.
    story = _get(token, "story")
    s.bundle_held_pct = _higher(s.bundle_held_pct, _share(_path(story, "bundle", "held_share")))
    dev = _get(story, "dev")
    if dev is not None:
        s.dev_held_pct = _higher(s.dev_held_pct, _share(_get(dev, "held_share")))
        if _get(dev, "exited") is True:
            s.dev_sold = True
        launched, exit_at = _seconds(_get(launch, "created_at")), _seconds(_get(dev, "exit_at"))
        if _get(dev, "exited") and launched is not None and exit_at is not None:
            s.dev_dump_seconds = max(0.0, exit_at - launched)

    # How sure the analysis's launch-kit check is: a kit's marks, or only funding laid out like one.
    kit_verdict = _path(token, "launch_tool", "verdict")
    if isinstance(kit_verdict, str):
        verdict = "none" if kit_verdict == "none" else "likely" if kit_verdict == "funded_like_kit" else "tool"
        _set_launch_tool(s, kit_name or _path(token, "launch_tool", "tool") or "a launch kit", verdict)
    _add_notes(s, _get(profile, "summary"))


def read_insiders(s: GuardSummary, result: Any) -> None:
    """``POST /insiders`` on the mint: the wallets linked to the dev by money, and what they hold."""
    if not isinstance(result, dict):
        return
    _fold(s, result)
    dev = _path(result, "dev", "address")
    if isinstance(dev, str) and s.creator is None:
        s.creator = dev
    s.insider_held_pct = _higher(s.insider_held_pct, _share(_path(result, "summary", "held_share")))
