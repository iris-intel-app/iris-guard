// Drop-in guard for a pump.fun sniper: new mint, guard check, then buy.
// The guard sits between your "new token" feed and your buy function; neither changes.
//
//   npm i iris-guard ws
//   IRIS_API_KEY=iris_live_... npx tsx pumpfun-sniper.ts
import WebSocket from "ws";
import { createGuard } from "iris-guard";

const guard = createGuard({
  apiKey: process.env.IRIS_API_KEY,
  failOpen: false, // a sniper that buys blind when Iris is slow is the bot rugs are built for
  timeoutMs: 8_000, // past this the entry is gone anyway: skip it
  cacheTtlMs: 120_000, // the same mint seen twice is checked once
  policy: {
    blockLaunchTools: true, // Proxima / BlockX fleets: launched to be dumped on snipers
    maxCreatorLaunches: 10, // a creator with 10+ launches is a token factory
  },
});

/** Your existing buy (Jupiter, PumpPortal's trade API, a direct bonding-curve buy...). */
async function buy(mint: string) {
  console.log(`BUY ${mint}`);
}

async function onNewMint(mint: string) {
  const verdict = await guard.check(mint);
  if (!verdict.allow) {
    console.log(`BLOCK ${mint} (${verdict.latencyMs} ms): ${verdict.reasons.join("; ")}`);
    return;
  }
  console.log(`ALLOW ${mint} (${verdict.latencyMs} ms)${verdict.warnings.length ? `: ${verdict.warnings.join("; ")}` : ""}`);
  await buy(mint);
}

// A new-token feed. Any source works: a Geyser stream, logsSubscribe on the pump.fun program,
// or a public websocket like this one. Swap it for yours; onNewMint stays the same.
function listen() {
  const ws = new WebSocket("wss://pumpportal.fun/api/data");
  ws.on("open", () => ws.send(JSON.stringify({ method: "subscribeNewToken" })));
  ws.on("message", (data) => {
    const event = JSON.parse(String(data));
    if (event.txType === "create" && event.mint) void onNewMint(event.mint);
  });
  ws.on("close", () => setTimeout(listen, 2_000));
  ws.on("error", (e) => console.error("feed error:", e.message));
}

listen();
