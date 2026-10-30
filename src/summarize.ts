import { riskSummary } from "@iriscan/sdk";
import type { GuardSummary, LaunchToolVerdict, Mode } from "./types.ts";

// Each answer goes through the SDK's `riskSummary` first (bundle, dev, launch kit, risk score),
// then the readers below add what the policy needs on top: the dev's dump time, the creator's
// launches, the insiders' share and how sure the launch-kit verdict is. A missing field stays
// null ("Iris could not tell"); it never counts as safe or unsafe by itself. When two answers
// both give a figure, the higher one is kept: a guard errs on the side of caution.

type Obj = Record<string, any>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const share = (v: unknown): number | null => {
  const n = num(v);
  return n === null ? null : Math.round(n * 1000) / 10; // 0..1 → percent, one decimal
};
const seconds = (v: unknown): number | null => {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const t = Date.parse(v);
    return Number.isNaN(t) ? null : t / 1000;
  }
  return null;
};

export function emptySummary(mint: string, mode: Mode): GuardSummary {
  return {
    mint,
    mode,
    creator: null,
    creatorLaunches: null,
    launchTool: null,
    launchToolVerdict: null,
    bundled: null,
    bundleHeldPct: null,
    devHeldPct: null,
    devSold: null,
    devDumpSeconds: null,
    insiderHeldPct: null,
    riskScore: null,
    notes: [],
  };
}

const higher = (a: number | null, b: number | null) => (a === null ? b : b === null ? a : Math.max(a, b));
const either = (a: boolean | null, b: boolean | null) => (a === true || b === true ? true : a ?? b);

function addNotes(s: GuardSummary, lines: unknown) {
  if (!Array.isArray(lines)) return;
  for (const line of lines) if (typeof line === "string" && line && !s.notes.includes(line)) s.notes.push(line);
}

/** Folds the SDK's `riskSummary` of one answer into the summary. */
function fold(s: GuardSummary, result: Obj): string | null {
  const r = riskSummary(result as any);
  s.bundled = either(s.bundled, r.bundled);
  s.bundleHeldPct = higher(s.bundleHeldPct, r.bundleHeldPct);
  s.devSold = either(s.devSold, r.devSold);
  s.devHeldPct = higher(s.devHeldPct, r.devHeldPct);
  s.riskScore = higher(s.riskScore, r.riskScore);
  addNotes(s, r.notes);
  return r.launchTool;
}

const rank: Record<LaunchToolVerdict, number> = { none: 0, likely: 1, tool: 2 };

function setLaunchTool(s: GuardSummary, tool: string | null, verdict: LaunchToolVerdict) {
  if (s.launchToolVerdict === null || rank[verdict] > rank[s.launchToolVerdict]) {
    s.launchToolVerdict = verdict;
    s.launchTool = verdict === "none" ? null : tool;
  }
}

/**
 * `POST /launch-tool` scanned the token's creator. Its "tool" field names the tool checked even
 * when nothing was found: only a verdict other than "none" is a detection.
 */
export function readLaunchTool(s: GuardSummary, report: Obj | null | undefined) {
  if (!report || typeof report !== "object") return;
  const name = fold(s, report);
  if (typeof report.wallet === "string") s.creator ??= report.wallet;
  if (Array.isArray(report.tokens_launched)) s.creatorLaunches = report.tokens_launched.length;
  const verdict = report.verdict;
  if (verdict === "tool" || verdict === "likely" || verdict === "none") setLaunchTool(s, name ?? "a launch tool", verdict);
}

/** `POST /analyze` on the mint: the token's risk, launch, bundle, dev and launch-kit check. */
export function readAnalyze(s: GuardSummary, profile: Obj | null | undefined) {
  if (!profile || typeof profile !== "object") return;
  const kitName = fold(s, profile);
  const token: Obj | undefined = profile.token;
  if (!token) return;
  const launch: Obj | undefined = token.launch;
  if (typeof launch?.creator === "string") s.creator = launch.creator;

  // The story reads what the bundle and the dev hold from their balances now, when it can.
  const story: Obj | undefined = token.story;
  s.bundleHeldPct = higher(s.bundleHeldPct, share(story?.bundle?.held_share));
  const dev: Obj | undefined = story?.dev;
  if (dev) {
    s.devHeldPct = higher(s.devHeldPct, share(dev.held_share));
    if (dev.exited === true) s.devSold = true;
    const launched = seconds(launch?.created_at);
    const exit = seconds(dev.exit_at);
    if (dev.exited && launched !== null && exit !== null) s.devDumpSeconds = Math.max(0, exit - launched);
  }

  // How sure the analysis's launch-kit check is: a kit's marks, or only funding laid out like one.
  const kit: Obj | null | undefined = token.launch_tool;
  if (kit && typeof kit.verdict === "string") {
    const verdict: LaunchToolVerdict = kit.verdict === "none" ? "none" : kit.verdict === "funded_like_kit" ? "likely" : "tool";
    setLaunchTool(s, kitName ?? (typeof kit.tool === "string" ? kit.tool : "a launch kit"), verdict);
  }
  addNotes(s, profile.summary);
}

/** `POST /insiders` on the mint: the wallets linked to the dev by money, and what they hold. */
export function readInsiders(s: GuardSummary, result: Obj | null | undefined) {
  if (!result || typeof result !== "object") return;
  fold(s, result);
  if (typeof result.dev?.address === "string") s.creator ??= result.dev.address;
  s.insiderHeldPct = higher(s.insiderHeldPct, share(result.summary?.held_share));
}
