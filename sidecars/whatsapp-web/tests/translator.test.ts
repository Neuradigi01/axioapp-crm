import { test } from "node:test";
import assert from "node:assert/strict";

process.env.SIDECAR_PORT ??= "4000";
process.env.SIDECAR_HMAC_SECRET ??= "a".repeat(64);
process.env.FASTAPI_BASE_URL ??= "http://localhost:8000";
process.env.FASTAPI_HMAC_SECRET ??= "b".repeat(64);
process.env.NODE_ENV ??= "test";

const { translateInbound, isGroupJid, statusKindFromBaileys } = await import(
  "../src/events/translator.js"
);

const ORG = "11111111-1111-1111-1111-111111111111";
const SESS = "22222222-2222-2222-2222-222222222222";

function envelope(message: object, key: object = {}): unknown {
  return {
    key: {
      id: "MSG_ID_1",
      remoteJid: "919876543210@s.whatsapp.net",
      fromMe: false,
      ...key,
    },
    messageTimestamp: 1782800000,
    message,
  };
}

test("translator: text via conversation", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({ conversation: "hi there" }) as never,
  });
  assert.ok(out);
  assert.equal(out?.message_type, "text");
  assert.equal(out?.text, "hi there");
  assert.equal(out?.from, "919876543210");
  assert.equal(out?.from_me, false);
  assert.equal(out?.chat_jid, "919876543210@s.whatsapp.net");
});

test("translator: extended text", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({ extendedTextMessage: { text: "linked!" } }) as never,
  });
  assert.equal(out?.message_type, "text");
  assert.equal(out?.text, "linked!");
});

test("translator: image with caption + mime + sha256", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({
      imageMessage: {
        mimetype: "image/jpeg",
        fileSha256: new Uint8Array([1, 2, 3, 4]),
        fileLength: 12345,
        caption: "smile",
      },
    }) as never,
  });
  assert.equal(out?.message_type, "image");
  assert.equal(out?.text, "smile");
  assert.equal(out?.media?.mime_type, "image/jpeg");
  assert.equal(out?.media?.sha256, "01020304");
  assert.equal(out?.media?.size_bytes, 12345);
});

test("translator: video / audio / document / sticker", () => {
  for (const [field, expected] of [
    ["videoMessage", "video"],
    ["audioMessage", "audio"],
    ["documentMessage", "document"],
    ["stickerMessage", "sticker"],
  ] as const) {
    const out = translateInbound({
      orgId: ORG,
      sessionId: SESS,
      waMessage: envelope({ [field]: { mimetype: "application/octet-stream" } }) as never,
    });
    assert.equal(out?.message_type, expected, `field=${field}`);
  }
});

test("translator: location", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({
      locationMessage: {
        degreesLatitude: 12.34,
        degreesLongitude: 56.78,
        name: "Spot",
      },
    }) as never,
  });
  assert.equal(out?.message_type, "location");
  assert.equal(out?.location?.latitude, 12.34);
  assert.equal(out?.location?.longitude, 56.78);
  assert.equal(out?.location?.name, "Spot");
});

test("translator: reaction", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({
      reactionMessage: { key: { id: "TARGET_1" }, text: "👍" },
    }) as never,
  });
  assert.equal(out?.message_type, "reaction");
  assert.equal(out?.reaction?.target_id, "TARGET_1");
  assert.equal(out?.reaction?.emoji, "👍");
});

test("translator: contacts", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({
      contactsArrayMessage: { contacts: [{ displayName: "Bob" }] },
    }) as never,
  });
  assert.equal(out?.message_type, "contacts");
});

test("translator: group jid returns null", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({ conversation: "hi" }, {
      remoteJid: "123456@g.us",
    }) as never,
  });
  assert.equal(out, null);
});

test("translator: from_me flips when key.fromMe = true", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({ conversation: "self note" }, { fromMe: true }) as never,
  });
  assert.equal(out?.from_me, true);
});

test("translator: unknown message shape -> message_type 'unknown'", () => {
  const out = translateInbound({
    orgId: ORG,
    sessionId: SESS,
    waMessage: envelope({ buttonsMessage: { headerType: 1 } }) as never,
  });
  assert.equal(out?.message_type, "unknown");
});

test("isGroupJid", () => {
  assert.equal(isGroupJid("123@g.us"), true);
  assert.equal(isGroupJid("919876543210@s.whatsapp.net"), false);
  assert.equal(isGroupJid(undefined), false);
});

test("statusKindFromBaileys maps numeric codes", () => {
  assert.equal(statusKindFromBaileys(4), "delivered");
  assert.equal(statusKindFromBaileys(5), "read");
  assert.equal(statusKindFromBaileys(1), "failed");
  assert.equal(statusKindFromBaileys(3), null);
  assert.equal(statusKindFromBaileys(undefined), null);
});
