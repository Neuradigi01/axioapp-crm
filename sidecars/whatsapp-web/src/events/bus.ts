import { EventEmitter } from "node:events";
import type {
  ConnectionLoggedOutPayload,
  ConnectionOpenedPayload,
  ConnectionReconnectingPayload,
  MessageReceivedBusPayload,
  MessageStatusBusPayload,
  QrUpdatedPayload,
} from "../sessions/types.js";

export type BusEventName =
  | "qr.updated"
  | "connection.opened"
  | "connection.logged_out"
  | "connection.reconnecting"
  | "message.received"
  | "message.status";

class Bus extends EventEmitter {}

export const bus: Bus = new Bus();
bus.setMaxListeners(100);

export function emitQrUpdated(payload: QrUpdatedPayload): void {
  bus.emit("qr.updated", payload);
}

export function emitConnectionOpened(payload: ConnectionOpenedPayload): void {
  bus.emit("connection.opened", payload);
}

export function emitConnectionLoggedOut(payload: ConnectionLoggedOutPayload): void {
  bus.emit("connection.logged_out", payload);
}

export function emitConnectionReconnecting(
  payload: ConnectionReconnectingPayload,
): void {
  bus.emit("connection.reconnecting", payload);
}

export function emitMessageReceived(payload: MessageReceivedBusPayload): void {
  bus.emit("message.received", payload);
}

export function emitMessageStatus(payload: MessageStatusBusPayload): void {
  bus.emit("message.status", payload);
}
