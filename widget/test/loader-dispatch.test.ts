/**
 * Loader dispatch tests (``tasks/ai-assistants`` Step 15).
 *
 * Exercise the ``resource_type`` dispatch that ``init()`` performs:
 * if ``GET /public/ai-assistants/assistant`` answers 200, the chat
 * renderer takes over; on 401 (wrong resource type) or other error,
 * we fall through to the existing lead-form path.
 *
 * These tests stub ``fetch`` — a real network call would break CI.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { init } from "../src/index";

const HOST = "https://api.test";
const FORM_KEY = "pk_live_LEADFORM";
const AI_KEY = "pk_live_AI_ASSIST";

const AI_META_BODY = {
  id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
  name: "Support Bot",
  interface_config: {
    header_heading: "Support Bot",
    header_subheading: "How can we help?",
    initial_messages: ["Hi! Ask me anything."],
    show_powered_by: true,
    footer_text: "Privacy",
    footer_link: "https://example.com/privacy",
  },
  styling_config: {
    assistant_bg: "#112233",
    assistant_text: "#FFFFFF",
    bg: "#FFFFFF",
    cta_bg: "#0088AA",
    bubble_bg: "#FEFEFE",
    bubble_text: "#111",
    footer_bg: "#FFFFFF",
    footer_text: "#666",
    assistant_shape: "circle",
  },
};

const FORM_CONFIG_BODY = {
  config: {
    fields: [
      {
        key: "full_name",
        label: "Name",
        required: true,
        order: 0,
        field_type: "text",
        field_source: "standard",
        entity: "contact",
      },
    ],
    submit_button_label: "Submit",
    thank_you_message: "Thanks!",
    thank_you_url: null,
    branding: {
      logo_url: null,
      accent_color: "#000",
      show_powered_by: false,
    },
    spam_protection: {
      recaptcha_enabled: false,
      recaptcha_site_key: null,
      min_fill_time_ms: 0,
    },
  },
};

// --- Fixtures ----------------------------------------------------------

function _mountDiv(id: string): HTMLDivElement {
  const div = document.createElement("div");
  div.id = id;
  document.body.appendChild(div);
  return div;
}

function _jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  window.localStorage?.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});


// --- Chat dispatch (200 on /assistant) --------------------------------

describe("init() with an ai_assistant key", () => {
  it("renders the chat widget when /assistant returns 200", async () => {
    const mount = _mountDiv("crm-mount");
    const fetchSpy = vi.fn(async (url: string) => {
      if (url.includes("/public/ai-assistants/assistant")) {
        return _jsonResponse(AI_META_BODY);
      }
      if (url.includes("/public/ai-assistants/session/init")) {
        return _jsonResponse({
          session_token: "pub-test-tok",
          requires_captcha: true,
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchSpy);

    await init({ key: AI_KEY, host: HOST, mountId: "crm-mount" });

    // Chat root must exist + header heading present.
    expect(mount.querySelector(".crm-ai-chat")).not.toBeNull();
    expect(mount.querySelector(".crm-ai-heading")?.textContent).toBe(
      "Support Bot",
    );
    // Composer input must exist.
    expect(mount.querySelector(".crm-ai-input")).not.toBeNull();
    // /assistant must have used the Authorization header, not the URL.
    const metaCall = fetchSpy.mock.calls.find((c) =>
      String(c[0]).includes("/assistant"),
    );
    expect(metaCall).toBeDefined();
    const [url, init2] = metaCall!;
    expect(String(url)).not.toContain(AI_KEY);
    expect(
      (init2 as RequestInit).headers as Record<string, string>,
    ).toMatchObject({ Authorization: `Bearer ${AI_KEY}` });
  });
});


// --- Form fallback (401 on /assistant) --------------------------------

describe("init() with a lead-form key", () => {
  it("falls through to the form renderer when /assistant returns 401", async () => {
    const mount = _mountDiv("crm-mount");
    const fetchSpy = vi.fn(async (url: string) => {
      if (url.includes("/public/ai-assistants/assistant")) {
        // 401 with detail={reason:'invalid_key'} — the standard
        // "this isn't an AI-assistant key" response from Step 14.
        return _jsonResponse(
          { detail: { reason: "invalid_key" } },
          401,
        );
      }
      if (url.includes("/embed/config/public")) {
        return _jsonResponse(FORM_CONFIG_BODY);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchSpy);

    await init({ key: FORM_KEY, host: HOST, mountId: "crm-mount" });

    // Chat root should NOT exist.
    expect(mount.querySelector(".crm-ai-chat")).toBeNull();
    // Form should exist (the existing renderer emits .furnicrm-form).
    expect(mount.querySelector(".furnicrm-form")).not.toBeNull();
  });
});
