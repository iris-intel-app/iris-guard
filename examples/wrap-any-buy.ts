// The smallest integration: wrap the buy function you already have.
// A blocked token throws GuardBlockedError instead of buying.
import { createGuard, GuardBlockedError, withGuard } from "iris-guard";

declare function myBuy(mint: string, sol: number): Promise<string>; // yours

const guardedBuy = withGuard(createGuard(), myBuy);

export async function tryBuy(mint: string, sol: number) {
  try {
    return await guardedBuy(mint, sol);
  } catch (e) {
    if (e instanceof GuardBlockedError) return console.log(`skipped ${mint}: ${e.result.reasons.join("; ")}`);
    throw e;
  }
}
