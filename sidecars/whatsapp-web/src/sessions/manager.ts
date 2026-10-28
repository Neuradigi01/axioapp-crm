import makeWASocket, {
  DisconnectReason,
  type WAMessage,
  type WASocket,
} from "@whiskeysockets/baileys";
import { pino } from "pino";
import QRCode from "qrcode";
import { logger } from "../logger.js";
import {
  bus,
  emitConnectionLoggedOut,
  emitConnectionOpened,
  emitConnectionReconnecting,
  emitMessageReceived,
  emitMessageStatus,
  emitQrUpdated,
} from "../events/bus.js";
import {
  isGroupJid,
  statusKindFromBaileys,
  translateInbound,
} from "../events/translator.js";
import { filesystemStorage, isValidUuid, type SessionStorage } from "./auth-store.js";
import type { ManagedSession, SessionStatus } from "./types.js";

type MakeSocket = typeof makeWASocket;

interface ManagerDeps {
  storage?: SessionStorage;
  makeSocket?: MakeSocket;
  reconnectBackoffMs?: (attempt: number) => number;
  restoreStaggerMs?: number;
  mediaCacheSize?: number;
}

const DEFAULT_MEDIA_CACHE = 500;

const DEFAULT_BACKOFF: (n: number) => number = (n) =>
  Math.min(60_000, [5_000, 15_000, 60_000][Math.min(n, 2)] ?? 60_000);

const BAILEYS_SILENT_LOGGER = pino({ level: "silent" });

function stripPhoneSuffix(jid: string | undefined): string | undefined {
  if (!jid) return undefined;
  const at = jid.indexOf("@");
  const head = at === -1 ? jid : jid.slice(0, at);
  const colon = head.indexOf(":");
  return colon === -1 ? head : head.slice(0, colon);
}

interface BoomLike {
  output?: { statusCode?: number };
}

function labelForDisconnect(code: number | undefined): string {
  if (code == null) return "unknown";
  switch (code) {
    case DisconnectReason.loggedOut:
      return "loggedOut";
    case DisconnectReason.connectionClosed:
      return "connectionClosed";
    case DisconnectReason.connectionReplaced:
      return "connectionReplaced";
    case DisconnectReason.connectionLost:
      return "connectionLost_or_timedOut";
    case DisconnectReason.badSession:
      return "badSession";
    case DisconnectReason.restartRequired:
      return "restartRequired";
    case DisconnectReason.multideviceMismatch:
      return "multideviceMismatch";
    case DisconnectReason.forbidden:
      return "forbidden";
    case DisconnectReason.unavailableService:
      return "unavailableService";
    default:
      return `code_${code}`;
  }
}

function disconnectReason(err: unknown): { code: number | undefined; label: string } {
  const code = (err as BoomLike | undefined)?.output?.statusCode;
  return { code, label: labelForDisconnect(code) };
}

export class SessionManager {
  private readonly sessions = new Map<string, ManagedSession>();
  private readonly mediaCache = new Map<string, Map<string, WAMessage>>();
  private readonly storage: SessionStorage;
  private readonly makeSocket: MakeSocket;
  private readonly backoff: (attempt: number) => number;
  private readonly restoreStaggerMs: number;
  private readonly mediaCacheSize: number;

  constructor(deps: ManagerDeps = {}) {
    this.storage = deps.storage ?? filesystemStorage;
    this.makeSocket = deps.makeSocket ?? makeWASocket;
    this.backoff = deps.reconnectBackoffMs ?? DEFAULT_BACKOFF;
    this.restoreStaggerMs = deps.restoreStaggerMs ?? 100;
    this.mediaCacheSize = deps.mediaCacheSize ?? DEFAULT_MEDIA_CACHE;
  }

  private rememberMedia(sessionId: string, msg: WAMessage): void {
    const id = msg.key?.id;
    if (!id) return;
    let cache = this.mediaCache.get(sessionId);
    if (!cache) {
      cache = new Map();
      this.mediaCache.set(sessionId, cache);
    }
    if (cache.has(id)) cache.delete(id);
    cache.set(id, msg);
    while (cache.size > this.mediaCacheSize) {
      const oldest = cache.keys().next().value;
      if (!oldest) break;
      cache.delete(oldest);
    }
  }

  findMessage(sessionId: string, messageId: string): WAMessage | undefined {
    return this.mediaCache.get(sessionId)?.get(messageId);
  }

  get(sessionId: string): ManagedSession | null {
    return this.sessions.get(sessionId) ?? null;
  }

  list(): ManagedSession[] {
    return Array.from(this.sessions.values());
  }

  async create(input: { orgId: string; sessionId: string }): Promise<ManagedSession> {
    const { orgId, sessionId } = input;
    if (!isValidUuid(orgId) || !isValidUuid(sessionId)) {
      throw new Error("invalid id");
    }
    const existing = this.sessions.get(sessionId);
    if (existing) return existing;

    const { state, saveCreds } = await this.storage.load(orgId, sessionId);

    const sock = this.makeSocket({
      auth: state,
      browser: ["Core CRM", "Chrome", "1.0"],
      printQRInTerminal: false,
      logger: BAILEYS_SILENT_LOGGER,
      syncFullHistory: false,
      markOnlineOnConnect: false,
    });

    const session: ManagedSession = {
      sessionId,
      orgId,
      sock,
      status: "pairing",
      paired: false,
      reconnectAttempts: 0,
    };
    this.sessions.set(sessionId, session);

    sock.ev.on("creds.update", () => {
      void saveCreds();
    });

    sock.ev.on("connection.update", (update) => {
      void this.handleConnectionUpdate(session, update);
    });

    sock.ev.on("messages.upsert", (payload) => {
      this.handleMessagesUpsert(session, payload as { messages: WAMessage[]; type?: string });
    });

    sock.ev.on("messages.update", (updates) => {
      this.handleMessagesUpdate(session, updates as Array<{
        key: { id?: string | null; remoteJid?: string | null; fromMe?: boolean | null };
        update: { status?: number | null };
      }>);
    });

    logger.info({ sessionId, orgId }, "session.created");
    return session;
  }

  private handleMessagesUpsert(
    session: ManagedSession,
    payload: { messages: WAMessage[]; type?: string },
  ): void {
    for (const msg of payload.messages ?? []) {
      const remoteJid = msg.key?.remoteJid ?? undefined;
      if (isGroupJid(remoteJid)) {
        logger.info({ sessionId: session.sessionId, remoteJid }, "session.skipped_group_message");
        continue;
      }
      if (msg.key?.fromMe) continue;
      this.rememberMedia(session.sessionId, msg);
      const envelope = translateInbound({
        orgId: session.orgId,
        sessionId: session.sessionId,
        waMessage: msg,
      });
      if (envelope) {
        emitMessageReceived({ envelope });
      }
    }
  }

  private handleMessagesUpdate(
    session: ManagedSession,
    updates: Array<{
      key: { id?: string | null; remoteJid?: string | null; fromMe?: boolean | null };
      update: { status?: number | null };
    }>,
  ): void {
    for (const u of updates) {
      const kind = statusKindFromBaileys(u.update.status ?? null);
      if (!kind) continue;
      const id = u.key.id;
      const chatJid = u.key.remoteJid;
      if (!id || !chatJid) continue;
      if (isGroupJid(chatJid)) continue;
      const type =
        kind === "delivered"
          ? "message.delivered"
          : kind === "read"
            ? "message.read"
            : "message.failed";
      emitMessageStatus({
        envelope: {
          type,
          session_id: session.sessionId,
          org_id: session.orgId,
          provider_message_id: id,
          chat_jid: chatJid,
          timestamp: new Date().toISOString(),
        },
      });
    }
  }

  private async handleConnectionUpdate(
    session: ManagedSession,
    update: Parameters<Parameters<WASocket["ev"]["on"]>[1]>[0] extends infer U ? U : never,
  ): Promise<void> {
    const u = update as {
      connection?: "open" | "close" | "connecting";
      lastDisconnect?: { error?: Error };
      qr?: string;
    };

    if (u.qr) {
      try {
        const dataUrl = await QRCode.toDataURL(u.qr, { margin: 1, scale: 6 });
        session.lastQr = dataUrl;
        session.status = "pairing";
        emitQrUpdated({ sessionId: session.sessionId, orgId: session.orgId, qrDataUrl: dataUrl });
        logger.info({ sessionId: session.sessionId }, "session.qr_ready");
      } catch (err) {
        session.lastError = (err as Error).message;
        logger.error({ err, sessionId: session.sessionId }, "session.qr_render_failed");
      }
    }

    if (u.connection === "connecting") {
      session.status = "pairing";
    }

    if (u.connection === "open") {
      session.status = "connected";
      session.paired = true;
      session.lastQr = undefined;
      session.reconnectAttempts = 0;
      session.phoneNumber = stripPhoneSuffix(session.sock.user?.id);
      session.lastError = undefined;
      emitConnectionOpened({
        sessionId: session.sessionId,
        orgId: session.orgId,
        phoneNumber: session.phoneNumber ?? "",
      });
      logger.info(
        { sessionId: session.sessionId, phone: session.phoneNumber },
        "session.connected",
      );
    }

    if (u.connection === "close") {
      const { code, label } = disconnectReason(u.lastDisconnect?.error);
      session.lastError = label;

      if (code === DisconnectReason.loggedOut) {
        session.status = "disconnected";
        session.paired = false;
        session.lastQr = undefined;
        await this.storage.destroy(session.orgId, session.sessionId).catch((err) => {
          logger.warn({ err, sessionId: session.sessionId }, "session.destroy_creds_failed");
        });
        emitConnectionLoggedOut({
          sessionId: session.sessionId,
          orgId: session.orgId,
          reason: label,
        });
        logger.info({ sessionId: session.sessionId }, "session.logged_out");
        this.sessions.delete(session.sessionId);
        this.mediaCache.delete(session.sessionId);
        return;
      }

      session.status = "reconnecting";
      session.reconnectAttempts += 1;
      const delayMs = this.backoff(session.reconnectAttempts - 1);
      emitConnectionReconnecting({
        sessionId: session.sessionId,
        orgId: session.orgId,
        attempt: session.reconnectAttempts,
        reason: label,
      });
      logger.warn(
        { sessionId: session.sessionId, reason: label, attempt: session.reconnectAttempts, delayMs },
        "session.reconnect_scheduled",
      );
      setTimeout(() => {
        if (!this.sessions.has(session.sessionId)) return;
        this.sessions.delete(session.sessionId);
        this.create({ orgId: session.orgId, sessionId: session.sessionId }).catch((err) => {
          logger.error({ err, sessionId: session.sessionId }, "session.reconnect_failed");
        });
      }, delayMs).unref();
    }
  }

  async destroy(sessionId: string): Promise<boolean> {
    const session = this.sessions.get(sessionId);
    if (!session) return false;
    try {
      if (session.paired) {
        await session.sock.logout().catch(() => undefined);
      } else {
        session.sock.end(undefined);
      }
    } catch (err) {
      logger.warn({ err, sessionId }, "session.close_failed");
    }
    this.sessions.delete(sessionId);
    this.mediaCache.delete(sessionId);
    await this.storage.destroy(session.orgId, sessionId).catch((err) => {
      logger.warn({ err, sessionId }, "session.destroy_creds_failed");
    });
    logger.info({ sessionId }, "session.destroyed");
    return true;
  }

  async restoreAll(): Promise<{ restored: number }> {
    const found = await this.storage.list();
    let restored = 0;
    for (const { orgId, sessionId } of found) {
      try {
        await this.create({ orgId, sessionId });
        restored += 1;
      } catch (err) {
        logger.error({ err, orgId, sessionId }, "session.restore_failed");
        continue;
      }
      if (this.restoreStaggerMs > 0) {
        await new Promise<void>((resolve) =>
          setTimeout(resolve, this.restoreStaggerMs).unref(),
        );
      }
    }
    logger.info({ restored }, "manager.restoreAll");
    return { restored };
  }

  status(): { count: number; statuses: Record<SessionStatus, number> } {
    const counts: Record<SessionStatus, number> = {
      pairing: 0,
      connected: 0,
      reconnecting: 0,
      disconnected: 0,
      error: 0,
    };
    for (const s of this.sessions.values()) counts[s.status] += 1;
    return { count: this.sessions.size, statuses: counts };
  }
}

export const manager: SessionManager = new SessionManager();

export { bus };
