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
import type {
  AiAssistantMeta,
  AiStreamEvent,
  SessionInitResponse,
  SubmissionPayload,
  SubmitResult,
  WidgetConfig,
} from "./types";

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

// --- AI Assistant chat mode (Step 15) -----------------------------------

/**
 * Public metadata for widget bootstrap. The bearer key resolves the
 * assistant + org server-side; the widget just gets back the styling +
 * interface config it needs to render itself. Never leaks
 * `instructions` / `key_id`.
 */
export async function getAssistantMeta(
  key: string,
  host: string,
): Promise<AiAssistantMeta> {
  const url = `${host}/api/v1/public/ai-assistants/assistant`;
  const r = await fetch(url, {
    method: "GET",
    mode: "cors",
    headers: {
      Authorization: `Bearer ${key}`,
    },
  });
  if (!r.ok) {
    const detail = await safeReadDetail(r);
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as AiAssistantMeta;
}

export async function initSession(
  key: string,
  host: string,
): Promise<SessionInitResponse> {
  const url = `${host}/api/v1/public/ai-assistants/session/init`;
  const r = await fetch(url, {
    method: "POST",
    mode: "cors",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${key}`,
    },
    body: "{}",
  });
  if (!r.ok) {
    const detail = await safeReadDetail(r);
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as SessionInitResponse;
}

/**
 * Stream one message via SSE. Uses `fetch()` + `ReadableStream` so
 * the bearer key travels in the Authorization header (never the URL
 * query string — visible to every proxy along the way).
 *
 * Returns an async iterator of `AiStreamEvent`. Consumers use
 * `for await (const evt of streamMessage(...))`. Iteration ends
 * when the server closes the connection OR the caller breaks out.
 * On non-2xx, yields one synthetic `error` event followed by `done`
 * — no thrown exception so a single try/catch at the call site is
 * enough.
 */
export async function* streamMessage(
  key: string,
  host: string,
  body: {
    message: string;
    session_token: string;
    captcha_token?: string | null;
  },
  signal?: AbortSignal,
): AsyncGenerator<AiStreamEvent, void, void> {
  const url = `${host}/api/v1/public/ai-assistants/message`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      mode: "cors",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${key}`,
      },
      body: JSON.stringify({
        message: body.message,
        session_token: body.session_token,
        captcha_token: body.captcha_token ?? null,
      }),
      signal,
    });
  } catch (err) {
    // Network error (ERR_NETWORK_CHANGED etc.). Surface the same
    // synthetic-error shape as a 5xx so callers have one code path.
    yield { type: "error", reason: (err as Error)?.message ?? "network_error" };
    yield { type: "done" };
    return;
  }

  if (!response.ok || !response.body) {
    let detail = `HTTP ${response.status}`;
    try {
      const text = await response.text();
      if (text) detail = text;
    } catch {
      /* body already consumed */
    }
    yield { type: "error", reason: detail };
    yield { type: "done" };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Parse `data: ...\n\n` frames as they arrive.
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const line = frame.trim();
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (payload === "[DONE]") return;
        try {
          const evt = JSON.parse(payload) as AiStreamEvent;
          yield evt;
          if (evt.type === "done") return;
        } catch {
          /* malformed frame — skip */
        }
      }
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* already closed */
    }
  }
}
