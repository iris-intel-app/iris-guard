// Drop-in guard for a bot that buys through Jupiter.
// One line before the quote: a blocked token never gets a quote, a transaction or your SOL.
//
//   npm i iris-guard @solana/web3.js
//   IRIS_API_KEY=iris_live_... RPC_URL=... WALLET_SECRET_KEY=[...] npx tsx jupiter-before-buy.ts <mint> <sol>
import { Connection, Keypair, VersionedTransaction } from "@solana/web3.js";
import { createGuard } from "iris-guard";

const SOL = "So11111111111111111111111111111111111111112";
const JUPITER = "https://lite-api.jup.ag/swap/v1";

const guard = createGuard({
  apiKey: process.env.IRIS_API_KEY, // without one: free mode (launch tools only)
  failOpen: false, // Iris down or slow? Don't buy.
  timeoutMs: 15_000,
  policy: { maxBundleHeldPct: 10, maxDevHeldPct: 10, maxRiskScore: 70 },
});

export async function buy(connection: Connection, wallet: Keypair, mint: string, sol: number) {
  // ---- the guard: the only line you add to your bot ----
  const verdict = await guard.check(mint);
  if (!verdict.allow) {
    console.log(`skip ${mint}: ${verdict.reasons.join("; ")}`);
    return null;
  }
  // -------------------------------------------------------

  const params = new URLSearchParams({ inputMint: SOL, outputMint: mint, amount: String(Math.round(sol * 1e9)), slippageBps: "300" });
  const quote = await (await fetch(`${JUPITER}/quote?${params}`)).json();
  if (quote.error) throw new Error(`no quote: ${quote.error}`);

  const swap = await fetch(`${JUPITER}/swap`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ quoteResponse: quote, userPublicKey: wallet.publicKey.toBase58(), dynamicComputeUnitLimit: true }),
  }).then((r) => r.json());

  const tx = VersionedTransaction.deserialize(Buffer.from(swap.swapTransaction, "base64"));
  tx.sign([wallet]);
  const signature = await connection.sendRawTransaction(tx.serialize(), { skipPreflight: true, maxRetries: 2 });
  console.log(`bought ${mint}: ${signature}`);
  return signature;
}

// Run as a script: npx tsx jupiter-before-buy.ts <mint> <sol>
if (import.meta.url === `file://${process.argv[1]}`) {
  const [mint, sol = "0.01"] = process.argv.slice(2);
  const secret = JSON.parse(process.env.WALLET_SECRET_KEY ?? "[]"); // a JSON byte array, as solana-keygen writes it
  await buy(new Connection(process.env.RPC_URL ?? "https://api.mainnet-beta.solana.com"), Keypair.fromSecretKey(Uint8Array.from(secret)), mint, Number(sol));
}
