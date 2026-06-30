import type { WASocket } from "@whiskeysockets/baileys";

export type SessionStatus =
  | "pairing"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

export interface ManagedSession {
  sessionId: string;
  orgId: string;
  sock: WASocket;
  status: SessionStatus;
  paired: boolean;
  phoneNumber?: string;
  lastQr?: string;
  lastError?: string;
  reconnectAttempts: number;
}

export interface SessionView {
  session_id: string;
  org_id: string;
  status: SessionStatus;
  paired: boolean;
  phone_number?: string;
  last_error?: string;
}

export interface QrUpdatedPayload {
  sessionId: string;
  orgId: string;
  qrDataUrl: string;
}

export interface ConnectionOpenedPayload {
  sessionId: string;
  orgId: string;
  phoneNumber: string;
}

export interface ConnectionLoggedOutPayload {
  sessionId: string;
  orgId: string;
  reason: string;
}

export interface ConnectionReconnectingPayload {
  sessionId: string;
  orgId: string;
  attempt: number;
  reason?: string;
}

export type CanonicalMessageType =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "document"
  | "sticker"
  | "location"
  | "contacts"
  | "reaction"
  | "unknown";

export interface CanonicalMediaMeta {
  mime_type?: string;
  sha256?: string;
  size_bytes?: number;
  filename?: string;
  caption?: string;
}

export interface CanonicalLocation {
  latitude: number;
  longitude: number;
  name?: string;
  address?: string;
}

export interface CanonicalReaction {
  target_id: string;
  emoji: string;
}

export interface CanonicalInboundMessage {
  type: "message.received";
  session_id: string;
  org_id: string;
  provider_message_id: string;
  from: string;
  chat_jid: string;
  from_me: boolean;
  timestamp: string;
  message_type: CanonicalMessageType;
  text?: string;
  media?: CanonicalMediaMeta;
  location?: CanonicalLocation;
  reaction?: CanonicalReaction;
  raw: object;
}

export type MessageStatusKind = "delivered" | "read" | "failed";

export interface CanonicalMessageStatus {
  type: "message.delivered" | "message.read" | "message.failed";
  session_id: string;
  org_id: string;
  provider_message_id: string;
  chat_jid: string;
  timestamp: string;
}

export interface MessageReceivedBusPayload {
  envelope: CanonicalInboundMessage;
}

export interface MessageStatusBusPayload {
  envelope: CanonicalMessageStatus;
}

export function toSessionView(s: ManagedSession): SessionView {
  return {
    session_id: s.sessionId,
    org_id: s.orgId,
    status: s.status,
    paired: s.paired,
    phone_number: s.phoneNumber,
    last_error: s.lastError,
  };
}
