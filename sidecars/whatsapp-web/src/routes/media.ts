import { Router } from "express";
import { z } from "zod";
import { downloadMediaMessage } from "@whiskeysockets/baileys";
import { pino } from "pino";
import { manager } from "../sessions/manager.js";
import { logger } from "../logger.js";

const UUID = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);

const BAILEYS_SILENT = pino({ level: "silent" });

function inferMime(message: Record<string, unknown> | null | undefined): string {
  if (!message) return "application/octet-stream";
  const known = ["imageMessage", "videoMessage", "audioMessage", "documentMessage", "stickerMessage"] as const;
  for (const k of known) {
    const m = message[k] as { mimetype?: string } | undefined;
    if (m?.mimetype) return m.mimetype;
  }
  return "application/octet-stream";
}

export const mediaRouter: Router = Router();

mediaRouter.get("/sessions/:sessionId/download-media/:providerMessageId", async (req, res) => {
  const sessionId = req.params.sessionId;
  const providerMessageId = req.params.providerMessageId;
  if (!UUID.safeParse(sessionId).success) {
    res.status(400).json({ error: "invalid session_id" });
    return;
  }
  if (!providerMessageId || providerMessageId.length > 256) {
    res.status(400).json({ error: "invalid provider_message_id" });
    return;
  }

  const session = manager.get(sessionId);
  if (!session) {
    res.status(404).json({ error: "session not found" });
    return;
  }

  const cached = manager.findMessage(sessionId, providerMessageId);
  if (!cached) {
    res.status(404).json({ error: "message not in cache" });
    return;
  }

  try {
    const buffer = await downloadMediaMessage(cached, "buffer", {}, {
      logger: BAILEYS_SILENT,
      reuploadRequest: session.sock.updateMediaMessage,
    });
    if (!buffer || buffer.length === 0) {
      res.status(404).json({ error: "media unavailable" });
      return;
    }
    res.setHeader("Content-Type", inferMime(cached.message as Record<string, unknown>));
    res.setHeader("Content-Length", buffer.length.toString());
    res.status(200).end(buffer);
  } catch (err) {
    logger.warn({ err, sessionId, providerMessageId }, "download_media.failed");
    res.status(502).json({ error: "download_failed", message: (err as Error).message });
  }
});
