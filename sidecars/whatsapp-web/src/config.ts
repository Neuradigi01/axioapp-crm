import { z } from "zod";

const EnvSchema = z.object({
  SIDECAR_PORT: z.coerce.number().int().min(1).max(65535).default(4000),
  SIDECAR_HMAC_SECRET: z.string().min(32, "SIDECAR_HMAC_SECRET must be >= 32 chars"),
  FASTAPI_BASE_URL: z.string().url(),
  FASTAPI_HMAC_SECRET: z.string().min(32, "FASTAPI_HMAC_SECRET must be >= 32 chars"),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),
  STORAGE_DIR: z.string().min(1).default("./storage"),
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
});

export type Config = z.infer<typeof EnvSchema>;

export const config: Config = EnvSchema.parse(process.env);

export const VERSION = "0.1.0";
