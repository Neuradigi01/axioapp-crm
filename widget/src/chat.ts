/**
 * AI-assistant chat widget
 * (``tasks/ai-assistants`` Step 15).
 *
 * Two-panel render inside the host page's mount div:
 *   1. Header — profile picture (or fallback sparkles), heading,
 *      subheading, close-x button (visual only in v1 — we don't
 *      teardown the widget because there's no re-open affordance).
 *   2. Body — vertically stacked message bubbles. Initial-messages
 *      from ``interface_config.initial_messages`` render first;
 *      user turns + assistant turns append below as they happen.
 *   3. Composer — a text input + Send button, plus a Turnstile
 *      slot when the backend flags ``requires_captcha`` on the
 *      first turn.
 *   4. Footer — optional "⚡ Powered by CRM" + configured footer link.
 *
 * Wire:
 *   * ``GET /public/ai-assistants/assistant`` — bootstrap.
 *   * ``POST /public/ai-assistants/session/init`` — session token
 *     (persisted per-key in localStorage so a page reload keeps the
 *     conversation identifier).
 *   * ``POST /public/ai-assistants/message`` — SSE stream of tokens.
 *
 * Bearer key travels in the Authorization header on every call. Every
 * assistant reply body is markdown → :func:`safeMarkdownToHtml` (marked
 * → DOMPurify) so a malicious model output can't inject script tags.
 */
import DOMPurify from "dompurify";
import { marked } from "marked";

import { ApiError, getAssistantMeta, initSession, streamMessage } from "./api";
import type {
  AiAssistantMeta,
  AiStreamEvent,
  InitConfig,
} from "./types";

// --- Config helpers ---------------------------------------------------

const IFACE_DEFAULTS = {
  header_heading: "Your Brand Name 👋",
  header_subheading: "We're online and happy to assist you!",
  initial_messages: ["Hi there! 👋 How can I help you today?"],
  show_powered_by: true,
  footer_text: "Privacy Policy",
  footer_link: "https://www.example.com/privacy-policy/",
};

const STYLE_DEFAULTS = {
  assistant_bg: "#128C7E",
  assistant_text: "#FFFFFF",
  bg: "#FFFFFF",
  cta_bg: "#25D366",
  bubble_bg: "#FEFEFE",
  bubble_text: "#1C252E",
  footer_bg: "#FFFFFF",
  footer_text: "#637381",
  assistant_shape: "circle",
  header_profile_picture_url: null as string | null,
};

function _cfgStr(cfg: Record<string, unknown>, key: string, fallback: string): string {
  const v = cfg[key];
  return typeof v === "string" && v.length > 0 ? v : fallback;
}
function _cfgBool(cfg: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const v = cfg[key];
  return typeof v === "boolean" ? v : fallback;
}
function _cfgStrOrNull(cfg: Record<string, unknown>, key: string): string | null {
  const v = cfg[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}
function _cfgStrList(cfg: Record<string, unknown>, key: string, fallback: string[]): string[] {
  const v = cfg[key];
  if (Array.isArray(v) && v.every((x) => typeof x === "string")) return v as string[];
  return fallback;
}

// --- Session token ----------------------------------------------------

/**
 * Namespaced per embed-key prefix so a page hosting two different
 * assistants (different bearer keys) doesn't collide sessions.
 * Falls back to a memory-only token when ``localStorage`` is
 * unavailable (private browsing / disabled cookies).
 */
function _sessionKey(embedKey: string): string {
  const prefix = embedKey.slice(0, 11);
  return `crm_ai_session_${prefix}`;
}

function _loadCachedSession(embedKey: string): string | null {
  try {
    return window.localStorage?.getItem(_sessionKey(embedKey)) ?? null;
  } catch {
    return null;
  }
}

function _storeCachedSession(embedKey: string, token: string): void {
  try {
    window.localStorage?.setItem(_sessionKey(embedKey), token);
  } catch {
    /* private browsing — memory-only for this pageload */
  }
}

// --- Markdown sanitisation --------------------------------------------

/**
 * Convert model-output markdown to safe HTML.
 *
 * Layer 1 — ``marked`` with ``gfm+breaks`` handles the common
 * cases (bold, italic, links, lists, code fences, tables).
 *
 * Layer 2 — ``DOMPurify`` strips anything ``marked`` shouldn't have
 * emitted (script / style / on* handlers) as belt+braces against a
 * markdown parser bug or a future ``renderer`` extension. Default
 * config accepts standard markdown tags + safe attributes; we
 * explicitly opt-in ``target=_blank`` on ``<a>`` so links open away
 * from the host page.
 */
export function safeMarkdownToHtml(source: string): string {
  const raw = marked.parse(source, { gfm: true, breaks: true, async: false }) as string;
  const sanitised = DOMPurify.sanitize(raw, {
    ADD_ATTR: ["target", "rel"],
    FORBID_TAGS: ["style", "script", "iframe", "form", "input", "button"],
    FORBID_ATTR: ["style", "onerror", "onload", "onclick"],
  });
  // Force safe rel + target on every anchor. Skip in non-DOM shells
  // (should never trigger — chat.ts only runs in the browser).
  if (typeof document !== "undefined") {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = sanitised;
    wrapper.querySelectorAll("a[href]").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer nofollow");
    });
    return wrapper.innerHTML;
  }
  return sanitised;
}

// --- Rendering ---------------------------------------------------------

interface ChatContext {
  config: InitConfig;
  meta: AiAssistantMeta;
  sessionToken: string;
  requiresCaptcha: boolean;
  mount: HTMLElement;
  bodyEl: HTMLElement;
  inputEl: HTMLInputElement;
  sendBtn: HTMLButtonElement;
  captchaTokenGetter: () => string | null;
}

function _pill(text: string, sourceUrl: string | null, style: typeof STYLE_DEFAULTS, shape: string): HTMLElement {
  // Header avatar element. Renders profile picture if set, else a
  // sparkles-emoji fallback that carries the assistant_text colour.
  const el = document.createElement("div");
  el.className = "crm-ai-avatar";
  el.style.setProperty("background", "rgba(255,255,255,0.2)");
  el.style.setProperty("color", style.assistant_text);
  el.style.setProperty("border-radius", shape === "square" ? "6px" : "50%");
  if (sourceUrl) {
    const img = document.createElement("img");
    img.src = sourceUrl;
    img.alt = "";
    el.appendChild(img);
  } else {
    el.textContent = text;
  }
  return el;
}

function renderChat(mount: HTMLElement, meta: AiAssistantMeta, requiresCaptcha: boolean): {
  bodyEl: HTMLElement;
  inputEl: HTMLInputElement;
  sendBtn: HTMLButtonElement;
  captchaSlot: HTMLElement;
} {
  mount.innerHTML = "";

  const iface = meta.interface_config;
  const style = meta.styling_config;
  const heading = _cfgStr(iface, "header_heading", IFACE_DEFAULTS.header_heading);
  const sub = _cfgStr(iface, "header_subheading", IFACE_DEFAULTS.header_subheading);
  const initialMessages = _cfgStrList(iface, "initial_messages", IFACE_DEFAULTS.initial_messages);
  const showPoweredBy = _cfgBool(iface, "show_powered_by", IFACE_DEFAULTS.show_powered_by);
  const footerText = _cfgStr(iface, "footer_text", IFACE_DEFAULTS.footer_text);
  const footerLink = _cfgStr(iface, "footer_link", IFACE_DEFAULTS.footer_link);

  const styling = {
    assistant_bg: _cfgStr(style, "assistant_bg", STYLE_DEFAULTS.assistant_bg),
    assistant_text: _cfgStr(style, "assistant_text", STYLE_DEFAULTS.assistant_text),
    bg: _cfgStr(style, "bg", STYLE_DEFAULTS.bg),
    cta_bg: _cfgStr(style, "cta_bg", STYLE_DEFAULTS.cta_bg),
    bubble_bg: _cfgStr(style, "bubble_bg", STYLE_DEFAULTS.bubble_bg),
    bubble_text: _cfgStr(style, "bubble_text", STYLE_DEFAULTS.bubble_text),
    footer_bg: _cfgStr(style, "footer_bg", STYLE_DEFAULTS.footer_bg),
    footer_text: _cfgStr(style, "footer_text", STYLE_DEFAULTS.footer_text),
    assistant_shape: _cfgStr(style, "assistant_shape", STYLE_DEFAULTS.assistant_shape),
    header_profile_picture_url: _cfgStrOrNull(style, "header_profile_picture_url"),
  };

  const root = document.createElement("div");
  root.className = "crm-ai-chat";
  root.style.setProperty("background", styling.bg);

  // Header ------------------------------------------------------------
  const header = document.createElement("div");
  header.className = "crm-ai-header";
  header.style.setProperty("background", styling.assistant_bg);
  header.style.setProperty("color", styling.assistant_text);
  header.appendChild(
    _pill("✨", styling.header_profile_picture_url, styling, styling.assistant_shape),
  );
  const titleBox = document.createElement("div");
  titleBox.className = "crm-ai-title";
  const h = document.createElement("div");
  h.className = "crm-ai-heading";
  h.textContent = heading;
  const s = document.createElement("div");
  s.className = "crm-ai-sub";
  s.textContent = sub;
  titleBox.appendChild(h);
  titleBox.appendChild(s);
  header.appendChild(titleBox);

  // Body --------------------------------------------------------------
  const body = document.createElement("div");
  body.className = "crm-ai-body";
  body.style.setProperty("background", styling.bg);
  for (const m of initialMessages) {
    body.appendChild(_bubble(m, "assistant", styling));
  }

  // Composer ----------------------------------------------------------
  const composer = document.createElement("div");
  composer.className = "crm-ai-composer";
  composer.style.setProperty("background", styling.bg);
  const captchaSlot = document.createElement("div");
  captchaSlot.className = "crm-ai-captcha";
  captchaSlot.setAttribute("data-requires-captcha", requiresCaptcha ? "true" : "false");
  const inputRow = document.createElement("div");
  inputRow.className = "crm-ai-input-row";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "Type a message…";
  input.className = "crm-ai-input";
  input.setAttribute("aria-label", "Type your message");
  const send = document.createElement("button");
  send.type = "button";
  send.className = "crm-ai-send";
  send.textContent = "Send";
  send.style.setProperty("background", styling.cta_bg);
  send.style.setProperty("color", "#FFFFFF");
  inputRow.appendChild(input);
  inputRow.appendChild(send);
  composer.appendChild(captchaSlot);
  composer.appendChild(inputRow);

  // Footer ------------------------------------------------------------
  const footer = document.createElement("div");
  footer.className = "crm-ai-footer";
  footer.style.setProperty("background", styling.footer_bg);
  footer.style.setProperty("color", styling.footer_text);
  if (showPoweredBy) {
    const p = document.createElement("span");
    p.textContent = "⚡ Powered by CRM";
    footer.appendChild(p);
  } else {
    footer.appendChild(document.createElement("span"));
  }
  const link = document.createElement("a");
  link.href = footerLink;
  link.target = "_blank";
  link.rel = "noopener noreferrer nofollow";
  link.textContent = footerText;
  link.style.setProperty("color", styling.footer_text);
  footer.appendChild(link);

  root.appendChild(header);
  root.appendChild(body);
  root.appendChild(composer);
  root.appendChild(footer);
  mount.appendChild(root);

  return { bodyEl: body, inputEl: input, sendBtn: send, captchaSlot };
}

function _bubble(
  content: string,
  role: "user" | "assistant",
  styling: {
    cta_bg: string;
    bubble_bg: string;
    bubble_text: string;
  },
): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = `crm-ai-bubble-wrap crm-ai-bubble-${role}`;
  const bubble = document.createElement("div");
  bubble.className = `crm-ai-bubble crm-ai-bubble-${role}`;
  if (role === "user") {
    bubble.style.setProperty("background", styling.cta_bg);
    bubble.style.setProperty("color", "#FFFFFF");
    bubble.textContent = content;
  } else {
    bubble.style.setProperty("background", styling.bubble_bg);
    bubble.style.setProperty("color", styling.bubble_text);
    bubble.innerHTML = safeMarkdownToHtml(content);
  }
  wrap.appendChild(bubble);
  return wrap;
}

// --- Turnstile bootstrap ----------------------------------------------

const TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js";
let _turnstileScriptLoaded = false;

/**
 * Load the Cloudflare Turnstile script + render an invisible widget
 * into the captcha slot. Returns a getter that yields the current
 * token (or null if the visitor hasn't solved yet). Missing site
 * key = no-op that always returns a dev bypass token so local /
 * smoke deployments work without Cloudflare credentials.
 */
function bootstrapTurnstile(slot: HTMLElement): () => string | null {
  const siteKey = slot.dataset.siteKey;
  if (!siteKey) {
    // Dev/smoke path: return Cloudflare's documented always-pass token.
    return () => "1x0000000000000000000000000000000AA";
  }
  if (!_turnstileScriptLoaded) {
    const s = document.createElement("script");
    s.src = TURNSTILE_SCRIPT;
    s.async = true;
    s.defer = true;
    document.head.appendChild(s);
    _turnstileScriptLoaded = true;
  }
  const holder = document.createElement("div");
  holder.className = "cf-turnstile";
  holder.setAttribute("data-sitekey", siteKey);
  slot.appendChild(holder);
  return () => {
    // The Turnstile widget renders a hidden input named
    // ``cf-turnstile-response`` into its container once solved.
    const el = holder.querySelector<HTMLInputElement>(
      'input[name="cf-turnstile-response"]',
    );
    return el?.value?.trim() || null;
  };
}

// --- Turn handling ----------------------------------------------------

async function sendTurn(ctx: ChatContext, message: string): Promise<void> {
  // Append the user's bubble immediately.
  const styling = _readStyling(ctx.meta);
  ctx.bodyEl.appendChild(_bubble(message, "user", styling));

  // Fresh assistant bubble that we mutate as tokens stream in. Start
  // with a subtle typing indicator so the user knows something is
  // happening (empty bubble looks broken during LLM cold-start).
  const asstWrap = document.createElement("div");
  asstWrap.className = "crm-ai-bubble-wrap crm-ai-bubble-assistant";
  const asstBubble = document.createElement("div");
  asstBubble.className = "crm-ai-bubble crm-ai-bubble-assistant";
  asstBubble.style.setProperty("background", styling.bubble_bg);
  asstBubble.style.setProperty("color", styling.bubble_text);
  asstBubble.textContent = "…";
  asstWrap.appendChild(asstBubble);
  ctx.bodyEl.appendChild(asstWrap);
  ctx.bodyEl.scrollTop = ctx.bodyEl.scrollHeight;

  const captchaToken = ctx.requiresCaptcha ? ctx.captchaTokenGetter() : null;
  if (ctx.requiresCaptcha && !captchaToken) {
    asstBubble.innerHTML = safeMarkdownToHtml(
      "*Please complete the CAPTCHA below before sending.*",
    );
    return;
  }

  let acc = "";
  let terminated = false;
  try {
    for await (const evt of streamMessage(ctx.config.key, ctx.config.host, {
      message,
      session_token: ctx.sessionToken,
      captcha_token: captchaToken,
    })) {
      if (evt.type === "token" && evt.delta) {
        acc += evt.delta;
        asstBubble.innerHTML = safeMarkdownToHtml(acc);
        ctx.bodyEl.scrollTop = ctx.bodyEl.scrollHeight;
      } else if (evt.type === "error") {
        terminated = true;
        const reason = evt.reason ?? "Something went wrong.";
        asstBubble.innerHTML = safeMarkdownToHtml(
          `⚠️ ${escapeAsMarkdown(reason)}`,
        );
      } else if (evt.type === "done") {
        break;
      }
    }
  } catch (err) {
    if (!terminated) {
      asstBubble.innerHTML = safeMarkdownToHtml(
        `⚠️ Network error — please try again.`,
      );
    }
    // Don't rethrow — the composer is already reset via `finally`.
    // eslint-disable-next-line no-console
    console.warn("[CRM chat] stream error", err);
  }
  // First message consumed the CAPTCHA — subsequent turns in this
  // session skip the challenge (server keeps the session verified
  // for 5 minutes).
  ctx.requiresCaptcha = false;
}

function escapeAsMarkdown(text: string): string {
  // The failure reasons come from the server so they're already
  // safe; escape underscores + asterisks so a "*" in a reason doesn't
  // italicise half the sentence in the sanitised HTML output.
  return text.replace(/[*_`]/g, (m) => `\\${m}`);
}

function _readStyling(meta: AiAssistantMeta): typeof STYLE_DEFAULTS {
  const style = meta.styling_config;
  return {
    assistant_bg: _cfgStr(style, "assistant_bg", STYLE_DEFAULTS.assistant_bg),
    assistant_text: _cfgStr(style, "assistant_text", STYLE_DEFAULTS.assistant_text),
    bg: _cfgStr(style, "bg", STYLE_DEFAULTS.bg),
    cta_bg: _cfgStr(style, "cta_bg", STYLE_DEFAULTS.cta_bg),
    bubble_bg: _cfgStr(style, "bubble_bg", STYLE_DEFAULTS.bubble_bg),
    bubble_text: _cfgStr(style, "bubble_text", STYLE_DEFAULTS.bubble_text),
    footer_bg: _cfgStr(style, "footer_bg", STYLE_DEFAULTS.footer_bg),
    footer_text: _cfgStr(style, "footer_text", STYLE_DEFAULTS.footer_text),
    assistant_shape: _cfgStr(style, "assistant_shape", STYLE_DEFAULTS.assistant_shape),
    header_profile_picture_url: _cfgStrOrNull(style, "header_profile_picture_url"),
  };
}

// --- Public entry point -----------------------------------------------

/**
 * Bootstrap the chat widget. Called by :mod:`index` when the resolved
 * embed key has ``resource_type='ai_assistant'``. Same signature +
 * error semantics as the form-renderer path so a future 3rd renderer
 * (voice? forms-plus-chat?) fits without a bigger dispatcher refactor.
 */
export async function initChatWidget(
  mount: HTMLElement,
  config: InitConfig,
): Promise<void> {
  // 1. Bootstrap metadata + session.
  let meta: AiAssistantMeta;
  try {
    meta = await getAssistantMeta(config.key, config.host);
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 401
        ? "This chat is not active. Please contact the site owner."
        : "Could not load chat right now. Please try again in a moment.";
    mount.innerHTML = "";
    const p = document.createElement("p");
    p.textContent = msg;
    p.style.setProperty("padding", "12px");
    p.style.setProperty("font-family", "system-ui, sans-serif");
    mount.appendChild(p);
    return;
  }

  let sessionToken = _loadCachedSession(config.key);
  let requiresCaptcha = true;
  if (!sessionToken) {
    try {
      const resp = await initSession(config.key, config.host);
      sessionToken = resp.session_token;
      requiresCaptcha = resp.requires_captcha;
      _storeCachedSession(config.key, sessionToken);
    } catch (err) {
      // Fall through to a soft error — mint an ephemeral session
      // token so the widget at least renders. First message will
      // fail with 401 if the backend is truly down.
      // eslint-disable-next-line no-console
      console.warn("[CRM chat] session/init failed, using ephemeral token", err);
      sessionToken = `pub-fallback-${Math.random().toString(36).slice(2, 12)}`;
    }
  } else {
    // Reloaded session — first message still requires CAPTCHA if the
    // 5-min server-side cache has expired. Safe default: challenge.
    requiresCaptcha = true;
  }

  const { bodyEl, inputEl, sendBtn, captchaSlot } = renderChat(
    mount,
    meta,
    requiresCaptcha,
  );
  const captchaTokenGetter = requiresCaptcha
    ? bootstrapTurnstile(captchaSlot)
    : () => null;

  const ctx: ChatContext = {
    config,
    meta,
    sessionToken,
    requiresCaptcha,
    mount,
    bodyEl,
    inputEl,
    sendBtn,
    captchaTokenGetter,
  };

  const doSend = async () => {
    const msg = inputEl.value.trim();
    if (!msg || sendBtn.disabled) return;
    inputEl.value = "";
    sendBtn.disabled = true;
    try {
      await sendTurn(ctx, msg);
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  };

  sendBtn.addEventListener("click", () => void doSend());
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void doSend();
    }
  });
}

export const _internal = { safeMarkdownToHtml };
