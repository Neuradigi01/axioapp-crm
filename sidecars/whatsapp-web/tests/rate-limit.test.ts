import { test } from "node:test";
import assert from "node:assert/strict";

process.env.SIDECAR_PORT ??= "4000";
process.env.SIDECAR_HMAC_SECRET ??= "a".repeat(64);
process.env.FASTAPI_BASE_URL ??= "http://localhost:8000";
process.env.FASTAPI_HMAC_SECRET ??= "b".repeat(64);
process.env.NODE_ENV ??= "test";

const { TokenBucket } = await import("../src/sessions/rate-limit.js");

test("rate-limit: first call within capacity succeeds", () => {
  let now = 0;
  const b = new TokenBucket({ capacity: 1, refillIntervalMs: 1200, now: () => now });
  const r = b.acquire("s1");
  assert.equal(r.ok, true);
});

test("rate-limit: second call within window is denied with retry_after", () => {
  let now = 0;
  const b = new TokenBucket({ capacity: 1, refillIntervalMs: 1200, now: () => now });
  assert.equal(b.acquire("s1").ok, true);
  now = 200;
  const r = b.acquire("s1");
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.ok(r.retry_after_ms > 0 && r.retry_after_ms <= 1200);
  }
});

test("rate-limit: bucket refills after interval", () => {
  let now = 0;
  const b = new TokenBucket({ capacity: 1, refillIntervalMs: 1200, now: () => now });
  assert.equal(b.acquire("s1").ok, true);
  now = 1300;
  assert.equal(b.acquire("s1").ok, true);
});

test("rate-limit: per-key isolation", () => {
  let now = 0;
  const b = new TokenBucket({ capacity: 1, refillIntervalMs: 1200, now: () => now });
  assert.equal(b.acquire("s1").ok, true);
  assert.equal(b.acquire("s2").ok, true);
  assert.equal(b.acquire("s1").ok, false);
});
