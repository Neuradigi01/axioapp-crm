import { test } from "node:test";
import assert from "node:assert/strict";

process.env.SIDECAR_PORT ??= "4000";
process.env.SIDECAR_HMAC_SECRET ??= "a".repeat(64);
process.env.FASTAPI_BASE_URL ??= "http://localhost:8000";
process.env.FASTAPI_HMAC_SECRET ??= "b".repeat(64);
process.env.NODE_ENV ??= "test";

const { sign, verify } = await import("../src/auth.js");

const SECRET = process.env.SIDECAR_HMAC_SECRET!;

test("sign + verify round-trip succeeds", () => {
  const body = JSON.stringify({ foo: "bar" });
  const sig = sign(body, SECRET);
  assert.equal(verify(body, sig, SECRET), true);
});

test("tampered signature is rejected", () => {
  const body = JSON.stringify({ foo: "bar" });
  const sig = sign(body, SECRET);
  const tampered = sig.slice(0, -1) + (sig.endsWith("0") ? "1" : "0");
  assert.equal(verify(body, tampered, SECRET), false);
});

test("wrong prefix is rejected", () => {
  const body = JSON.stringify({ foo: "bar" });
  const sig = sign(body, SECRET).replace("sha256=", "sha1=");
  assert.equal(verify(body, sig, SECRET), false);
});

test("missing / empty header is rejected", () => {
  const body = JSON.stringify({ foo: "bar" });
  assert.equal(verify(body, undefined, SECRET), false);
  assert.equal(verify(body, "", SECRET), false);
});

test("signature from wrong secret is rejected", () => {
  const body = JSON.stringify({ foo: "bar" });
  const sig = sign(body, "z".repeat(64));
  assert.equal(verify(body, sig, SECRET), false);
});

test("different body with same signature is rejected", () => {
  const sig = sign(JSON.stringify({ foo: "bar" }), SECRET);
  assert.equal(verify(JSON.stringify({ foo: "baz" }), sig, SECRET), false);
});
