"""Drop-in guard for a pump.fun sniper: new mint, guard check, then buy.

The guard sits between your "new token" feed and your buy function; neither changes.

    pip install iris-guard websockets
    IRIS_API_KEY=iris_live_... python pumpfun_sniper.py
"""

import asyncio
import json
import os

import websockets

from iris_guard import create_async_guard

guard = create_async_guard(
    os.environ.get("IRIS_API_KEY"),
    fail_open=False,  # a sniper that buys blind when Iris is slow is the bot rugs are built for
    timeout=8,  # past this the entry is gone anyway: skip it
    cache_ttl=120,  # the same mint seen twice is checked once
    block_launch_tools=True,  # Proxima / BlockX fleets: launched to be dumped on snipers
    max_creator_launches=10,  # a creator with 10+ launches is a token factory
)


async def buy(mint: str) -> None:
    """Your existing buy (Jupiter, PumpPortal's trade API, a direct bonding-curve buy...)."""
    print(f"BUY {mint}")


async def on_new_mint(mint: str) -> None:
    verdict = await guard.check(mint)
    if not verdict.allow:
        print(f"BLOCK {mint} ({verdict.latency_ms} ms): {'; '.join(verdict.reasons)}")
        return
    print(f"ALLOW {mint} ({verdict.latency_ms} ms)")
    await buy(mint)


async def listen() -> None:
    # A new-token feed. Any source works: a Geyser stream, logsSubscribe on the pump.fun program,
    # or a public websocket like this one. Swap it for yours; on_new_mint stays the same.
    while True:
        try:
            async with websockets.connect("wss://pumpportal.fun/api/data") as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                async for message in ws:
                    event = json.loads(message)
                    if event.get("txType") == "create" and event.get("mint"):
                        asyncio.create_task(on_new_mint(event["mint"]))
        except (OSError, websockets.ConnectionClosed) as e:
            print(f"feed error: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(listen())
