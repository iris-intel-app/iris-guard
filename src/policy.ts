import type { GuardSummary, Policy } from "./types.ts";

/**
 * The default policy. Every threshold is a starting point: override any of them in `createGuard({ policy })`.
 *
 * - Bundle 10%: a bundle sitting on a tenth of the supply can dump it on the first buyers.
 * - Dev 10%: a pump.fun dev's own launch buy is usually a few percent; ten or more is a loaded gun.
 * - Dev dump 5 minutes: a dev who is done selling within minutes of the launch ran a pump and dump.
 * - Insiders 20%: wallets the dev funded or was funded with, together, holding a fifth of the supply.
 * - Risk 70: the score at which Iris itself calls a token HIGH risk.
 * - Launch tools: Proxima and BlockX exist to launch, bundle and dump tokens from fleets of wallets.
 * - Serial launches: reported as a warning only; many honest devs launch more than once.
 */
export const DEFAULT_POLICY: Readonly<Policy> = Object.freeze({
  maxBundleHeldPct: 10,
  maxDevHeldPct: 10,
  devDumpWithinSeconds: 300,
  maxInsiderHeldPct: 20,
  maxRiskScore: 70,
  blockLaunchTools: true,
  blockLikelyLaunchTools: true,
  maxCreatorLaunches: null,
});

const pct = (n: number) => `${n.toFixed(1)}%`;

function duration(seconds: number) {
  if (seconds < 120) return `${Math.round(seconds)} s`;
  if (seconds < 7200) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

/** Applies `policy` to what a check found: the reasons to block it, and the facts worth a warning. */
export function evaluate(summary: GuardSummary, policy: Policy): { allow: boolean; reasons: string[]; warnings: string[] } {
  const reasons: string[] = [];
  const warnings: string[] = [];
  const at = (value: number | null, max: number | null) => value !== null && max !== null && value >= max;

  if (summary.launchTool && summary.launchToolVerdict && summary.launchToolVerdict !== "none") {
    const likely = summary.launchToolVerdict === "likely";
    const what = `Launch tool${likely ? " (likely)" : ""}: ${summary.launchTool}`;
    if (policy.blockLaunchTools && (!likely || policy.blockLikelyLaunchTools)) reasons.push(what);
    else warnings.push(what);
  }

  if (summary.bundled && at(summary.bundleHeldPct, policy.maxBundleHeldPct)) {
    reasons.push(`Bundle still holds ${pct(summary.bundleHeldPct!)} of the supply (max ${policy.maxBundleHeldPct}%)`);
  } else if (summary.bundled) {
    warnings.push(summary.bundleHeldPct === null ? "Bundled launch" : `Bundled launch, the bundle holds ${pct(summary.bundleHeldPct)} now`);
  }

  if (at(summary.devHeldPct, policy.maxDevHeldPct)) {
    reasons.push(`Dev still holds ${pct(summary.devHeldPct!)} of the supply (max ${policy.maxDevHeldPct}%)`);
  }

  if (summary.devDumpSeconds !== null && policy.devDumpWithinSeconds !== null && summary.devDumpSeconds <= policy.devDumpWithinSeconds) {
    reasons.push(`Dev dumped ${duration(summary.devDumpSeconds)} after launch (limit ${duration(policy.devDumpWithinSeconds)})`);
  } else if (summary.devSold) {
    warnings.push("Dev sold");
  }

  if (at(summary.insiderHeldPct, policy.maxInsiderHeldPct)) {
    reasons.push(`Wallets linked to the dev hold ${pct(summary.insiderHeldPct!)} of the supply (max ${policy.maxInsiderHeldPct}%)`);
  }

  if (at(summary.riskScore, policy.maxRiskScore)) {
    reasons.push(`Iris risk score ${summary.riskScore}/100 (max ${policy.maxRiskScore})`);
  }

  if (summary.creatorLaunches !== null && summary.creatorLaunches > 1) {
    const line = `Creator launched ${summary.creatorLaunches} tokens`;
    if (at(summary.creatorLaunches, policy.maxCreatorLaunches)) reasons.push(`${line} (max ${policy.maxCreatorLaunches})`);
    else warnings.push(line);
  }

  if (policy.custom) {
    const custom = policy.custom(summary);
    if (custom) reasons.push(custom);
  }

  return { allow: reasons.length === 0, reasons, warnings };
}
