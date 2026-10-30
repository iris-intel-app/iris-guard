"""Unit tests with a mocked SDK client: python -m unittest discover -s tests"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from iris_guard import DEFAULT_POLICY, AsyncGuard, Guard, GuardBlocked, GuardSummary, Policy, evaluate, with_guard

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures"
MINT = "So11111111111111111111111111111111111111112"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class FakeIrisError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class Mock:
    """A mocked SDK client: each method answers what it is given (an exception is raised, a
    callable is called), and counts its calls."""

    def __init__(self, **answers: Any):
        self.answers = answers
        self.calls = {"launch_tool": 0, "analyze": 0, "insiders": 0}
        self._lock = threading.Lock()

    def _answer(self, name: str) -> Any:
        with self._lock:
            self.calls[name] += 1
        value = self.answers.get(name)
        if isinstance(value, BaseException):
            raise value
        return value() if callable(value) else value

    def launch_tool(self, wallet_or_mint: str, **_: Any) -> Any:
        return self._answer("launch_tool")

    def analyze(self, address: str, **_: Any) -> Any:
        return self._answer("analyze")

    def insiders(self, mint: str, **_: Any) -> Any:
        return self._answer("insiders")


class AsyncMock(Mock):
    async def launch_tool(self, wallet_or_mint: str, **_: Any) -> Any:  # type: ignore[override]
        return await self._async("launch_tool")

    async def analyze(self, address: str, **_: Any) -> Any:  # type: ignore[override]
        return await self._async("analyze")

    async def insiders(self, mint: str, **_: Any) -> Any:  # type: ignore[override]
        return await self._async("insiders")

    async def _async(self, name: str) -> Any:
        value = self.answers.get(name)
        if callable(value) and not isinstance(value, BaseException):
            with self._lock:
                self.calls[name] += 1
            return await value()
        return self._answer(name)


def guard(client: Any, **kwargs: Any) -> Guard:
    kwargs.setdefault("mode", "free")
    return Guard(client=client, **kwargs)


RUG = dict(analyze=fixture("analyze-rug"), insiders=fixture("insiders-linked"), launch_tool=fixture("launch-tool-serial"))


class FreeMode(unittest.TestCase):
    def test_allows_no_launch_tool_and_warns_serial(self):
        m = Mock(launch_tool=fixture("launch-tool-serial"))
        r = guard(m).check(MINT)
        self.assertTrue(r.allow)
        self.assertEqual(r.reasons, [])
        self.assertEqual(r.warnings, ["Creator launched 12 tokens"])
        self.assertIsNone(r.summary.launch_tool, "the 'tool' field alone is not a detection")
        self.assertEqual(r.summary.creator_launches, 12)
        self.assertEqual(m.calls, {"launch_tool": 1, "analyze": 0, "insiders": 0})

    def test_blocks_proxima(self):
        r = guard(Mock(launch_tool=fixture("launch-tool-proxima"))).check(MINT)
        self.assertFalse(r.allow)
        self.assertEqual(r.reasons, ["Launch tool: Proxima"])

    def test_likely_blocks_by_default_warns_when_told(self):
        likely = {**fixture("launch-tool-proxima"), "verdict": "likely"}
        self.assertFalse(guard(Mock(launch_tool=likely)).check(MINT).allow)
        r = guard(Mock(launch_tool=likely), block_likely_launch_tools=False).check(MINT)
        self.assertTrue(r.allow)
        self.assertEqual(r.warnings, ["Launch tool (likely): Proxima"])

    def test_serial_launch_limit(self):
        r = guard(Mock(launch_tool=fixture("launch-tool-serial")), max_creator_launches=5).check(MINT)
        self.assertEqual(r.reasons, ["Creator launched 12 tokens (max 5)"])


class FullMode(unittest.TestCase):
    def test_blocks_rug_for_every_rule(self):
        m = Mock(**RUG)
        r = guard(m, mode="full").check(MINT)
        self.assertFalse(r.allow)
        self.assertEqual(
            r.reasons,
            [
                "Bundle still holds 34.2% of the supply (max 10%)",
                "Dev dumped 42 s after launch (limit 5 min)",
                "Wallets linked to the dev hold 25.3% of the supply (max 20%)",
                "Iris risk score 82/100 (max 70)",
            ],
        )
        self.assertEqual(r.summary.dev_dump_seconds, 42)
        self.assertEqual(m.calls, {"launch_tool": 1, "analyze": 1, "insiders": 1})

    def test_allows_clean(self):
        insiders = {"dev": {"address": "dev"}, "summary": {"insiders": 0, "held_share": 0.01}, "insiders": [], "complete": True}
        r = guard(Mock(analyze=fixture("analyze-clean"), insiders=insiders, launch_tool=fixture("launch-tool-serial")), mode="full").check(MINT)
        self.assertTrue(r.allow, r.reasons)
        self.assertIs(r.summary.bundled, False)
        self.assertEqual(r.summary.dev_held_pct, 2.0)
        self.assertEqual(r.summary.risk_score, 12)

    def test_dev_holds_too_much(self):
        analysis = fixture("analyze-clean")
        analysis["token"]["story"]["dev"]["held_share"] = 0.15
        r = guard(Mock(analyze=analysis), mode="full").check(MINT)
        self.assertEqual(r.reasons, ["Dev still holds 15.0% of the supply (max 10%)"])

    def test_launch_kit_from_analysis(self):
        analysis = fixture("analyze-clean")
        analysis["token"]["launch_tool"]["verdict"] = "blockx"
        r = guard(Mock(analyze=analysis, launch_tool=fixture("launch-tool-serial")), mode="full").check(MINT)
        self.assertEqual(r.reasons, ["Launch tool: BlockX"])

    def test_without_insider_search(self):
        m = Mock(analyze=fixture("analyze-clean"), launch_tool=fixture("launch-tool-serial"))
        guard(m, mode="full", insiders=False).check(MINT)
        self.assertEqual(m.calls["insiders"], 0)

    def test_optional_calls_fail_softly(self):
        m = Mock(analyze=fixture("analyze-clean"), insiders=FakeIrisError(500, "boom"), launch_tool=FakeIrisError(429, "Too many"))
        r = guard(m, mode="full").check(MINT)
        self.assertTrue(r.allow)
        self.assertIsNone(r.error)
        self.assertTrue(any(n.startswith("Insider search skipped") for n in r.summary.notes))
        self.assertTrue(any(n.startswith("Launch-tool scan skipped") for n in r.summary.notes))

    def test_default_mode_with_key(self):
        self.assertEqual(Guard("iris_live_test", client=Mock()).mode, "full")
        self.assertEqual(Guard("iris_live_test", mode="free", client=Mock()).mode, "free")


class Failures(unittest.TestCase):
    def test_fail_closed(self):
        r = guard(Mock(launch_tool=FakeIrisError(500, "The launch-tool scan failed"))).check(MINT)
        self.assertFalse(r.allow)
        self.assertEqual(r.error["status"], 500)
        self.assertTrue(r.reasons[0].startswith("Iris check failed (fail-closed): The launch-tool scan failed"))

    def test_fail_open(self):
        r = guard(Mock(launch_tool=FakeIrisError(500, "down")), fail_open=True).check(MINT)
        self.assertTrue(r.allow)
        self.assertEqual(r.reasons, [])
        self.assertIn("fail-open", r.warnings[0])

    def test_analysis_error_fails(self):
        m = Mock(analyze=FakeIrisError(402, "Not enough credits", "no_credits"), launch_tool=fixture("launch-tool-serial"))
        r = guard(m, mode="full").check(MINT)
        self.assertFalse(r.allow)
        self.assertIn("iriscan.app/pricing", r.error["message"])

    def test_missing_key_points_to_pricing(self):
        r = guard(Mock(launch_tool=FakeIrisError(401, "Log in to use Iris", "login"))).check(MINT)
        self.assertIn("get an API key: https://iriscan.app/pricing", r.reasons[0])

    def test_timeout(self):
        r = guard(Mock(launch_tool=lambda: time.sleep(0.5)), timeout=0.05).check(MINT)
        self.assertFalse(r.allow)
        self.assertIn("did not answer within 0.05 s", r.error["message"])
        self.assertLess(r.latency_ms, 400)
        self.assertTrue(guard(Mock(launch_tool=lambda: time.sleep(0.5)), timeout=0.05, fail_open=True).check(MINT).allow)

    def test_not_a_mint(self):
        m = Mock()
        r = guard(m).check("not-a-mint")
        self.assertFalse(r.allow)
        self.assertEqual(m.calls["launch_tool"], 0)


class Cache(unittest.TestCase):
    def test_reuse_within_ttl(self):
        m = Mock(launch_tool=fixture("launch-tool-serial"))
        g = guard(m)
        first, second = g.check(MINT), g.check(MINT)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(m.calls["launch_tool"], 1)

    def test_expires(self):
        m = Mock(launch_tool=fixture("launch-tool-serial"))
        g = guard(m, cache_ttl=0.02)
        g.check(MINT)
        time.sleep(0.04)
        self.assertFalse(g.check(MINT).cached)
        self.assertEqual(m.calls["launch_tool"], 2)

    def test_failures_not_cached(self):
        m = Mock(launch_tool=FakeIrisError(503, "busy"))
        g = guard(m)
        g.check(MINT)
        g.check(MINT)
        self.assertEqual(m.calls["launch_tool"], 2)

    def test_concurrent_checks_share_one_call(self):
        def slow():
            time.sleep(0.05)
            return fixture("launch-tool-serial")

        m = Mock(launch_tool=slow)
        g = guard(m)
        results: list = []
        threads = [threading.Thread(target=lambda: results.append(g.check(MINT))) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 3)
        self.assertEqual(m.calls["launch_tool"], 1)

    def test_off_and_clear(self):
        m = Mock(launch_tool=fixture("launch-tool-serial"))
        off = guard(m, cache_ttl=0)
        off.check(MINT)
        off.check(MINT)
        self.assertEqual(m.calls["launch_tool"], 2)
        g = guard(m)
        g.check(MINT)
        g.clear_cache()
        g.check(MINT)
        self.assertEqual(m.calls["launch_tool"], 4)


class PolicyRules(unittest.TestCase):
    def test_unknown_is_neutral(self):
        self.assertEqual(evaluate(GuardSummary(MINT, "full"), DEFAULT_POLICY), (True, [], []))

    def test_threshold_inclusive(self):
        s = GuardSummary(MINT, "full", bundled=True, bundle_held_pct=10, dev_held_pct=9.9, risk_score=70)
        self.assertEqual(evaluate(s)[1], ["Bundle still holds 10.0% of the supply (max 10%)", "Iris risk score 70/100 (max 70)"])

    def test_none_turns_off(self):
        s = GuardSummary(MINT, "full", risk_score=99, dev_dump_seconds=5)
        self.assertTrue(evaluate(s, Policy(max_risk_score=None, dev_dump_within_seconds=None))[0])

    def test_custom_rule(self):
        rule = lambda s: "Creator is a launch factory" if (s.creator_launches or 0) > 10 else None  # noqa: E731
        r = guard(Mock(launch_tool=fixture("launch-tool-serial")), custom=rule).check(MINT)
        self.assertEqual(r.reasons, ["Creator is a launch factory"])

    def test_same_defaults_as_typescript(self):
        ts = (Path(__file__).resolve().parents[2] / "src" / "policy.ts").read_text()
        for ts_name, value in [
            ("maxBundleHeldPct", DEFAULT_POLICY.max_bundle_held_pct),
            ("maxDevHeldPct", DEFAULT_POLICY.max_dev_held_pct),
            ("devDumpWithinSeconds", DEFAULT_POLICY.dev_dump_within_seconds),
            ("maxInsiderHeldPct", DEFAULT_POLICY.max_insider_held_pct),
            ("maxRiskScore", DEFAULT_POLICY.max_risk_score),
        ]:
            self.assertIn(f"{ts_name}: {value:g},", ts)


class Helpers(unittest.TestCase):
    def test_assert_allowed(self):
        with self.assertRaises(GuardBlocked) as caught:
            guard(Mock(launch_tool=fixture("launch-tool-proxima"))).assert_allowed(MINT)
        self.assertFalse(caught.exception.result.allow)

    def test_with_guard(self):
        bought: list[float] = []
        blocked = with_guard(guard(Mock(launch_tool=fixture("launch-tool-proxima"))), lambda mint, sol: bought.append(sol))
        with self.assertRaises(GuardBlocked):
            blocked(MINT, 1)
        allowed = with_guard(guard(Mock(launch_tool=fixture("launch-tool-serial"))), lambda mint, sol: bought.append(sol))
        allowed(MINT, 0.5)
        self.assertEqual(bought, [0.5])


class Async(unittest.IsolatedAsyncioTestCase):
    async def test_full_rug(self):
        r = await AsyncGuard(client=AsyncMock(**RUG), mode="full").check(MINT)
        self.assertFalse(r.allow)
        self.assertEqual(len(r.reasons), 4)

    async def test_timeout_fail_closed(self):
        async def never():
            await asyncio.sleep(5)

        r = await AsyncGuard(client=AsyncMock(launch_tool=never), mode="free", timeout=0.05).check(MINT)
        self.assertFalse(r.allow)
        self.assertEqual(r.error["message"], "Iris did not answer within 0.05 s")

    async def test_concurrent_share_and_cache(self):
        async def slow():
            await asyncio.sleep(0.05)
            return fixture("launch-tool-serial")

        m = AsyncMock(launch_tool=slow)
        g = AsyncGuard(client=m, mode="free")
        a, b = await asyncio.gather(g.check(MINT), g.check(MINT))
        self.assertTrue(a.allow and b.allow)
        self.assertTrue((await g.check(MINT)).cached)
        self.assertEqual(m.calls["launch_tool"], 1)

    async def test_with_guard_async(self):
        bought: list[str] = []

        async def buy(mint: str) -> None:
            bought.append(mint)

        await with_guard(AsyncGuard(client=AsyncMock(launch_tool=fixture("launch-tool-serial")), mode="free"), buy)(MINT)
        self.assertEqual(bought, [MINT])


if __name__ == "__main__":
    unittest.main()
