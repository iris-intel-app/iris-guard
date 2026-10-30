// A live smoke test against https://iriscan.app/api, on the free launch-tool scan only and
// without an API key. Skipped unless IRIS_LIVE=1:  IRIS_LIVE=1 node --test test/live.test.ts
import assert from "node:assert/strict";
import { it } from "node:test";
import { createGuard } from "../src/index.ts";

// A serial launcher: no launch-tool evidence, a dozen tokens launched.
const SERIAL_LAUNCHER = "2zy2NEyvzXfPkdFesbisZViTyz6oCWERFEvSD9PfoRg1";

it("checks a real wallet in free mode, without a key", { skip: process.env.IRIS_LIVE !== "1" && "set IRIS_LIVE=1 to run" }, async () => {
  const guard = createGuard({ apiKey: "", mode: "free", timeoutMs: 60_000, ...(process.env.IRIS_BASE_URL && { baseUrl: process.env.IRIS_BASE_URL }) });
  const r = await guard.check(SERIAL_LAUNCHER);
  console.log(JSON.stringify({ allow: r.allow, reasons: r.reasons, warnings: r.warnings, latencyMs: r.latencyMs, error: r.error, launchTool: r.summary?.launchTool, verdict: r.summary?.launchToolVerdict, creatorLaunches: r.summary?.creatorLaunches }));
  assert.equal(r.error, undefined, `Iris answered with an error: ${r.error?.message}`);
  assert.equal(r.summary?.launchToolVerdict, "none");
  assert.ok((r.summary?.creatorLaunches ?? 0) >= 1, "expected the wallet's launches");
});
