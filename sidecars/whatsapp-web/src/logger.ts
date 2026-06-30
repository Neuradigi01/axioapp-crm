import { pino, type LoggerOptions } from "pino";
import { config } from "./config.js";

const baseOptions: LoggerOptions = {
  level: config.LOG_LEVEL,
  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers["x-sidecar-signature"]',
      'req.headers["x-fastapi-signature"]',
      "*.secret",
      "*.token",
      "*.password",
    ],
    censor: "[redacted]",
  },
};

const transport =
  config.NODE_ENV === "production"
    ? undefined
    : { target: "pino-pretty", options: { colorize: true, translateTime: "SYS:standard" } };

export const logger = pino(transport ? { ...baseOptions, transport } : baseOptions);
