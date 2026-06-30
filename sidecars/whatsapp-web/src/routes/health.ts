import { Router } from "express";
import { VERSION } from "../config.js";

const startedAt = Date.now();

export const healthRouter: Router = Router();

healthRouter.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    uptime_seconds: Math.floor((Date.now() - startedAt) / 1000),
    version: VERSION,
  });
});
