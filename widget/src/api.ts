/**
 * Thin typed wrappers around the two backend endpoints the widget
 * needs:
 *
 *   GET  /api/v1/embed/config/public?key=…  → render the form
 *   POST /api/v1/embed/leads                → submit a lead
 *
 * Uses native `fetch` — no XHR, no polyfill, no fetch wrapper lib.
 * `mode: "cors"` + no `credentials` so the host site's session
 * cookies never leak across the boundary.
 *
 * Errors surface as `ApiError(status, detail)`. The orchestrator
 * (index.ts) inspects `err.status` to decide between "show error
 * banner" (4xx/5xx) and "fall back to defaults" (network / 0 /
 * `/embed/config/public` outage).
 */
import type { SubmissionPayload, SubmitResult, WidgetConfig } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface PublicConfigEnvelope {
  config: WidgetConfig;
}

export async function getConfig(
  key: string,
  host: string,
): Promise<WidgetConfig> {
  const url = `${host}/api/v1/embed/config/public?key=${encodeURIComponent(key)}`;
  const r = await fetch(url, { mode: "cors" });
  if (!r.ok) {
    const detail = await safeReadDetail(r);
    throw new ApiError(r.status, detail);
  }
  const envelope = (await r.json()) as PublicConfigEnvelope;
  return envelope.config;
}

export async function submitLead(
  key: string,
  host: string,
  payload: SubmissionPayload,
): Promise<SubmitResult> {
  const url = `${host}/api/v1/embed/leads`;
  const r = await fetch(url, {
    method: "POST",
    mode: "cors",
    headers: {
      "Content-Type": "application/json",
      "X-FurniCRM-Key": key,
    },
    body: JSON.stringify(payload),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail =
      typeof body?.detail === "string" ? body.detail : "Submission failed";
    throw new ApiError(r.status, detail);
  }
  return body as SubmitResult;
}

async function safeReadDetail(r: Response): Promise<string> {
  try {
    const body = await r.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* response wasn't JSON */
  }
  return r.statusText || `HTTP ${r.status}`;
}
