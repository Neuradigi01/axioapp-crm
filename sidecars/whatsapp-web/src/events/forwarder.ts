import axios, { type AxiosInstance } from "axios";
import { config } from "../config.js";
import { signOutgoing } from "../auth.js";
import { logger } from "../logger.js";
import { bus } from "./bus.js";
import { RetryQueue, type RetryTask } from "./retry-queue.js";
import type {
  ConnectionLoggedOutPayload,
  ConnectionOpenedPayload,
  ConnectionReconnectingPayload,
  MessageReceivedBusPayload,
  MessageStatusBusPayload,
  QrUpdatedPayload,
} from "../sessions/types.js";

const EVENTS_PATH = "/api/v1/integrations/whatsapp-web/events";

export interface ForwarderConfig {
  client?: AxiosInstance;
  retry?: RetryQueue;
  baseUrl?: string;
  signaturesHeader?: string;
}

export class EventForwarder {
  private readonly client: AxiosInstance;
  private readonly retry: RetryQueue;
  private readonly baseUrl: string;
  private readonly headerName: string;
  private listeners: Array<() => void> = [];
  private started = false;

  constructor(cfg: ForwarderConfig = {}) {
    this.baseUrl = cfg.baseUrl ?? config.FASTAPI_BASE_URL;
    this.client =
      cfg.client ??
      axios.create({
        baseURL: this.baseUrl,
        timeout: 10_000,
        headers: { "Content-Type": "application/json" },
      });
    this.retry = cfg.retry ?? new RetryQueue({ backoffMs: [1_000, 5_000, 30_000, 120_000, 600_000], label: "forwarder" });
    this.headerName = cfg.signaturesHeader ?? "X-Fastapi-Signature";
  }

  start(): void {
    if (this.started) return;
    this.started = true;

    const onQr = (p: QrUpdatedPayload) =>
      this.dispatch({
        type: "qr.updated",
        session_id: p.sessionId,
        org_id: p.orgId,
        qr_data_url: p.qrDataUrl,
      });

    const onOpened = (p: ConnectionOpenedPayload) =>
      this.dispatch({
        type: "connection.opened",
        session_id: p.sessionId,
        org_id: p.orgId,
        phone_number: p.phoneNumber,
      });

    const onLoggedOut = (p: ConnectionLoggedOutPayload) =>
      this.dispatch({
        type: "connection.logged_out",
        session_id: p.sessionId,
        org_id: p.orgId,
        reason: p.reason,
      });

    const onReconnecting = (p: ConnectionReconnectingPayload) =>
      this.dispatch({
        type: "connection.reconnecting",
        session_id: p.sessionId,
        org_id: p.orgId,
        attempt: p.attempt,
        reason: p.reason,
      });

    const onMessage = (p: MessageReceivedBusPayload) =>
      this.dispatch({ ...p.envelope } as { type: string; [k: string]: unknown });
    const onStatus = (p: MessageStatusBusPayload) =>
      this.dispatch({ ...p.envelope } as { type: string; [k: string]: unknown });

    bus.on("qr.updated", onQr);
    bus.on("connection.opened", onOpened);
    bus.on("connection.logged_out", onLoggedOut);
    bus.on("connection.reconnecting", onReconnecting);
    bus.on("message.received", onMessage);
    bus.on("message.status", onStatus);

    this.listeners.push(
      () => bus.off("qr.updated", onQr),
      () => bus.off("connection.opened", onOpened),
      () => bus.off("connection.logged_out", onLoggedOut),
      () => bus.off("connection.reconnecting", onReconnecting),
      () => bus.off("message.received", onMessage),
      () => bus.off("message.status", onStatus),
    );

    logger.info({ baseUrl: this.baseUrl }, "forwarder.started");
  }

  stop(): void {
    for (const off of this.listeners) off();
    this.listeners = [];
    this.started = false;
  }

  private dispatch(envelope: { type: string; [k: string]: unknown }): void {
    void this.post(envelope).catch(() => undefined);
  }

  private async post(envelope: object): Promise<void> {
    const body = JSON.stringify(envelope);
    const signature = signOutgoing(body);

    const task: RetryTask = async () => {
      const res = await this.client.post(EVENTS_PATH, body, {
        headers: { [this.headerName]: signature, "Content-Type": "application/json" },
        validateStatus: (code) => code >= 200 && code < 300,
      });
      logger.debug(
        { status: res.status, type: (envelope as { type?: string }).type },
        "forwarder.delivered",
      );
    };

    try {
      await task();
    } catch (err) {
      const type = (envelope as { type?: string }).type;
      logger.warn({ err, type }, "forwarder.first_attempt_failed");
      this.retry.enqueue(task, type);
    }
  }
}

export const forwarder: EventForwarder = new EventForwarder();
