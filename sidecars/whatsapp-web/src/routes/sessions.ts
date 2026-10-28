import { Router } from "express";
import { z } from "zod";
import { manager } from "../sessions/manager.js";
import { InvalidIdError } from "../sessions/auth-store.js";
import { toSessionView } from "../sessions/types.js";
import { logger } from "../logger.js";

const UUID = z
  .string()
  .regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);

const CreateBody = z.object({
  org_id: UUID,
  session_id: UUID,
});

export const sessionsRouter: Router = Router();

sessionsRouter.post("/sessions", async (req, res) => {
  const parsed = CreateBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "invalid body", issues: parsed.error.issues });
    return;
  }
  const { org_id, session_id } = parsed.data;
  try {
    const session = await manager.create({ orgId: org_id, sessionId: session_id });
    res.status(200).json(toSessionView(session));
  } catch (err) {
    if (err instanceof InvalidIdError) {
      res.status(400).json({ error: err.message });
      return;
    }
    logger.error({ err, session_id }, "sessions.create_failed");
    res.status(500).json({ error: "session create failed" });
  }
});

sessionsRouter.get("/sessions/:sessionId", (req, res) => {
  const sessionId = req.params.sessionId;
  if (!UUID.safeParse(sessionId).success) {
    res.status(400).json({ error: "invalid session_id" });
    return;
  }
  const session = manager.get(sessionId);
  if (!session) {
    res.status(404).json({ error: "session not found" });
    return;
  }
  res.json(toSessionView(session));
});

sessionsRouter.delete("/sessions/:sessionId", async (req, res) => {
  const sessionId = req.params.sessionId;
  if (!UUID.safeParse(sessionId).success) {
    res.status(400).json({ error: "invalid session_id" });
    return;
  }
  const ok = await manager.destroy(sessionId);
  if (!ok) {
    res.status(404).json({ error: "session not found" });
    return;
  }
  res.status(204).end();
});
