// The guard through the real SDK, against a local server that answers like the Iris API.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, it } from "node:test";
import { createGuard } from "../src/index.ts";

const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8");
const MINT = "So11111111111111111111111111111111111111112";
const seen: { path: string; auth: string | undefined; body: any }[] = [];
let baseUrl = "";

const server = createServer((req, res) => {
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    const path = req.url ?? "";
    seen.push({ path, auth: req.headers.authorization, body: raw ? JSON.parse(raw) : null });
    const send = (status: number, body: string) => res.writeHead(status, { "content-type": "application/json" }).end(body);
    if (!req.headers.authorization) return send(401, JSON.stringify({ error: "Log in to use Iris, or send an API key", code: "login" }));
    if (path === "/launch-tool") return send(200, fixture("launch-tool-serial"));
    if (path === "/analyze") return send(200, fixture("analyze-rug"));
    if (path === "/insiders") return send(200, fixture("insiders-linked"));
    send(404, JSON.stringify({ error: "Not found" }));
  });
});

before(async () => {
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(() => server.close());

describe("through the SDK over HTTP", () => {
  it("runs the three calls with the key and blocks the rug", async () => {
    seen.length = 0;
    const r = await createGuard({ apiKey: "iris_live_test", baseUrl }).check(MINT);
    assert.equal(r.mode, "full");
    assert.equal(r.allow, false);
    assert.equal(r.reasons.length, 4);
    assert.deepEqual(seen.map((s) => s.path).sort(), ["/analyze", "/insiders", "/launch-tool"]);
    assert.ok(seen.every((s) => s.auth === "Bearer iris_live_test"));
    assert.equal(seen.find((s) => s.path === "/launch-tool")?.body.wallet, MINT);
  });

  it("fails closed on a 401 without a key", async () => {
    const r = await createGuard({ apiKey: "", baseUrl }).check(MINT);
    assert.equal(r.mode, "free");
    assert.equal(r.allow, false);
    assert.equal(r.error?.status, 401);
    assert.equal(r.error?.code, "login");
  });
});
