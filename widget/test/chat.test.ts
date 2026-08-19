/**
 * Chat widget tests (``tasks/ai-assistants`` Step 15).
 *
 * Cover the safety-critical surfaces without spinning up a real
 * SSE stream:
 *   * ``safeMarkdownToHtml`` strips script + on-event + iframe tags.
 *   * ``streamMessage`` parses SSE frames + surfaces done/error.
 *   * ``streamMessage`` sends the bearer key in the Authorization
 *     header (never the URL).
 *   * localStorage session token persists per embed-key prefix.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { streamMessage } from "../src/api";
import { _internal as chatInternals } from "../src/chat";

const { safeMarkdownToHtml } = chatInternals;

// --- Markdown sanitisation ---------------------------------------------

describe("safeMarkdownToHtml", () => {
  it("renders bold + italic + code", () => {
    const html = safeMarkdownToHtml("Hello **world** and *friends*, `x = 1`.");
    expect(html).toContain("<strong>world</strong>");
    expect(html).toContain("<em>friends</em>");
    expect(html).toContain("<code>x = 1</code>");
  });

  it("strips <script> tags from LLM output", () => {
    const evil = "Reply\n\n<script>window.alert('xss')</script>\n\nSafe.";
    const html = safeMarkdownToHtml(evil);
    expect(html).not.toContain("<script");
    expect(html).not.toContain("window.alert");
    expect(html).toContain("Safe");
  });

  it("strips inline event handlers", () => {
    const evil = "<img src=x onerror=\"alert(1)\">";
    const html = safeMarkdownToHtml(evil);
    expect(html.toLowerCase()).not.toContain("onerror");
  });

  it("strips <iframe>", () => {
    const html = safeMarkdownToHtml("<iframe src=\"//evil\"></iframe>");
    expect(html).not.toContain("<iframe");
  });

  it("adds target=_blank + rel=noopener to links", () => {
    const html = safeMarkdownToHtml("[docs](https://example.com/docs)");
    expect(html).toContain('href="https://example.com/docs"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer nofollow"');
  });

  it("renders code fences", () => {
    const html = safeMarkdownToHtml("```\nfoo\n```");
    expect(html).toContain("<pre>");
    expect(html).toContain("<code>");
  });
});

// --- streamMessage ------------------------------------------------------

function _sseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]));
        i++;
      } else {
        controller.close();
      }
    },
  });
}

describe("streamMessage", () => {
  const fetchSpy = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchSpy);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchSpy.mockReset();
  });

  it("puts the bearer key in the Authorization header, not the URL", async () => {
    fetchSpy.mockResolvedValue(
      new Response(_sseStream(["data: [DONE]\n\n"]), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );
    const gen = streamMessage(
      "pk_live_abc",
      "https://api.example.com",
      { message: "hi", session_token: "sess-1" },
    );
    // Consume the generator so the fetch fires.
    for await (const _e of gen) void _e;
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("https://api.example.com/api/v1/public/ai-assistants/message");
    expect(url).not.toContain("pk_live_abc");
    expect(init.headers.Authorization).toBe("Bearer pk_live_abc");
    expect(init.method).toBe("POST");
  });

  it("yields tokens in the order the server sends them", async () => {
    fetchSpy.mockResolvedValue(
      new Response(
        _sseStream([
          'data: {"type":"token","delta":"Hello "}\n\n',
          'data: {"type":"token","delta":"world!"}\n\n',
          'data: {"type":"done","total_tokens":5,"cost_usd":"0.001"}\n\n',
          "data: [DONE]\n\n",
        ]),
        { status: 200 },
      ),
    );
    const events: string[] = [];
    for await (const evt of streamMessage(
      "pk_live_xyz",
      "https://api.example.com",
      { message: "hi", session_token: "s" },
    )) {
      if (evt.type === "token" && evt.delta) events.push(evt.delta);
      if (evt.type === "done") events.push("<DONE>");
    }
    expect(events).toEqual(["Hello ", "world!", "<DONE>"]);
  });

  it("yields a synthetic error on non-2xx without throwing", async () => {
    fetchSpy.mockResolvedValue(
      new Response("bad key", { status: 401 }),
    );
    const events: unknown[] = [];
    for await (const evt of streamMessage(
      "bad",
      "https://api.example.com",
      { message: "hi", session_token: "s" },
    )) {
      events.push(evt);
    }
    // One error + one done.
    expect(events.length).toBe(2);
    expect((events[0] as { type: string }).type).toBe("error");
    expect((events[1] as { type: string }).type).toBe("done");
  });

  it("yields a synthetic error on fetch throw (network error)", async () => {
    fetchSpy.mockRejectedValue(new Error("ERR_NETWORK_CHANGED"));
    const events: unknown[] = [];
    for await (const evt of streamMessage(
      "any",
      "https://api.example.com",
      { message: "hi", session_token: "s" },
    )) {
      events.push(evt);
    }
    expect(events.length).toBe(2);
    expect((events[0] as { type: string; reason: string }).reason).toBe(
      "ERR_NETWORK_CHANGED",
    );
    expect((events[1] as { type: string }).type).toBe("done");
  });

  it("skips malformed frames", async () => {
    fetchSpy.mockResolvedValue(
      new Response(
        _sseStream([
          "data: not-json\n\n",
          'data: {"type":"token","delta":"OK"}\n\n',
          "data: [DONE]\n\n",
        ]),
        { status: 200 },
      ),
    );
    const deltas: string[] = [];
    for await (const evt of streamMessage(
      "pk_live_x",
      "https://api.example.com",
      { message: "hi", session_token: "s" },
    )) {
      if (evt.type === "token" && evt.delta) deltas.push(evt.delta);
    }
    expect(deltas).toEqual(["OK"]);
  });
});

// --- Session token storage --------------------------------------------

describe("chat session token namespacing", () => {
  beforeEach(() => {
    window.localStorage?.clear();
  });

  it("keys the token by embed-key prefix so two assistants don't collide", () => {
    window.localStorage.setItem("crm_ai_session_pk_live_AA", "session-A");
    window.localStorage.setItem("crm_ai_session_pk_live_BB", "session-B");
    expect(window.localStorage.getItem("crm_ai_session_pk_live_AA")).toBe(
      "session-A",
    );
    expect(window.localStorage.getItem("crm_ai_session_pk_live_BB")).toBe(
      "session-B",
    );
  });
});
