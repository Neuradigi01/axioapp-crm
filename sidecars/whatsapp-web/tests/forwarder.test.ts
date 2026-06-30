import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { AddressInfo } from "node:net";
import axios from "axios";

process.env.SIDECAR_PORT ??= "4000";
process.env.SIDECAR_HMAC_SECRET ??= "a".repeat(64);
process.env.FASTAPI_BASE_URL ??= "http://localhost:8000";
process.env.FASTAPI_HMAC_SECRET ??= "b".repeat(64);
process.env.NODE_ENV ??= "test";

const { EventForwarder } = await import("../src/events/forwarder.js");
const { RetryQueue } = await import("../src/events/retry-queue.js");
const { bus, emitMessageReceived } = await import("../src/events/bus.js");

interface ReceivedRequest {
  url: string;
  signature: string | undefined;
  body: string;
}

interface MockServer {
  port: number;
  received: ReceivedRequest[];
  failNext: (count: number, status: number) => void;
  failNetwork: (count: number) => void;
  close: () => Promise<void>;
}

async function startMockServer(): Promise<MockServer> {
  const received: ReceivedRequest[] = [];
  let pendingFailures = 0;
  let failStatus = 500;
  let pendingNetworkFails = 0;

  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c.toString("utf8")));
    req.on("end", () => {
      if (pendingNetworkFails > 0) {
        pendingNetworkFails -= 1;
        req.socket.destroy();
        return;
      }
      received.push({
        url: req.url ?? "",
        signature: req.headers["x-fastapi-signature"] as string | undefined,
        body,
      });
      if (pendingFailures > 0) {
        pendingFailures -= 1;
        res.statusCode = failStatus;
        res.end();
        return;
      }
      res.statusCode = 200;
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    port,
    received,
    failNext: (count, status) => {
      pendingFailures = count;
      failStatus = status;
    },
    failNetwork: (count) => {
      pendingNetworkFails = count;
    },
    close: () => new Promise((r) => server.close(() => r())),
  };
}

function makeEnvelope(id = "MSG_1") {
  return {
    type: "message.received" as const,
    session_id: "11111111-1111-1111-1111-111111111111",
    org_id: "22222222-2222-2222-2222-222222222222",
    provider_message_id: id,
    from: "919876543210",
    chat_jid: "919876543210@s.whatsapp.net",
    from_me: false,
    timestamp: new Date().toISOString(),
    message_type: "text" as const,
    text: "hello",
    raw: { conversation: "hello" },
  };
}

function syncTimer(): (cb: () => void, ms: number) => { ref: () => void; unref: () => void } {
  return (cb) => {
    setImmediate(cb);
    return { ref: () => undefined, unref: () => undefined };
  };
}

async function waitFor(predicate: () => boolean, ms = 1500): Promise<void> {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > ms) throw new Error("waitFor: timeout");
    await new Promise((r) => setImmediate(r));
  }
}

test("forwarder: happy path posts envelope with HMAC header", async () => {
  bus.removeAllListeners("message.received");
  const server = await startMockServer();
  const client = axios.create({ baseURL: `http://localhost:${server.port}` });
  const fwd = new EventForwarder({ client });
  fwd.start();

  emitMessageReceived({ envelope: makeEnvelope() });
  await waitFor(() => server.received.length >= 1);

  assert.equal(server.received.length, 1);
  assert.equal(server.received[0]!.url, "/api/v1/integrations/whatsapp-web/events");
  assert.ok(server.received[0]!.signature?.startsWith("sha256="));
  const parsed = JSON.parse(server.received[0]!.body);
  assert.equal(parsed.type, "message.received");
  assert.equal(parsed.provider_message_id, "MSG_1");

  fwd.stop();
  await server.close();
});

test("forwarder: 500 then 200 -> retry queue delivers", async () => {
  bus.removeAllListeners("message.received");
  const server = await startMockServer();
  server.failNext(1, 500);
  const client = axios.create({ baseURL: `http://localhost:${server.port}` });
  const retry = new RetryQueue({ backoffMs: [10], setTimer: syncTimer(), label: "test" });
  const fwd = new EventForwarder({ client, retry });
  fwd.start();

  emitMessageReceived({ envelope: makeEnvelope("MSG_2") });
  await waitFor(() => server.received.filter((r) => r.body.includes("MSG_2")).length >= 2);

  fwd.stop();
  await server.close();
});

test("forwarder: drops after backoff exhausts", async () => {
  bus.removeAllListeners("message.received");
  const server = await startMockServer();
  server.failNext(10, 502);
  const client = axios.create({ baseURL: `http://localhost:${server.port}` });
  const retry = new RetryQueue({ backoffMs: [5, 5, 5], setTimer: syncTimer(), label: "test" });
  const fwd = new EventForwarder({ client, retry });
  fwd.start();

  emitMessageReceived({ envelope: makeEnvelope("MSG_3") });
  await waitFor(() => server.received.filter((r) => r.body.includes("MSG_3")).length >= 4, 2000);

  fwd.stop();
  await server.close();
});

test("forwarder: network error first, then 200 on retry", async () => {
  bus.removeAllListeners("message.received");
  const server = await startMockServer();
  server.failNetwork(1);
  const client = axios.create({
    baseURL: `http://localhost:${server.port}`,
    timeout: 500,
  });
  const retry = new RetryQueue({ backoffMs: [10], setTimer: syncTimer(), label: "test" });
  const fwd = new EventForwarder({ client, retry });
  fwd.start();

  emitMessageReceived({ envelope: makeEnvelope("MSG_4") });
  await waitFor(() => server.received.some((r) => r.body.includes("MSG_4")), 3000);

  fwd.stop();
  await server.close();
});
