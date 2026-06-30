import path from "node:path";
import fs from "node:fs/promises";
import { useMultiFileAuthState, type AuthenticationState } from "@whiskeysockets/baileys";
import { config } from "../config.js";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class InvalidIdError extends Error {
  constructor(field: string, value: string) {
    super(`invalid ${field}: ${value}`);
    this.name = "InvalidIdError";
  }
}

export interface LoadedAuthState {
  state: AuthenticationState;
  saveCreds: () => Promise<void>;
}

export interface SessionStorage {
  load(orgId: string, sessionId: string): Promise<LoadedAuthState>;
  destroy(orgId: string, sessionId: string): Promise<void>;
  list(): Promise<Array<{ orgId: string; sessionId: string }>>;
  resolvePath(orgId: string, sessionId: string): string;
}

function validateUuid(value: string, field: string): void {
  if (!UUID_RE.test(value)) {
    throw new InvalidIdError(field, value);
  }
}

function sessionsRoot(): string {
  return path.resolve(config.STORAGE_DIR, "sessions");
}

export const filesystemStorage: SessionStorage = {
  resolvePath(orgId, sessionId) {
    validateUuid(orgId, "org_id");
    validateUuid(sessionId, "session_id");
    return path.join(sessionsRoot(), orgId, sessionId);
  },

  async load(orgId, sessionId) {
    const dir = this.resolvePath(orgId, sessionId);
    await fs.mkdir(dir, { recursive: true });
    return useMultiFileAuthState(dir);
  },

  async destroy(orgId, sessionId) {
    const dir = this.resolvePath(orgId, sessionId);
    await fs.rm(dir, { recursive: true, force: true });
  },

  async list() {
    const root = sessionsRoot();
    let orgs: string[];
    try {
      orgs = await fs.readdir(root);
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw err;
    }
    const out: Array<{ orgId: string; sessionId: string }> = [];
    for (const orgId of orgs) {
      if (!UUID_RE.test(orgId)) continue;
      let sessions: string[];
      try {
        sessions = await fs.readdir(path.join(root, orgId));
      } catch {
        continue;
      }
      for (const sessionId of sessions) {
        if (!UUID_RE.test(sessionId)) continue;
        out.push({ orgId, sessionId });
      }
    }
    return out;
  },
};

export function isValidUuid(value: string): boolean {
  return UUID_RE.test(value);
}
