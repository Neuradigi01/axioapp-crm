import crypto from "node:crypto";
import type { Request, Response, NextFunction } from "express";
import { config } from "./config.js";
import { logger } from "./logger.js";

const SIG_PREFIX = "sha256=";

export function sign(body: string, secret: string): string {
  const digest = crypto.createHmac("sha256", secret).update(body).digest("hex");
  return SIG_PREFIX + digest;
}

export function verify(body: string, header: string | undefined, secret: string): boolean {
  if (!header || !header.startsWith(SIG_PREFIX)) return false;
  const expected = sign(body, secret);
  const headerBuf = Buffer.from(header);
  const expectedBuf = Buffer.from(expected);
  if (headerBuf.length !== expectedBuf.length) return false;
  return crypto.timingSafeEqual(headerBuf, expectedBuf);
}

export function signOutgoing(body: string): string {
  return sign(body, config.FASTAPI_HMAC_SECRET);
}

type RawBodyRequest = Request & { rawBody?: Buffer };

export function hmacMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (req.path === "/health") {
    next();
    return;
  }

  const header = req.header("X-Sidecar-Signature");
  const rawBody = (req as RawBodyRequest).rawBody ?? Buffer.alloc(0);
  const ok = verify(rawBody.toString("utf8"), header, config.SIDECAR_HMAC_SECRET);

  if (!ok) {
    logger.warn({ path: req.path, method: req.method }, "hmac.verify_failed");
    res.status(401).json({ error: "invalid signature" });
    return;
  }

  next();
}
