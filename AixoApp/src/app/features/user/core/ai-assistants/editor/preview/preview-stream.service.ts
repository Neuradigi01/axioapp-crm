/**
 * SSE helper for the AI Assistant preview stream
 * (``tasks/ai-assistants`` Step 9).
 *
 * Uses ``fetch()`` + ``ReadableStream`` (NOT ``EventSource``) so the
 * JWT can travel in the ``Authorization`` header instead of the URL
 * query string. ``EventSource`` cannot set custom headers, which
 * would force us to put the JWT in the URL — visible to every
 * proxy / access log along the way.
 *
 * Emits three event types matching the backend's ``RuntimeChunk``:
 *
 *   * ``token``  — one incremental content delta.
 *   * ``error``  — runtime rejected the message (budget-cap,
 *                  stop-keyword, provider error, client disconnect).
 *   * ``done``   — terminal marker with total tokens + cost.
 *
 * The consumer (the preview pane) appends ``delta``s to a
 * ``signal<string>`` and re-renders. On ``error`` / ``done`` it
 * flips a ``streaming`` signal off.
 */
import { inject, Injectable } from '@angular/core';

import { environment } from '../../../../../../../environments/environment';
import { TokenStorageService } from '../../../auth/token-storage.service';

export interface PreviewStreamEvent {
  type: 'token' | 'error' | 'done';
  delta?: string;
  reason?: string;
  total_tokens?: number;
  cost_usd?: string;
}

@Injectable({ providedIn: 'root' })
export class PreviewStreamService {
  private readonly tokens = inject(TokenStorageService);

  /** Open the SSE stream for one message. Returns an async
   *  generator the caller iterates via ``for await`` — no RxJS
   *  because the consumer wants signal-friendly serial delivery.
   *  Iteration ends when the server closes the connection OR the
   *  caller breaks out. */
  async *stream(
    assistantId: string,
    message: string,
    sessionToken: string,
    abortSignal?: AbortSignal,
  ): AsyncGenerator<PreviewStreamEvent, void, void> {
    const url = `${environment.apiBaseUrl}/ai-assistants/${assistantId}/preview`;
    const token = this.tokens.getAccess();
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, session_token: sessionToken }),
      signal: abortSignal,
    });

    if (!response.ok || !response.body) {
      // Yield a synthetic error so the caller renders the failure
      // via the same UI path as a mid-stream error.
      let detail = `HTTP ${response.status}`;
      try {
        const body = await response.text();
        detail = body || detail;
      } catch {
        /* body already consumed */
      }
      yield { type: 'error', reason: detail };
      yield { type: 'done' };
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Parse ``data: ...\n\n`` frames as they arrive.
        let boundary: number;
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const line = frame.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (payload === '[DONE]') return;
          try {
            const evt = JSON.parse(payload) as PreviewStreamEvent;
            yield evt;
            if (evt.type === 'done') return;
          } catch {
            // Malformed frame — skip; the server never emits these.
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
}
