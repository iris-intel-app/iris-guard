"""iris-guard: a pre-trade rug filter for Solana trading bots, powered by Iris (iriscan.app).

    from iris_guard import create_guard

    guard = create_guard()            # IRIS_API_KEY from the environment, if set
    if not guard.check(mint).allow:
        return                        # bundled, dev dumping, Proxima-launched...
"""

from .guard import AsyncGuard, Guard, GuardBlocked, GuardTimeout, create_async_guard, create_guard, with_guard
from .policy import DEFAULT_POLICY, Policy, evaluate
from .types import GuardResult, GuardSummary

__all__ = [
    "AsyncGuard",
    "DEFAULT_POLICY",
    "Guard",
    "GuardBlocked",
    "GuardResult",
    "GuardSummary",
    "GuardTimeout",
    "Policy",
    "create_async_guard",
    "create_guard",
    "evaluate",
    "with_guard",
]
from .guard import VERSION as __version__  # noqa: E402
