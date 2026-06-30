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
