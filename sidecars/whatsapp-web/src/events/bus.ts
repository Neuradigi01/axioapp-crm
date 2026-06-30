import { EventEmitter } from "node:events";
import type {
  ConnectionLoggedOutPayload,
  ConnectionOpenedPayload,
  ConnectionReconnectingPayload,
  QrUpdatedPayload,
} from "../sessions/types.js";

export type SidecarEvent =
  | { type: "qr.updated"; payload: QrUpdatedPayload }
  | { type: "connection.opened"; payload: ConnectionOpenedPayload }
  | { type: "connection.logged_out"; payload: ConnectionLoggedOutPayload }
  | { type: "connection.reconnecting"; payload: ConnectionReconnectingPayload };

class Bus extends EventEmitter {}

export const bus: Bus = new Bus();
bus.setMaxListeners(50);

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
