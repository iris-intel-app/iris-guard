"""Drop-in guard for a bot that buys through Jupiter.

One line before the quote: a blocked token never gets a quote, a transaction or your SOL.

    pip install iris-guard solana solders httpx
    IRIS_API_KEY=iris_live_... python jupiter_before_buy.py <mint> <sol>
"""

import base64
import os
import sys

import httpx
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from iris_guard import create_guard

SOL = "So11111111111111111111111111111111111111112"
JUPITER = "https://lite-api.jup.ag/swap/v1"

guard = create_guard(
    os.environ.get("IRIS_API_KEY"),  # without one: free mode (launch tools only)
    fail_open=False,  # Iris down or slow? Don't buy.
    timeout=15,
    max_bundle_held_pct=10,
    max_dev_held_pct=10,
    max_risk_score=70,
)


def buy(rpc: Client, wallet: Keypair, mint: str, sol: float):
    # ---- the guard: the only line you add to your bot ----
    verdict = guard.check(mint)
    if not verdict.allow:
        print(f"skip {mint}: {'; '.join(verdict.reasons)}")
        return None
    # -------------------------------------------------------

    quote = httpx.get(f"{JUPITER}/quote", params={"inputMint": SOL, "outputMint": mint, "amount": int(sol * 1e9), "slippageBps": 300}).json()
    if "error" in quote:
        raise RuntimeError(f"no quote: {quote['error']}")
    swap = httpx.post(
        f"{JUPITER}/swap",
        json={"quoteResponse": quote, "userPublicKey": str(wallet.pubkey()), "dynamicComputeUnitLimit": True},
    ).json()
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(swap["swapTransaction"]))
    signed = VersionedTransaction(unsigned.message, [wallet])
    signature = rpc.send_raw_transaction(bytes(signed)).value
    print(f"bought {mint}: {signature}")
    return signature


if __name__ == "__main__":
    mint, sol = sys.argv[1], float(sys.argv[2] if len(sys.argv) > 2 else "0.01")
    wallet = Keypair.from_json(os.environ["WALLET_SECRET_KEY"])  # a JSON byte array, as solana-keygen writes it
    buy(Client(os.environ.get("RPC_URL", "https://api.mainnet-beta.solana.com")), wallet, mint, sol)
