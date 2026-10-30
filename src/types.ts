/** What a check reads: free (the launch-tool scan only) or full (adds /analyze and /insiders). */
export type Mode = "free" | "full";

/** How sure Iris is that a launch tool made the token. */
export type LaunchToolVerdict = "tool" | "likely" | "none";

/** The facts a check found about a token. `null` means Iris could not tell (or the mode does not read it). */
export interface GuardSummary {
  mint: string;
  mode: Mode;
  /** The token's creator (its dev), when known. */
  creator: string | null;
  /** Tokens the creator launched, over the history Iris read (a serial launcher has many). */
  creatorLaunches: number | null;
  /** The launch tool found ("Proxima", "BlockX"), or null when none was found. */
  launchTool: string | null;
  launchToolVerdict: LaunchToolVerdict | null;
  /** A launch bundle was found: wallets one party bought the launch with. */
  bundled: boolean | null;
  /** Share of the supply the bundle still holds, in percent (0 to 100). */
  bundleHeldPct: number | null;
  /** Share of the supply the dev still holds, in percent. */
  devHeldPct: number | null;
  /** The dev sold (most of) what it got. */
  devSold: boolean | null;
  /** Seconds between the launch and the dev being done selling, when it was. */
  devDumpSeconds: number | null;
  /** Share of the supply held by wallets linked to the dev by money (/insiders), in percent. */
  insiderHeldPct: number | null;
  /** Iris risk score, 0 to 100 (70 and up is HIGH). */
  riskScore: number | null;
  /** Things to keep in mind, from Iris. */
  notes: string[];
}

export interface Policy {
  /** Block when a bundle was found and it still holds this share of the supply or more (percent). null: off. */
  maxBundleHeldPct: number | null;
  /** Block when the dev still holds this share of the supply or more (percent). null: off. */
  maxDevHeldPct: number | null;
  /** Block when the dev was done selling within this many seconds of the launch. null: off. */
  devDumpWithinSeconds: number | null;
  /** Block when wallets linked to the dev still hold this share of the supply or more (percent). null: off. */
  maxInsiderHeldPct: number | null;
  /** Block when the Iris risk score is this or more (0 to 100). null: off. */
  maxRiskScore: number | null;
  /** Block tokens made with a launch tool (Proxima, BlockX). */
  blockLaunchTools: boolean;
  /** Also block on "likely" (moderate evidence), not only on a confirmed tool fingerprint. */
  blockLikelyLaunchTools: boolean;
  /** Block when the creator launched this many tokens or more. null: off (reported as a warning). */
  maxCreatorLaunches: number | null;
  /** Your own rule: return a reason to block, or null to let it through. */
  custom?: (summary: GuardSummary) => string | null | undefined;
}

export interface GuardResult {
  mint: string;
  allow: boolean;
  /** Why it was blocked (empty when allowed). */
  reasons: string[];
  /** Facts worth knowing that did not block it. */
  warnings: string[];
  /** What the check found; null when the check failed before reading anything. */
  summary: GuardSummary | null;
  mode: Mode;
  latencyMs: number;
  /** Served from the in-memory cache. */
  cached: boolean;
  /** Set when Iris could not be reached or answered with an error; `allow` then follows `failOpen`. */
  error?: { message: string; status?: number; code?: string };
}
