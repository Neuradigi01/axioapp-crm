import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs/promises";
import os from "node:os";

process.env.SIDECAR_PORT ??= "4000";
process.env.SIDECAR_HMAC_SECRET ??= "a".repeat(64);
process.env.FASTAPI_BASE_URL ??= "http://localhost:8000";
process.env.FASTAPI_HMAC_SECRET ??= "b".repeat(64);
process.env.NODE_ENV ??= "test";

const tmpStorage = await fs.mkdtemp(path.join(os.tmpdir(), "sidecar-test-"));
process.env.STORAGE_DIR = tmpStorage;

const { filesystemStorage, InvalidIdError, isValidUuid } = await import(
  "../src/sessions/auth-store.js"
);
const { SessionManager } = await import("../src/sessions/manager.js");
const { bus } = await import("../src/events/bus.js");
const { makeMockFactory } = await import("./_baileys-mock.js");

const ORG = "11111111-1111-1111-1111-111111111111";
const SESS = "22222222-2222-2222-2222-222222222222";

test("auth-store: UUID validator accepts canonical UUID, rejects junk", () => {
  assert.equal(isValidUuid(ORG), true);
  assert.equal(isValidUuid("../etc/passwd"), false);
  assert.equal(isValidUuid("not a uuid"), false);
  assert.equal(isValidUuid(""), false);
  assert.equal(isValidUuid("11111111111111111111111111111111"), false);
});

test("auth-store: resolvePath rejects path traversal", () => {
  assert.throws(
    () => filesystemStorage.resolvePath("../etc", SESS),
    (err: unknown) => err instanceof InvalidIdError,
  );
  assert.throws(
    () => filesystemStorage.resolvePath(ORG, "../escape"),
    (err: unknown) => err instanceof InvalidIdError,
  );
});

test("auth-store: load creates folder; destroy removes it", async () => {
  const dir = filesystemStorage.resolvePath(ORG, SESS);
  await filesystemStorage.load(ORG, SESS);
  const stat = await fs.stat(dir);
  assert.equal(stat.isDirectory(), true);
  await filesystemStorage.destroy(ORG, SESS);
  await assert.rejects(fs.stat(dir), /ENOENT/);
});

test("manager: create + get + duplicate-call is idempotent", async () => {
  const hooks = { socketsCreated: [], configsSeen: [] };
  const m = new SessionManager({ makeSocket: makeMockFactory(hooks), restoreStaggerMs: 0 });
  const s1 = await m.create({ orgId: ORG, sessionId: SESS });
  const s2 = await m.create({ orgId: ORG, sessionId: SESS });
  assert.equal(s1, s2);
  assert.equal(hooks.socketsCreated.length, 1);
  assert.equal(m.get(SESS), s1);
  await m.destroy(SESS);
});

test("manager: qr event flows to bus", async () => {
  const hooks = { socketsCreated: [], configsSeen: [] };
  const m = new SessionManager({ makeSocket: makeMockFactory(hooks), restoreStaggerMs: 0 });
  const session = await m.create({ orgId: ORG, sessionId: SESS });
  const sock = hooks.socketsCreated[0]!;

  const seen = new Promise<{ sessionId: string; qrDataUrl: string }>((resolve) => {
    bus.once("qr.updated", (p) => resolve(p as { sessionId: string; qrDataUrl: string }));
  });

  sock.__emit("connection.update", { qr: "2@abcd1234,fake-qr-payload" });

  const payload = await seen;
  assert.equal(payload.sessionId, SESS);
  assert.ok(payload.qrDataUrl.startsWith("data:image/png;base64,"));
  assert.equal(session.status, "pairing");
  assert.ok(session.lastQr?.startsWith("data:image/png;base64,"));
  await m.destroy(SESS);
});

test("manager: connection.open marks paired and extracts phone", async () => {
  const hooks = { socketsCreated: [], configsSeen: [] };
  const m = new SessionManager({ makeSocket: makeMockFactory(hooks), restoreStaggerMs: 0 });
  const session = await m.create({ orgId: ORG, sessionId: SESS });
  const sock = hooks.socketsCreated[0]!;

  sock.user = { id: "919876543210:1@s.whatsapp.net" };
  const opened = new Promise<{ phoneNumber: string }>((resolve) => {
    bus.once("connection.opened", (p) => resolve(p as { phoneNumber: string }));
  });
  sock.__emit("connection.update", { connection: "open" });
  const payload = await opened;

  assert.equal(payload.phoneNumber, "919876543210");
  assert.equal(session.status, "connected");
  assert.equal(session.paired, true);
  assert.equal(session.phoneNumber, "919876543210");
  await m.destroy(SESS);
});

test("manager: restoreAll walks storage and re-creates every found session", async () => {
  const dirA = filesystemStorage.resolvePath(ORG, SESS);
  await fs.mkdir(dirA, { recursive: true });
  const dirB = filesystemStorage.resolvePath(
    ORG,
    "33333333-3333-3333-3333-333333333333",
  );
  await fs.mkdir(dirB, { recursive: true });

  const hooks = { socketsCreated: [], configsSeen: [] };
  const m = new SessionManager({ makeSocket: makeMockFactory(hooks), restoreStaggerMs: 0 });
  const result = await m.restoreAll();

  assert.equal(result.restored, 2);
  assert.equal(hooks.socketsCreated.length, 2);
  assert.ok(m.get(SESS));
  assert.ok(m.get("33333333-3333-3333-3333-333333333333"));

  await m.destroy(SESS);
  await m.destroy("33333333-3333-3333-3333-333333333333");
});
