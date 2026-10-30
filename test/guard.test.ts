import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { createGuard, DEFAULT_POLICY, evaluate, GuardBlockedError, withGuard } from "../src/index.ts";
import type { GuardOptions, IrisClient } from "../src/index.ts";
import { emptySummary } from "../src/summarize.ts";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const MINT = "So11111111111111111111111111111111111111112";

class FakeIrisError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** A mocked SDK client: each method answers what it is given, and counts its calls. */
function mock(answers: { launchTool?: unknown; analyze?: unknown; insiders?: unknown }) {
  const calls = { launchTool: 0, analyze: 0, insiders: 0 };
  const answer = (v: unknown) => (typeof v === "function" ? (v as () => Promise<unknown>)() : v instanceof Error ? Promise.reject(v) : Promise.resolve(v));
  const client: IrisClient = {
    launchTool: async () => (calls.launchTool++, answer(answers.launchTool)),
    analyze: async () => (calls.analyze++, answer(answers.analyze)),
    insiders: async () => (calls.insiders++, answer(answers.insiders)),
  };
  return { client, calls };
}

const guard = (client: IrisClient, options: GuardOptions = {}) => createGuard({ mode: "free", ...options, client });

describe("free mode (launch-tool scan only)", () => {
  it("allows a token whose creator shows no launch tool, and warns about serial launches", async () => {
    const { client, calls } = mock({ launchTool: fixture("launch-tool-serial") });
    const r = await guard(client).check(MINT);
    assert.equal(r.allow, true);
    assert.deepEqual(r.reasons, []);
    assert.deepEqual(r.warnings, ["Creator launched 12 tokens"]);
    assert.equal(r.summary?.launchTool, null, "the 'tool' field alone is not a detection");
    assert.equal(r.summary?.creatorLaunches, 12);
    assert.equal(r.mode, "free");
    assert.deepEqual(calls, { launchTool: 1, analyze: 0, insiders: 0 });
  });

  it("blocks a Proxima launch", async () => {
    const { client } = mock({ launchTool: fixture("launch-tool-proxima") });
    const r = await guard(client).check(MINT);
    assert.equal(r.allow, false);
    assert.deepEqual(r.reasons, ["Launch tool: Proxima"]);
  });

  it("blocks a likely launch tool by default, warns when told to", async () => {
    const likely = { ...fixture("launch-tool-proxima"), verdict: "likely" };
    assert.equal((await guard(mock({ launchTool: likely }).client).check(MINT)).allow, false);
    const r = await guard(mock({ launchTool: likely }).client, { policy: { blockLikelyLaunchTools: false } }).check(MINT);
    assert.equal(r.allow, true);
    assert.deepEqual(r.warnings, ["Launch tool (likely): Proxima"]);
  });

  it("blocks serial launchers when maxCreatorLaunches is set", async () => {
    const r = await guard(mock({ launchTool: fixture("launch-tool-serial") }).client, { policy: { maxCreatorLaunches: 5 } }).check(MINT);
    assert.equal(r.allow, false);
    assert.deepEqual(r.reasons, ["Creator launched 12 tokens (max 5)"]);
  });
});

describe("full mode (analyze + insiders + launch-tool)", () => {
  it("blocks a rug for every rule it breaks", async () => {
    const { client, calls } = mock({ analyze: fixture("analyze-rug"), insiders: fixture("insiders-linked"), launchTool: fixture("launch-tool-serial") });
    const r = await guard(client, { mode: "full" }).check(MINT);
    assert.equal(r.allow, false);
    assert.deepEqual(r.reasons, [
      "Bundle still holds 34.2% of the supply (max 10%)",
      "Dev dumped 42 s after launch (limit 5 min)",
      "Wallets linked to the dev hold 25.3% of the supply (max 20%)",
      "Iris risk score 82/100 (max 70)",
    ]);
    assert.equal(r.summary?.devDumpSeconds, 42);
    assert.deepEqual(calls, { launchTool: 1, analyze: 1, insiders: 1 });
  });

  it("allows a clean token", async () => {
    const { client } = mock({ analyze: fixture("analyze-clean"), insiders: { dev: { address: "dev" }, summary: { insiders: 0, held_share: 0.01 }, insiders: [], complete: true }, launchTool: fixture("launch-tool-serial") });
    const r = await guard(client, { mode: "full" }).check(MINT);
    assert.equal(r.allow, true, r.reasons.join("; "));
    assert.equal(r.summary?.bundled, false);
    assert.equal(r.summary?.devHeldPct, 2);
    assert.equal(r.summary?.riskScore, 12);
  });

  it("blocks a dev who still holds too much", async () => {
    const analysis = fixture("analyze-clean");
    analysis.token.story.dev.held_share = 0.15;
    const r = await guard(mock({ analyze: analysis, insiders: null, launchTool: null }).client, { mode: "full" }).check(MINT);
    assert.deepEqual(r.reasons, ["Dev still holds 15.0% of the supply (max 10%)"]);
  });

  it("reads a launch kit from the analysis", async () => {
    const analysis = fixture("analyze-clean");
    analysis.token.launch_tool.verdict = "blockx";
    const r = await guard(mock({ analyze: analysis, insiders: null, launchTool: fixture("launch-tool-serial") }).client, { mode: "full" }).check(MINT);
    assert.deepEqual(r.reasons, ["Launch tool: BlockX"]);
  });

  it("skips the insider search when told to", async () => {
    const { client, calls } = mock({ analyze: fixture("analyze-clean"), launchTool: fixture("launch-tool-serial") });
    await guard(client, { mode: "full", insiders: false }).check(MINT);
    assert.equal(calls.insiders, 0);
  });

  it("goes on without the free scan or the insider search when they fail", async () => {
    const { client } = mock({ analyze: fixture("analyze-clean"), insiders: new FakeIrisError(500, "boom"), launchTool: new FakeIrisError(429, "Too many") });
    const r = await guard(client, { mode: "full" }).check(MINT);
    assert.equal(r.allow, true);
    assert.equal(r.error, undefined);
    assert.ok(r.summary?.notes.some((n) => n.startsWith("Insider search skipped")));
    assert.ok(r.summary?.notes.some((n) => n.startsWith("Launch-tool scan skipped")));
  });

  it("is the default mode with an API key", () => {
    assert.equal(createGuard({ apiKey: "iris_live_test", client: mock({}).client }).mode, "full");
    assert.equal(createGuard({ apiKey: "iris_live_test", mode: "free", client: mock({}).client }).mode, "free");
  });
});

describe("failures", () => {
  it("fails closed by default", async () => {
    const r = await guard(mock({ launchTool: new FakeIrisError(500, "The launch-tool scan failed") }).client).check(MINT);
    assert.equal(r.allow, false);
    assert.equal(r.error?.status, 500);
    assert.match(r.reasons[0], /^Iris check failed \(fail-closed\): The launch-tool scan failed/);
  });

  it("fails open when told to", async () => {
    const r = await guard(mock({ launchTool: new FakeIrisError(500, "down") }).client, { failOpen: true }).check(MINT);
    assert.equal(r.allow, true);
    assert.deepEqual(r.reasons, []);
    assert.match(r.warnings[0], /fail-open/);
  });

  it("fails on an analysis error in full mode", async () => {
    const r = await guard(mock({ analyze: new FakeIrisError(402, "Not enough credits", "no_credits"), launchTool: fixture("launch-tool-serial") }).client, { mode: "full" }).check(MINT);
    assert.equal(r.allow, false);
    assert.match(r.error!.message, /iriscan\.app\/pricing/);
  });

  it("points to pricing on a missing key", async () => {
    const r = await guard(mock({ launchTool: new FakeIrisError(401, "Log in to use Iris", "login") }).client).check(MINT);
    assert.match(r.reasons[0], /get an API key: https:\/\/iriscan\.app\/pricing/);
  });

  it("times out", async () => {
    const never = () => new Promise(() => {});
    const r = await guard(mock({ launchTool: never }).client, { timeoutMs: 50 }).check(MINT);
    assert.equal(r.allow, false);
    assert.match(r.error!.message, /did not answer within 50 ms/);
    assert.ok(r.latencyMs >= 45 && r.latencyMs < 1000, `latency ${r.latencyMs}`);
    const open = await guard(mock({ launchTool: never }).client, { timeoutMs: 50, failOpen: true }).check(MINT);
    assert.equal(open.allow, true);
  });

  it("refuses what is not a mint without calling Iris", async () => {
    const { client, calls } = mock({});
    const r = await guard(client).check("not-a-mint");
    assert.equal(r.allow, false);
    assert.equal(calls.launchTool, 0);
  });
});

describe("cache", () => {
  it("reuses a result within the TTL", async () => {
    const { client, calls } = mock({ launchTool: fixture("launch-tool-serial") });
    const g = guard(client);
    const first = await g.check(MINT);
    const second = await g.check(MINT);
    assert.equal(first.cached, false);
    assert.equal(second.cached, true);
    assert.equal(second.allow, first.allow);
    assert.equal(calls.launchTool, 1);
  });

  it("calls again once the TTL is over", async () => {
    const { client, calls } = mock({ launchTool: fixture("launch-tool-serial") });
    const g = guard(client, { cacheTtlMs: 20 });
    await g.check(MINT);
    await new Promise((r) => setTimeout(r, 40));
    assert.equal((await g.check(MINT)).cached, false);
    assert.equal(calls.launchTool, 2);
  });

  it("never caches a failure", async () => {
    const { client, calls } = mock({ launchTool: new FakeIrisError(503, "busy") });
    const g = guard(client);
    await g.check(MINT);
    await g.check(MINT);
    assert.equal(calls.launchTool, 2);
  });

  it("shares one call between concurrent checks of a mint", async () => {
    const { client, calls } = mock({ launchTool: () => new Promise((r) => setTimeout(() => r(fixture("launch-tool-serial")), 20)) });
    const g = guard(client);
    const [a, b] = await Promise.all([g.check(MINT), g.check(MINT)]);
    assert.equal(a.allow, b.allow);
    assert.equal(calls.launchTool, 1);
  });

  it("can be turned off and cleared", async () => {
    const { client, calls } = mock({ launchTool: fixture("launch-tool-serial") });
    const off = guard(client, { cacheTtlMs: 0 });
    await off.check(MINT);
    await off.check(MINT);
    assert.equal(calls.launchTool, 2);
    const g = guard(client);
    await g.check(MINT);
    g.clearCache();
    await g.check(MINT);
    assert.equal(calls.launchTool, 4);
  });
});

describe("policy", () => {
  it("treats unknown facts as neither safe nor unsafe", () => {
    const r = evaluate(emptySummary(MINT, "full"), DEFAULT_POLICY);
    assert.deepEqual(r, { allow: true, reasons: [], warnings: [] });
  });

  it("blocks at the threshold, not below it", () => {
    const s = { ...emptySummary(MINT, "full"), bundled: true, bundleHeldPct: 10, devHeldPct: 9.9, riskScore: 70 };
    assert.deepEqual(evaluate(s, DEFAULT_POLICY).reasons, ["Bundle still holds 10.0% of the supply (max 10%)", "Iris risk score 70/100 (max 70)"]);
  });

  it("turns a rule off with null", () => {
    const s = { ...emptySummary(MINT, "full"), riskScore: 99, devDumpSeconds: 5 };
    assert.equal(evaluate(s, { ...DEFAULT_POLICY, maxRiskScore: null, devDumpWithinSeconds: null }).allow, true);
  });

  it("runs a custom rule", async () => {
    const r = await guard(mock({ launchTool: fixture("launch-tool-serial") }).client, {
      policy: { custom: (s) => ((s.creatorLaunches ?? 0) > 10 ? "Creator is a launch factory" : null) },
    }).check(MINT);
    assert.deepEqual(r.reasons, ["Creator is a launch factory"]);
  });
});

describe("helpers", () => {
  it("assert throws on a block", async () => {
    const g = guard(mock({ launchTool: fixture("launch-tool-proxima") }).client);
    await assert.rejects(g.assert(MINT), (e: unknown) => e instanceof GuardBlockedError && !e.result.allow);
  });

  it("withGuard only buys allowed tokens", async () => {
    let bought = 0;
    const buy = async (_mint: string, sol: number) => (bought += sol);
    const blocked = withGuard(guard(mock({ launchTool: fixture("launch-tool-proxima") }).client), buy);
    await assert.rejects(blocked(MINT, 1), GuardBlockedError);
    const allowed = withGuard(guard(mock({ launchTool: fixture("launch-tool-serial") }).client), buy);
    await allowed(MINT, 0.5);
    assert.equal(bought, 0.5);
  });
});
