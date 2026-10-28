import { Router } from "express";
import { z } from "zod";
import type { AnyMessageContent } from "@whiskeysockets/baileys";
import { manager } from "../sessions/manager.js";
import { outboundLimiter } from "../sessions/rate-limit.js";
import { logger } from "../logger.js";

const UUID = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);

const PhoneDigits = z.string().regex(/^[0-9]{6,18}$/, "to must be digits only (no '+')");

const SendTextBody = z.object({
  to: PhoneDigits,
  body: z.string().min(1).max(4096),
  reply_to: z
    .object({
      id: z.string().min(1),
      remote_jid: z.string().min(1),
    })
    .optional(),
});

const MediaType = z.enum(["image", "video", "audio", "document"]);
const MAX_BASE64_BYTES = 16 * 1024 * 1024;

const SendMediaBody = z.object({
  to: PhoneDigits,
  media_type: MediaType,
  base64: z.string().min(1).max(MAX_BASE64_BYTES),
  mime_type: z.string().min(1).max(255),
  filename: z.string().max(255).optional(),
  caption: z.string().max(1024).optional(),
});

function toJid(phone: string): string {
  return `${phone}@s.whatsapp.net`;
}

function pickMessageId(result: unknown): string | undefined {
  const r = result as { key?: { id?: string | null } } | undefined;
  return r?.key?.id ?? undefined;
}

function buildMediaContent(input: z.infer<typeof SendMediaBody>): AnyMessageContent {
  const buffer = Buffer.from(input.base64, "base64");
  switch (input.media_type) {
    case "image":
      return {
        image: buffer,
        mimetype: input.mime_type,
        caption: input.caption,
      } as AnyMessageContent;
    case "video":
      return {
        video: buffer,
        mimetype: input.mime_type,
        caption: input.caption,
      } as AnyMessageContent;
    case "audio":
      return {
        audio: buffer,
        mimetype: input.mime_type,
      } as AnyMessageContent;
    case "document":
      return {
        document: buffer,
        mimetype: input.mime_type,
        fileName: input.filename,
        caption: input.caption,
      } as AnyMessageContent;
  }
}

export const messagesRouter: Router = Router();

messagesRouter.post("/sessions/:sessionId/send-text", async (req, res) => {
  const sessionId = req.params.sessionId;
  if (!UUID.safeParse(sessionId).success) {
    res.status(400).json({ error: "invalid session_id" });
    return;
  }

  const parsed = SendTextBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "invalid body", issues: parsed.error.issues });
    return;
  }

  const session = manager.get(sessionId);
  if (!session) {
    res.status(404).json({ error: "session not found" });
    return;
  }
  if (session.status !== "connected") {
    res.status(409).json({ error: "session_not_connected", status: session.status });
    return;
  }

  const allow = outboundLimiter.acquire(sessionId);
  if (!allow.ok) {
    res.setHeader("Retry-After", Math.ceil(allow.retry_after_ms / 1000).toString());
    res.status(429).json({
      error: "rate_limited",
      retry_after_seconds: Math.ceil(allow.retry_after_ms / 1000),
      retry_after_ms: allow.retry_after_ms,
    });
    return;
  }

  const jid = toJid(parsed.data.to);
  try {
    const result = await session.sock.sendMessage(jid, { text: parsed.data.body });
    const id = pickMessageId(result);
    if (!id) {
      res.status(502).json({ error: "baileys returned no message id" });
      return;
    }
    res.json({ message_id: id, timestamp: new Date().toISOString() });
  } catch (err) {
    const e = err as { output?: { statusCode?: number }; message?: string };
    logger.warn({ err, sessionId }, "send_text.failed");
    res.status(502).json({
      error: "baileys_send_failed",
      message: e.message ?? "send failed",
      code: e.output?.statusCode,
    });
  }
});

messagesRouter.post("/sessions/:sessionId/send-media", async (req, res) => {
  const sessionId = req.params.sessionId;
  if (!UUID.safeParse(sessionId).success) {
    res.status(400).json({ error: "invalid session_id" });
    return;
  }

  const parsed = SendMediaBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "invalid body", issues: parsed.error.issues });
    return;
  }

  const session = manager.get(sessionId);
  if (!session) {
    res.status(404).json({ error: "session not found" });
    return;
  }
  if (session.status !== "connected") {
    res.status(409).json({ error: "session_not_connected", status: session.status });
    return;
  }

  const allow = outboundLimiter.acquire(sessionId);
  if (!allow.ok) {
    res.setHeader("Retry-After", Math.ceil(allow.retry_after_ms / 1000).toString());
    res.status(429).json({
      error: "rate_limited",
      retry_after_seconds: Math.ceil(allow.retry_after_ms / 1000),
      retry_after_ms: allow.retry_after_ms,
    });
    return;
  }

  const jid = toJid(parsed.data.to);
  try {
    const content = buildMediaContent(parsed.data);
    const result = await session.sock.sendMessage(jid, content);
    const id = pickMessageId(result);
    if (!id) {
      res.status(502).json({ error: "baileys returned no message id" });
      return;
    }
    res.json({ message_id: id, timestamp: new Date().toISOString() });
  } catch (err) {
    const e = err as { output?: { statusCode?: number }; message?: string };
    logger.warn({ err, sessionId }, "send_media.failed");
    res.status(502).json({
      error: "baileys_send_failed",
      message: e.message ?? "send failed",
      code: e.output?.statusCode,
    });
  }
});
