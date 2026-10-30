import { Iris } from "@iriscan/sdk";
import { DEFAULT_POLICY, evaluate } from "./policy.ts";
import { emptySummary, readAnalyze, readInsiders, readLaunchTool } from "./summarize.ts";
import type { GuardResult, GuardSummary, Mode, Policy } from "./types.ts";

/** The Iris calls a guard makes: `Iris` from the SDK, or anything shaped like it. */
export interface IrisClient {
  launchTool(walletOrMint: string, options?: { mint?: string; signal?: AbortSignal }): Promise<any>;
  analyze(address: string, options?: { signal?: AbortSignal }): Promise<any>;
  insiders(mint: string, options?: { signal?: AbortSignal }): Promise<any>;
}

export interface GuardOptions {
  /** An Iris API key (iris_live_…). Defaults to the IRIS_API_KEY environment variable. */
  apiKey?: string;
  /** Defaults to https://iriscan.app/api. */
  baseUrl?: string;
  /** "free" reads the free launch-tool scan only; "full" adds /analyze and /insiders (credits). Default: "full" with a key, else "free". */
  mode?: Mode;
  /** Overrides of the default policy. */
  policy?: Partial<Policy>;
  /** When Iris errors or times out: true lets the buy through, false (the default) blocks it. */
  failOpen?: boolean;
  /** The whole check's deadline. Default 20000 ms. */
  timeoutMs?: number;
  /** How long a result is reused for the same mint. Default 60000 ms; 0 turns the cache off. */
  cacheTtlMs?: number;
  /** Full mode: also run the insider search (2 credits). Default true. */
  insiders?: boolean;
  /** A client to use instead of the SDK's (tests, proxies). */
  client?: IrisClient;
  /** A fetch implementation for the SDK. */
  fetch?: typeof fetch;
}

export interface Guard {
  /** Checks a token mint against the policy. Never throws: errors come back as a result shaped by `failOpen`. */
  check(mint: string): Promise<GuardResult>;
  /** Like `check`, but throws `GuardBlockedError` when the token is blocked. */
  assert(mint: string): Promise<GuardResult>;
  readonly mode: Mode;
  readonly policy: Readonly<Policy>;
  clearCache(): void;
}

export class GuardBlockedError extends Error {
  readonly result: GuardResult;
  constructor(result: GuardResult) {
    super(`iris-guard blocked ${result.mint}: ${result.reasons.join("; ")}`);
    this.name = "GuardBlockedError";
    this.result = result;
  }
}

class TimeoutError extends Error {
  constructor(ms: number) {
    super(`Iris did not answer within ${ms} ms`);
    this.name = "TimeoutError";
  }
}

/** Sent in the User-Agent, so Iris can tell guard traffic apart. */
export const VERSION = "0.1.0";

const BASE58 = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

function envKey(): string | undefined {
  const env = (globalThis as any).process?.env;
  const key = env?.IRIS_API_KEY;
  return typeof key === "string" && key.trim() ? key.trim() : undefined;
}

const PRICING = "https://iriscan.app/pricing";

function describe(e: unknown): NonNullable<GuardResult["error"]> {
  const err = e as any;
  const status = typeof err?.status === "number" ? err.status : undefined;
  const code = typeof err?.code === "string" ? err.code : undefined;
  let message = err instanceof Error ? err.message : String(e);
  if (status === 401 || code === "login" || code === "invalid_key") message += ` (get an API key: ${PRICING})`;
  else if (status === 402 || code === "no_credits") message += ` (out of credits: ${PRICING})`;
  else if (code === "daily_limit" || code === "quota_exceeded") message += ` (free plan limit reached: ${PRICING})`;
  if (status === 429 && err?.retryAfter) message += ` (retry after ${err.retryAfter} s)`;
  return { message, ...(status !== undefined && { status }), ...(code !== undefined && { code }) };
}

/** `work` within `ms`, else a TimeoutError; the calls still running are aborted. */
function withTimeout<T>(work: (signal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController();
  if (!(ms > 0) || !Number.isFinite(ms)) return work(controller.signal);
  let timer: ReturnType<typeof setTimeout>;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new TimeoutError(ms));
      controller.abort();
    }, ms);
  });
  return Promise.race([work(controller.signal), deadline]).finally(() => clearTimeout(timer));
}

/**
 * A pre-trade rug filter. `await guard.check(mint)` before every buy:
 *
 *     const guard = createGuard({ apiKey: process.env.IRIS_API_KEY });
 *     if (!(await guard.check(mint)).allow) return;
 */
export function createGuard(options: GuardOptions = {}): Guard {
  const apiKey = options.apiKey ?? envKey();
  const mode: Mode = options.mode ?? (apiKey ? "full" : "free");
  const policy: Policy = { ...DEFAULT_POLICY, ...options.policy };
  const failOpen = options.failOpen ?? false;
  const timeoutMs = options.timeoutMs ?? 20_000;
  const cacheTtlMs = options.cacheTtlMs ?? 60_000;
  const useInsiders = options.insiders ?? true;
  const client: IrisClient =
    options.client ??
    (new Iris({
      // "" when none: the guard already read IRIS_API_KEY, the SDK must not fall back to it.
      apiKey: apiKey ?? "",
      userAgent: `iris-guard/${VERSION}`,
      ...(options.baseUrl && { baseUrl: options.baseUrl }),
      ...(options.fetch && { fetch: options.fetch }),
      timeoutMs,
    }) as unknown as IrisClient);

  const cache = new Map<string, { expires: number; result: GuardResult }>();
  const inflight = new Map<string, Promise<GuardResult>>();

  async function read(mint: string, signal: AbortSignal): Promise<GuardSummary> {
    const summary = emptySummary(mint, mode);
    if (mode === "free") {
      readLaunchTool(summary, await client.launchTool(mint, { signal }));
      return summary;
    }
    // Full: the analysis decides; the free scan and the insider search add to it when they answer.
    const [analysis, scan, insiders] = await Promise.allSettled([
      client.analyze(mint, { signal }),
      client.launchTool(mint, { signal }),
      useInsiders ? client.insiders(mint, { signal }) : Promise.resolve(null),
    ]);
    if (analysis.status === "rejected") throw analysis.reason;
    readAnalyze(summary, analysis.value);
    if (scan.status === "fulfilled") readLaunchTool(summary, scan.value);
    else summary.notes.push(`Launch-tool scan skipped: ${describe(scan.reason).message}`);
    if (insiders.status === "fulfilled") readInsiders(summary, insiders.value);
    else summary.notes.push(`Insider search skipped: ${describe(insiders.reason).message}`);
    return summary;
  }

  async function run(mint: string): Promise<GuardResult> {
    const started = Date.now();
    try {
      const summary = await withTimeout((signal) => read(mint, signal), timeoutMs);
      const verdict = evaluate(summary, policy);
      const result: GuardResult = { mint, ...verdict, summary, mode, latencyMs: Date.now() - started, cached: false };
      if (cacheTtlMs > 0) cache.set(mint, { expires: Date.now() + cacheTtlMs, result });
      return result;
    } catch (e) {
      const error = describe(e);
      const how = failOpen ? "fail-open" : "fail-closed";
      return {
        mint,
        allow: failOpen,
        reasons: failOpen ? [] : [`Iris check failed (${how}): ${error.message}`],
        warnings: failOpen ? [`Iris check failed (${how}): ${error.message}`] : [],
        summary: null,
        mode,
        latencyMs: Date.now() - started,
        cached: false,
        error,
      };
    }
  }

  async function check(input: string): Promise<GuardResult> {
    const mint = String(input ?? "").trim();
    if (!BASE58.test(mint)) {
      return { mint, allow: false, reasons: ["Not a Solana mint address"], warnings: [], summary: null, mode, latencyMs: 0, cached: false };
    }
    const hit = cache.get(mint);
    if (hit && hit.expires > Date.now()) return { ...hit.result, cached: true, latencyMs: 0 };
    if (hit) cache.delete(mint);
    // Two checks of one mint at once (a sniper seeing it twice) share one call.
    let pending = inflight.get(mint);
    if (!pending) {
      pending = run(mint).finally(() => inflight.delete(mint));
      inflight.set(mint, pending);
    }
    return pending;
  }

  return {
    check,
    async assert(mint) {
      const result = await check(mint);
      if (!result.allow) throw new GuardBlockedError(result);
      return result;
    },
    mode,
    policy: Object.freeze({ ...policy }),
    clearCache: () => cache.clear(),
  };
}

/** Wraps a buy function so it only runs for tokens the guard allows; blocked ones throw `GuardBlockedError`. */
export function withGuard<A extends [string, ...unknown[]], R>(guard: Guard, buy: (...args: A) => Promise<R>) {
  return async (...args: A): Promise<R> => {
    await guard.assert(args[0]);
    return buy(...args);
  };
}
