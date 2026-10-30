# iris-guard

**Stop buying bundled tokens. One line before every buy.**

`iris-guard` is a pre-trade rug filter for Solana trading bots. Before your bot buys a token, it asks
[Iris](https://iriscan.app) who launched it and who holds it, and refuses the ones built to dump on you:
bundled launches whose bundle still holds the supply, devs who still hold a bag or already dumped,
tokens launched with Proxima or BlockX, and anything Iris scores as high risk.

<!-- GIF placeholder: record a terminal running the pump.fun sniper example, BLOCK lines scrolling
     past with their reasons, then one ALLOW and a buy. ~10 s, 800 px wide, saved as docs/demo.gif. -->

```ts
import { createGuard } from "iris-guard";

const guard = createGuard({ apiKey: process.env.IRIS_API_KEY });

async function onNewToken(mint: string) {
  const { allow, reasons } = await guard.check(mint);
  if (!allow) return console.log("skip", mint, reasons);
  await buy(mint); // your existing buy
}
```

```
BLOCK <mint> (full mode, 2140 ms)
  - Bundle still holds 34.2% of the supply (max 10%)
  - Dev dumped 42 s after launch (limit 5 min)
  - Iris risk score 82/100 (max 70)
```

TypeScript and Python, same policy, same results. MIT licensed.

## Install

```bash
npm install iris-guard        # Node 18+
pip install iris-guard        # Python 3.9+
```

## Python

```python
from iris_guard import create_guard

guard = create_guard()  # reads IRIS_API_KEY from the environment

def on_new_token(mint: str):
    verdict = guard.check(mint)
    if not verdict.allow:
        return print("skip", mint, verdict.reasons)
    buy(mint)  # your existing buy
```

Async bots: `create_async_guard()` and `await guard.check(mint)`.

## What it blocks

The default policy. Every value can be overridden (`policy: { ... }` in TypeScript, keyword
arguments in Python), and `null` / `None` turns a rule off.

| Rule | Default | Option (TS / Python) | Why |
| --- | --- | --- | --- |
| Bundle still holds the supply | 10% or more | `maxBundleHeldPct` / `max_bundle_held_pct` | A bundle sitting on a tenth of the supply can dump it on the first buyers. |
| Dev still holds the supply | 10% or more | `maxDevHeldPct` / `max_dev_held_pct` | A pump.fun dev's own launch buy is usually a few percent. Ten or more is a loaded gun. |
| Dev dumped right after launch | within 300 s | `devDumpWithinSeconds` / `dev_dump_within_seconds` | A dev who is done selling within minutes ran a pump and dump. |
| Linked wallets hold the supply | 20% or more | `maxInsiderHeldPct` / `max_insider_held_pct` | Wallets the dev funded, or was funded with, are the dev. |
| Iris risk score | 70 or more | `maxRiskScore` / `max_risk_score` | 70 is where Iris itself calls a token HIGH risk. |
| Launch tool (Proxima, BlockX) | blocked | `blockLaunchTools` / `block_launch_tools` | These kits launch, bundle and dump tokens from fleets of fresh wallets. |
| Launch tool, moderate evidence | blocked | `blockLikelyLaunchTools` / `block_likely_launch_tools` | Set to false to only block confirmed fingerprints. |
| Serial launcher | warning only | `maxCreatorLaunches` / `max_creator_launches` | Many honest devs launch more than once. Set a number to block token factories. |
| Your own rule | none | `custom` | `(summary) => reason or null`. |

Unknown facts never block and never pass on their own: if Iris could not read the dev's holdings,
that rule is skipped, not counted as safe.

Other options:

| Option | Default | |
| --- | --- | --- |
| `failOpen` / `fail_open` | `false` | When Iris errors or times out: `false` blocks the buy (fail-closed), `true` lets it through. |
| `timeoutMs` / `timeout` | 20000 ms / 20 s | Deadline for the whole check. Snipers usually want 5 to 8 s. |
| `cacheTtlMs` / `cache_ttl` | 60000 ms / 60 s | A mint checked again within this window is answered from memory. Failures are never cached. |
| `mode` | `"full"` with a key, else `"free"` | See below. |
| `insiders` | `true` | Full mode: also run the insider search (2 credits). |

Concurrent checks of the same mint share one call, so a sniper that sees a mint twice pays once.

## Free mode and full mode

| | Free mode | Full mode |
| --- | --- | --- |
| Calls | `/launch-tool` (free) | `/analyze` + `/insiders` + `/launch-tool` |
| Cost | no credits | 3 credits a check (analysis 1, insider search 2), or 1 with `insiders: false` |
| Launch tools (Proxima, BlockX) | yes | yes |
| Creator's serial launches | yes | yes |
| Bundle and what it still holds | no | yes |
| Dev holdings and dump timing | no | yes |
| Wallets linked to the dev | no | yes |
| Iris risk score | no | yes |

**Free mode** reads the token's creator with Iris's free launch-tool scan: whether Proxima or BlockX
made it, and how many tokens the creator launched before. It spends no credits. It is rate limited
(10 scans a minute, and a daily cap without a paid plan), so it suits trying iris-guard and
low-volume bots. Today the API asks for an account even on this free route: a free account
(email or Solana wallet, no card) gives you a key and 10 API calls a day.

**Full mode** adds the token analysis and the insider search: the bundle, the dev's holdings and
sells, the wallets linked to the dev by money, and the Iris risk score. That is where most rugs show.
It needs an API key with credits.

Plans, credits and keys: **https://iriscan.app/pricing**

```bash
export IRIS_API_KEY=iris_live_...
```

## Examples

Drop-in snippets in [`examples/`](examples):

- [`jupiter-before-buy.ts`](examples/jupiter-before-buy.ts): the guard in front of a Jupiter quote and swap.
- [`pumpfun-sniper.ts`](examples/pumpfun-sniper.ts): new pump.fun mints from a websocket feed, a guard check, then your buy.
- [`wrap-any-buy.ts`](examples/wrap-any-buy.ts): wrap the buy function you already have with `withGuard`.
- [`check-list.sh`](examples/check-list.sh): filter a list of mints with the CLI.
- [`python/jupiter_before_buy.py`](examples/python/jupiter_before_buy.py) and [`python/pumpfun_sniper.py`](examples/python/pumpfun_sniper.py): the same in Python.

Wrap a buy function so it can only buy allowed tokens:

```ts
import { createGuard, withGuard } from "iris-guard";

const safeBuy = withGuard(createGuard(), buy); // throws GuardBlockedError on a block
```

## CLI

```bash
npx iris-guard <mint>
python -m iris_guard <mint>
```

Prints `ALLOW` or `BLOCK` with the reasons, and exits `0` (allow) or `1` (block), so it drops into
any script:

```bash
npx iris-guard "$MINT" && ./buy.sh "$MINT"
```

Options: `--free`, `--full`, `--no-insiders`, `--fail-open`, `--timeout`, `--max-bundle`,
`--max-dev`, `--dump-within`, `--max-risk`, `--max-launches`, `--json`. Exit code `2` means bad usage.

## The result

```ts
{
  mint: string,
  allow: boolean,
  reasons: string[],      // why it was blocked
  warnings: string[],     // facts that did not block it (bundled but sold out, serial launcher...)
  summary: {              // what Iris found; null fields mean "could not tell"
    creator, creatorLaunches, launchTool, launchToolVerdict,
    bundled, bundleHeldPct, devHeldPct, devSold, devDumpSeconds,
    insiderHeldPct, riskScore, notes
  },
  mode: "free" | "full",
  latencyMs: number,
  cached: boolean,
  error?: { message, status?, code? }   // set when Iris failed; allow then follows failOpen
}
```

Python returns the same fields in snake_case (`latency_ms`, `bundle_held_pct`...), with `to_dict()`.

## Development

```bash
npm install && npm test            # unit tests, mocked SDK and a local HTTP server
IRIS_LIVE=1 npm run test:live      # live smoke test on /launch-tool, no key

cd python
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

iris-guard is built on the official Iris SDKs: [`@iriscan/sdk`](https://www.npmjs.com/package/@iriscan/sdk)
and [`iriscan`](https://pypi.org/project/iriscan/).

## Disclaimer

iris-guard lowers the odds of buying a rug. It does not remove them, and it is not financial advice.
A token that passes can still go to zero.

## License

MIT, Iris (iriscan.app).
