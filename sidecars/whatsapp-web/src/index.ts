import express, { type Request, type Response, type NextFunction } from "express";
import { config } from "./config.js";
import { logger } from "./logger.js";
import { hmacMiddleware } from "./auth.js";
import { healthRouter } from "./routes/health.js";
import { sessionsRouter } from "./routes/sessions.js";
import { manager } from "./sessions/manager.js";

type RawBodyRequest = Request & { rawBody?: Buffer };

const app = express();

app.use(
  express.json({
    limit: "10mb",
    verify: (req, _res, buf) => {
      (req as RawBodyRequest).rawBody = Buffer.from(buf);
    },
  }),
);

app.use(healthRouter);

app.use(hmacMiddleware);

app.use(sessionsRouter);

app.use((_req, res) => {
  res.status(404).json({ error: "not found" });
});

app.use((err: Error, req: Request, res: Response, _next: NextFunction) => {
  logger.error({ err, path: req.path }, "unhandled_error");
  res.status(500).json({ error: "internal error" });
});

async function bootstrap(): Promise<void> {
  try {
    await manager.restoreAll();
  } catch (err) {
    logger.error({ err }, "manager.restoreAll_failed");
  }

  const server = app.listen(config.SIDECAR_PORT, () => {
    logger.info(
      { port: config.SIDECAR_PORT, node_env: config.NODE_ENV },
      "sidecar.listening",
    );
  });

  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => {
      logger.info({ signal }, "sidecar.shutdown");
      server.close(() => process.exit(0));
    });
  }
}

void bootstrap();
