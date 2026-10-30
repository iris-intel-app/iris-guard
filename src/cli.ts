#!/usr/bin/env node
import { createGuard } from "./guard.ts";
import type { GuardResult, Mode } from "./types.ts";

const HELP = `Usage: iris-guard <mint> [options]

Checks a Solana token before you buy it. Prints ALLOW or BLOCK with the reasons.
Exit code: 0 ALLOW, 1 BLOCK (or Iris failed, fail-closed), 2 bad usage.

Options:
  --free               Free mode: the launch-tool scan only, no credits spent
  --full               Full mode: adds /analyze and /insiders (needs IRIS_API_KEY)
  --no-insiders        Full mode without the insider search (saves 2 credits)
  --fail-open          ALLOW when Iris errors or times out (default: BLOCK)
  --timeout <ms>       Deadline for the whole check (default 20000)
  --max-bundle <pct>   Block when the bundle still holds this % or more (default 10)
  --max-dev <pct>      Block when the dev still holds this % or more (default 10)
  --dump-within <s>    Block when the dev dumped within this many seconds (default 300)
  --max-risk <score>   Block at this Iris risk score or more (default 70)
  --max-launches <n>   Block when the creator launched this many tokens or more (default off)
  --json               Print the full result as JSON
  -h, --help           Show this help

Environment: IRIS_API_KEY (optional; get one at https://iriscan.app/pricing), IRIS_BASE_URL.`;

function fail(message: string): never {
  process.stderr.write(`iris-guard: ${message}\n\n${HELP}\n`);
  process.exit(2);
}

function parse(argv: string[]) {
  const out: { mint?: string; mode?: Mode; json: boolean; failOpen: boolean; insiders: boolean; timeoutMs?: number; policy: Record<string, number> } = {
    json: false,
    failOpen: false,
    insiders: true,
    policy: {},
  };
  const number = (flag: string, value: string | undefined) => {
    const n = Number(value);
    if (value === undefined || !Number.isFinite(n)) fail(`${flag} needs a number`);
    return n;
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "-h":
      case "--help":
        process.stdout.write(`${HELP}\n`);
        process.exit(0);
      case "--free":
        out.mode = "free";
        break;
      case "--full":
        out.mode = "full";
        break;
      case "--no-insiders":
        out.insiders = false;
        break;
      case "--fail-open":
        out.failOpen = true;
        break;
      case "--json":
        out.json = true;
        break;
      case "--timeout":
        out.timeoutMs = number(arg, argv[++i]);
        break;
      case "--max-bundle":
        out.policy.maxBundleHeldPct = number(arg, argv[++i]);
        break;
      case "--max-dev":
        out.policy.maxDevHeldPct = number(arg, argv[++i]);
        break;
      case "--dump-within":
        out.policy.devDumpWithinSeconds = number(arg, argv[++i]);
        break;
      case "--max-risk":
        out.policy.maxRiskScore = number(arg, argv[++i]);
        break;
      case "--max-launches":
        out.policy.maxCreatorLaunches = number(arg, argv[++i]);
        break;
      default:
        if (arg.startsWith("-")) fail(`unknown option ${arg}`);
        if (out.mint) fail("one mint at a time");
        out.mint = arg;
    }
  }
  if (!out.mint) fail("a token mint is needed");
  return out;
}

function print(result: GuardResult) {
  const lines = [`${result.allow ? "ALLOW" : "BLOCK"} ${result.mint} (${result.mode} mode, ${result.latencyMs} ms)`];
  for (const r of result.reasons) lines.push(`  - ${r}`);
  for (const w of result.warnings) lines.push(`  ! ${w}`);
  if (result.mode === "free" && !result.error) lines.push("  Free mode reads launch tools only. Bundles, dev holdings and risk need a key: https://iriscan.app/pricing");
  process.stdout.write(`${lines.join("\n")}\n`);
}

const args = parse(process.argv.slice(2));
const guard = createGuard({
  ...(args.mode && { mode: args.mode }),
  ...(process.env.IRIS_BASE_URL && { baseUrl: process.env.IRIS_BASE_URL }),
  ...(args.timeoutMs !== undefined && { timeoutMs: args.timeoutMs }),
  failOpen: args.failOpen,
  insiders: args.insiders,
  cacheTtlMs: 0,
  policy: args.policy,
});
if (guard.mode === "full" && !process.env.IRIS_API_KEY) fail("--full needs IRIS_API_KEY");
const result = await guard.check(args.mint!);
if (args.json) process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
else print(result);
process.exit(result.allow ? 0 : 1);
