import { EventEmitter } from "node:events";
import type { WASocket } from "@whiskeysockets/baileys";

export interface MockSocket {
  ev: EventEmitter;
  user: { id: string } | undefined;
  logout: (msg?: string) => Promise<void>;
  end: (err: Error | undefined) => void;
  __emit: (name: string, payload: unknown) => boolean;
}

interface MockOptions {
  initialUser?: { id: string };
  onLogout?: () => void | Promise<void>;
  onEnd?: () => void;
}

export function createMockSocket(opts: MockOptions = {}): MockSocket {
  const ev = new EventEmitter();
  ev.setMaxListeners(50);
  const sock: MockSocket = {
    ev,
    user: opts.initialUser,
    logout: async () => {
      await opts.onLogout?.();
    },
    end: () => {
      opts.onEnd?.();
    },
    __emit: (name, payload) => ev.emit(name, payload),
  };
  return sock;
}

export interface MockMakeSocketHooks {
  socketsCreated: MockSocket[];
  configsSeen: unknown[];
}

export function makeMockFactory(hooks: MockMakeSocketHooks): typeof import("@whiskeysockets/baileys").default {
  const fn = ((config: unknown) => {
    hooks.configsSeen.push(config);
    const sock = createMockSocket();
    hooks.socketsCreated.push(sock);
    return sock as unknown as WASocket;
  }) as unknown as typeof import("@whiskeysockets/baileys").default;
  return fn;
}
