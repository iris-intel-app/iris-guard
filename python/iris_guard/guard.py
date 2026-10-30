"""The guard: one call before every buy."""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from typing import Any, Awaitable, Callable, Optional, Protocol, TypeVar

from .policy import DEFAULT_POLICY, Policy, evaluate
from .summarize import read_analyze, read_insiders, read_launch_tool
from .types import GuardResult, GuardSummary, Mode

PRICING = "https://iriscan.app/pricing"
_BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
T = TypeVar("T")


class IrisClient(Protocol):
    """The Iris calls a guard makes: ``iriscan.Iris``, or anything shaped like it."""

    def launch_tool(self, wallet_or_mint: str, **kwargs: Any) -> Any: ...
    def analyze(self, address: str, **kwargs: Any) -> Any: ...
    def insiders(self, mint: str, **kwargs: Any) -> Any: ...


class GuardBlocked(Exception):
    """Raised by ``assert_allowed`` (and ``with_guard``) when a token is blocked."""

    def __init__(self, result: GuardResult):
        super().__init__(f"iris-guard blocked {result.mint}: {'; '.join(result.reasons)}")
        self.result = result


class GuardTimeout(Exception):
    def __init__(self, seconds: float):
        super().__init__(f"Iris did not answer within {seconds:g} s")


def _env_key() -> Optional[str]:
    key = os.environ.get("IRIS_API_KEY", "").strip()
    return key or None


def _describe(e: BaseException) -> dict[str, Any]:
    status = getattr(e, "status", None)
    code = getattr(e, "code", None)
    message = str(e) or type(e).__name__
    if status == 401 or code in ("login", "invalid_key"):
        message += f" (get an API key: {PRICING})"
    elif status == 402 or code == "no_credits":
        message += f" (out of credits: {PRICING})"
    elif code in ("daily_limit", "quota_exceeded"):
        message += f" (free plan limit reached: {PRICING})"
    retry = getattr(e, "retry_after", None)
    if status == 429 and retry:
        message += f" (retry after {retry} s)"
    error: dict[str, Any] = {"message": message}
    if isinstance(status, int):
        error["status"] = status
    if isinstance(code, str):
        error["code"] = code
    return error


class _Core:
    """What the sync and async guards share: settings, the policy, the cache and the results."""

    def __init__(
        self,
        api_key: Optional[str],
        mode: Optional[Mode],
        policy: Optional[Policy],
        fail_open: bool,
        timeout: float,
        cache_ttl: float,
        insiders: bool,
        policy_overrides: dict[str, Any],
    ):
        self.api_key = api_key if api_key is not None else _env_key()
        self.mode: Mode = mode or ("full" if self.api_key else "free")
        self.policy = replace(policy or DEFAULT_POLICY, **policy_overrides)
        self.fail_open = fail_open
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.use_insiders = insiders
        self._cache: dict[str, tuple[float, GuardResult]] = {}
        self._lock = threading.Lock()

    def invalid(self, mint: str) -> Optional[GuardResult]:
        if _BASE58.match(mint):
            return None
        return GuardResult(mint, False, ["Not a Solana mint address"], [], None, self.mode, 0)

    def cached(self, mint: str) -> Optional[GuardResult]:
        with self._lock:
            hit = self._cache.get(mint)
            if hit is None:
                return None
            if hit[0] > time.monotonic():
                return replace(hit[1], cached=True, latency_ms=0)
            del self._cache[mint]
            return None

    def success(self, mint: str, summary: GuardSummary, started: float) -> GuardResult:
        allow, reasons, warnings = evaluate(summary, self.policy)
        result = GuardResult(mint, allow, reasons, warnings, summary, self.mode, round((time.monotonic() - started) * 1000))
        if self.cache_ttl > 0:
            with self._lock:
                self._cache[mint] = (time.monotonic() + self.cache_ttl, result)
        return result

    def failure(self, mint: str, e: BaseException, started: float) -> GuardResult:
        error = _describe(e)
        how = "fail-open" if self.fail_open else "fail-closed"
        line = f"Iris check failed ({how}): {error['message']}"
        return GuardResult(
            mint,
            self.fail_open,
            [] if self.fail_open else [line],
            [line] if self.fail_open else [],
            None,
            self.mode,
            round((time.monotonic() - started) * 1000),
            error=error,
        )

    def full_summary(self, mint: str, analysis: Any, scan: Any, insiders: Any) -> GuardSummary:
        """Full mode: the analysis decides (its error is raised); the free scan and the insider
        search add to it when they answered (their errors become notes)."""
        if isinstance(analysis, BaseException):
            raise analysis
        summary = GuardSummary(mint, "full")
        read_analyze(summary, analysis)
        if isinstance(scan, BaseException):
            summary.notes.append(f"Launch-tool scan skipped: {_describe(scan)['message']}")
        else:
            read_launch_tool(summary, scan)
        if isinstance(insiders, BaseException):
            summary.notes.append(f"Insider search skipped: {_describe(insiders)['message']}")
        else:
            read_insiders(summary, insiders)
        return summary

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()


def _sdk_kwargs(api_key: Optional[str], base_url: Optional[str], timeout: float) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": timeout}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs


class Guard:
    """A pre-trade rug filter (blocking calls). ``guard.check(mint).allow`` before every buy."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        mode: Optional[Mode] = None,
        policy: Optional[Policy] = None,
        fail_open: bool = False,
        timeout: float = 20.0,
        cache_ttl: float = 60.0,
        insiders: bool = True,
        base_url: Optional[str] = None,
        client: Optional[IrisClient] = None,
        **policy_overrides: Any,
    ):
        self._core = _Core(api_key, mode, policy, fail_open, timeout, cache_ttl, insiders, policy_overrides)
        if client is None:
            from iriscan import Iris

            client = Iris(**_sdk_kwargs(self._core.api_key, base_url, timeout))
        self._client = client
        self._pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="iris-guard")
        self._inflight: dict[str, tuple[threading.Event, list[GuardResult]]] = {}
        self._inflight_lock = threading.Lock()

    mode = property(lambda self: self._core.mode)
    policy = property(lambda self: self._core.policy)

    def _call(self, fn: Callable[[], T]) -> Any:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - every failure is handled by the policy
            return e

    def _run(self, mint: str) -> GuardResult:
        started = time.monotonic()
        c = self._client
        calls: list[Callable[[], Any]] = [lambda: c.launch_tool(mint)]
        if self._core.mode == "full":
            calls = [lambda: c.analyze(mint), calls[0], (lambda: c.insiders(mint)) if self._core.use_insiders else (lambda: None)]
        # The calls run side by side in the pool; the deadline is kept here, on the caller's side.
        futures = [self._pool.submit(self._call, call) for call in calls]
        _, late = wait(futures, timeout=self._core.timeout if self._core.timeout > 0 else None)
        if late:
            return self._core.failure(mint, GuardTimeout(self._core.timeout), started)
        answers = [f.result() for f in futures]
        try:
            if self._core.mode == "free":
                if isinstance(answers[0], BaseException):
                    raise answers[0]
                summary = GuardSummary(mint, "free")
                read_launch_tool(summary, answers[0])
            else:
                summary = self._core.full_summary(mint, *answers)
        except Exception as e:  # noqa: BLE001
            return self._core.failure(mint, e, started)
        return self._core.success(mint, summary, started)

    def check(self, mint: str) -> GuardResult:
        """Checks a token mint against the policy. Never raises: errors come back shaped by ``fail_open``."""
        mint = str(mint or "").strip()
        early = self._core.invalid(mint) or self._core.cached(mint)
        if early is not None:
            return early
        # Two checks of one mint at once (a sniper seeing it twice) share one call.
        with self._inflight_lock:
            shared = self._inflight.get(mint)
            if shared is None:
                shared = self._inflight[mint] = (threading.Event(), [])
                owner = True
            else:
                owner = False
        event, box = shared
        if not owner:
            event.wait()
            return box[0]
        try:
            box.append(self._run(mint))
        finally:
            with self._inflight_lock:
                self._inflight.pop(mint, None)
            event.set()
        return box[0]

    def assert_allowed(self, mint: str) -> GuardResult:
        """Like ``check``, but raises ``GuardBlocked`` when the token is blocked."""
        result = self.check(mint)
        if not result.allow:
            raise GuardBlocked(result)
        return result

    def clear_cache(self) -> None:
        self._core.clear_cache()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "Guard":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncGuard:
    """The asyncio guard: ``(await guard.check(mint)).allow`` before every buy."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        mode: Optional[Mode] = None,
        policy: Optional[Policy] = None,
        fail_open: bool = False,
        timeout: float = 20.0,
        cache_ttl: float = 60.0,
        insiders: bool = True,
        base_url: Optional[str] = None,
        client: Any = None,
        **policy_overrides: Any,
    ):
        self._core = _Core(api_key, mode, policy, fail_open, timeout, cache_ttl, insiders, policy_overrides)
        if client is None:
            from iriscan import AsyncIris

            client = AsyncIris(**_sdk_kwargs(self._core.api_key, base_url, timeout))
        self._client = client
        self._inflight: dict[str, asyncio.Future] = {}

    mode = property(lambda self: self._core.mode)
    policy = property(lambda self: self._core.policy)

    async def _read(self, mint: str) -> GuardSummary:
        c = self._client
        if self._core.mode == "free":
            summary = GuardSummary(mint, "free")
            read_launch_tool(summary, await c.launch_tool(mint))
            return summary

        async def nothing() -> None:
            return None

        analysis, scan, insiders = await asyncio.gather(
            c.analyze(mint),
            c.launch_tool(mint),
            c.insiders(mint) if self._core.use_insiders else nothing(),
            return_exceptions=True,
        )
        return self._core.full_summary(mint, analysis, scan, insiders)

    async def _run(self, mint: str) -> GuardResult:
        started = time.monotonic()
        try:
            timeout = self._core.timeout if self._core.timeout > 0 else None
            summary = await asyncio.wait_for(self._read(mint), timeout)
        except asyncio.TimeoutError:
            return self._core.failure(mint, GuardTimeout(self._core.timeout), started)
        except Exception as e:  # noqa: BLE001
            return self._core.failure(mint, e, started)
        return self._core.success(mint, summary, started)

    async def check(self, mint: str) -> GuardResult:
        """Checks a token mint against the policy. Never raises: errors come back shaped by ``fail_open``."""
        mint = str(mint or "").strip()
        early = self._core.invalid(mint) or self._core.cached(mint)
        if early is not None:
            return early
        pending = self._inflight.get(mint)
        if pending is not None:
            return await asyncio.shield(pending)
        task = asyncio.ensure_future(self._run(mint))
        self._inflight[mint] = task
        task.add_done_callback(lambda _: self._inflight.pop(mint, None))
        return await asyncio.shield(task)

    async def assert_allowed(self, mint: str) -> GuardResult:
        result = await self.check(mint)
        if not result.allow:
            raise GuardBlocked(result)
        return result

    def clear_cache(self) -> None:
        self._core.clear_cache()

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
        if callable(close):
            out = close()
            if asyncio.iscoroutine(out):
                await out

    async def __aenter__(self) -> "AsyncGuard":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()


def create_guard(api_key: Optional[str] = None, **kwargs: Any) -> Guard:
    """``guard = create_guard()``; ``guard.check(mint).allow`` before every buy."""
    return Guard(api_key, **kwargs)


def create_async_guard(api_key: Optional[str] = None, **kwargs: Any) -> AsyncGuard:
    return AsyncGuard(api_key, **kwargs)


def with_guard(guard: Guard | AsyncGuard, buy: Callable[..., Any]) -> Callable[..., Any]:
    """Wraps a buy function (``buy(mint, ...)``, sync or async) so it only runs for allowed tokens;
    a blocked one raises ``GuardBlocked``."""
    if isinstance(guard, AsyncGuard):

        async def guarded_async(mint: str, *args: Any, **kwargs: Any) -> Any:
            await guard.assert_allowed(mint)
            out = buy(mint, *args, **kwargs)
            return await out if isinstance(out, Awaitable) else out

        return guarded_async

    def guarded(mint: str, *args: Any, **kwargs: Any) -> Any:
        guard.assert_allowed(mint)
        return buy(mint, *args, **kwargs)

    return guarded
