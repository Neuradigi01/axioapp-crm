import type { WAMessage } from "@whiskeysockets/baileys";
import type {
  CanonicalInboundMessage,
  CanonicalLocation,
  CanonicalMediaMeta,
  CanonicalMessageType,
  CanonicalReaction,
} from "../sessions/types.js";

function jidToPhone(jid: string | null | undefined): string {
  if (!jid) return "";
  const head = jid.split("@")[0] ?? "";
  const noDevice = head.split(":")[0] ?? "";
  return noDevice.replace(/[^0-9]/g, "");
}

function uint8ToHex(b: unknown): string | undefined {
  if (!b) return undefined;
  if (b instanceof Uint8Array) return Buffer.from(b).toString("hex");
  if (Buffer.isBuffer(b)) return b.toString("hex");
  return undefined;
}

function asNumber(n: unknown): number | undefined {
  if (typeof n === "number") return n;
  if (typeof n === "bigint") return Number(n);
  if (n && typeof (n as { toNumber?: () => number }).toNumber === "function") {
    return (n as { toNumber: () => number }).toNumber();
  }
  return undefined;
}

function timestampToIso(ts: unknown): string {
  const n = asNumber(ts);
  if (!n || !Number.isFinite(n)) return new Date().toISOString();
  return new Date(n * 1000).toISOString();
}

interface MediaLikeMessage {
  mimetype?: string | null;
  fileSha256?: Uint8Array | Buffer | null;
  fileLength?: number | bigint | null | { toNumber: () => number };
  fileName?: string | null;
  caption?: string | null;
}

function mediaMeta(m: MediaLikeMessage | null | undefined): CanonicalMediaMeta | undefined {
  if (!m) return undefined;
  const meta: CanonicalMediaMeta = {};
  if (m.mimetype) meta.mime_type = m.mimetype;
  const sha = uint8ToHex(m.fileSha256);
  if (sha) meta.sha256 = sha;
  const size = asNumber(m.fileLength);
  if (size != null) meta.size_bytes = size;
  if (m.fileName) meta.filename = m.fileName;
  if (m.caption) meta.caption = m.caption;
  return Object.keys(meta).length === 0 ? undefined : meta;
}

interface ClassifiedMessage {
  message_type: CanonicalMessageType;
  text?: string;
  media?: CanonicalMediaMeta;
  location?: CanonicalLocation;
  reaction?: CanonicalReaction;
}

function classify(message: Record<string, unknown> | null | undefined): ClassifiedMessage {
  if (!message) return { message_type: "unknown" };

  const conversation = message.conversation;
  if (typeof conversation === "string" && conversation.length > 0) {
    return { message_type: "text", text: conversation };
  }

  const ext = message.extendedTextMessage as { text?: string | null } | undefined;
  if (ext?.text) {
    return { message_type: "text", text: ext.text };
  }

  const image = message.imageMessage as MediaLikeMessage | undefined;
  if (image) {
    return {
      message_type: "image",
      media: mediaMeta(image),
      text: image.caption ?? undefined,
    };
  }

  const video = message.videoMessage as MediaLikeMessage | undefined;
  if (video) {
    return {
      message_type: "video",
      media: mediaMeta(video),
      text: video.caption ?? undefined,
    };
  }

  const audio = message.audioMessage as MediaLikeMessage | undefined;
  if (audio) {
    return { message_type: "audio", media: mediaMeta(audio) };
  }

  const document = message.documentMessage as MediaLikeMessage | undefined;
  if (document) {
    return {
      message_type: "document",
      media: mediaMeta(document),
      text: document.caption ?? undefined,
    };
  }

  const sticker = message.stickerMessage as MediaLikeMessage | undefined;
  if (sticker) {
    return { message_type: "sticker", media: mediaMeta(sticker) };
  }

  const location = message.locationMessage as
    | {
        degreesLatitude?: number;
        degreesLongitude?: number;
        name?: string;
        address?: string;
      }
    | undefined;
  if (location && typeof location.degreesLatitude === "number") {
    return {
      message_type: "location",
      location: {
        latitude: location.degreesLatitude,
        longitude: location.degreesLongitude ?? 0,
        name: location.name,
        address: location.address,
      },
    };
  }

  const contacts = message.contactsArrayMessage as { contacts?: unknown[] } | undefined;
  if (contacts?.contacts) {
    return { message_type: "contacts" };
  }

  const reaction = message.reactionMessage as
    | { key?: { id?: string }; text?: string }
    | undefined;
  if (reaction?.key?.id) {
    return {
      message_type: "reaction",
      reaction: { target_id: reaction.key.id, emoji: reaction.text ?? "" },
    };
  }

  return { message_type: "unknown" };
}

export function isGroupJid(jid: string | null | undefined): boolean {
  return !!jid && jid.endsWith("@g.us");
}

export function translateInbound(args: {
  orgId: string;
  sessionId: string;
  waMessage: WAMessage;
}): CanonicalInboundMessage | null {
  const { orgId, sessionId, waMessage } = args;
  const key = waMessage.key ?? {};
  const remoteJid = key.remoteJid ?? null;
  if (!remoteJid) return null;

  if (isGroupJid(remoteJid)) return null;

  const providerId = key.id ?? "";
  const fromMe = !!key.fromMe;
  const fromJid = fromMe ? remoteJid : key.participant ?? remoteJid;
  const classified = classify(waMessage.message as Record<string, unknown> | null);

  return {
    type: "message.received",
    session_id: sessionId,
    org_id: orgId,
    provider_message_id: providerId,
    from: jidToPhone(fromJid),
    chat_jid: remoteJid,
    from_me: fromMe,
    timestamp: timestampToIso(waMessage.messageTimestamp),
    message_type: classified.message_type,
    text: classified.text,
    media: classified.media,
    location: classified.location,
    reaction: classified.reaction,
    raw: (waMessage.message ?? {}) as object,
  };
}

export function statusKindFromBaileys(code: number | null | undefined):
  | "delivered"
  | "read"
  | "failed"
  | null {
  switch (code) {
    case 1:
      return "failed";
    case 4:
      return "delivered";
    case 5:
      return "read";
    default:
      return null;
  }
}
