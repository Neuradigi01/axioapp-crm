/**
 * FurniCRM embeddable widget — orchestrator.
 *
 * `init(config)` is the single externally-meaningful entry. Customers
 * never call this directly — `loader.ts` discovers `<script data-key>`
 * tags and invokes it for them. The named export stays for manual
 * (non-snippet) integrations and for tests.
 *
 * Flow on init:
 *
 *   1. Render a loading state into the mount div.
 *   2. Fetch the org's widget config via `/embed/config/public`.
 *      Fall back to a baked-in default config if the fetch fails so
 *      the form still renders during a backend blip.
 *   3. Render the form, wire the submit handler.
 *   4. On submit: validate (handled by renderer) → POST → success
 *      state or error banner.
 *   5. Attribution captured ONCE at render time; included with every
 *      submission for the lifetime of this render.
 */
import { ApiError, getConfig, submitLead } from "./api";
import { captureAttribution } from "./attribution";
import {
  renderError,
  renderForm,
  renderLoading,
  renderSuccessState,
  type RenderedForm,
} from "./renderer";
import { getToken, warmRecaptcha } from "./spam";
import { injectStyles } from "./styles";
import type { InitConfig, SubmissionPayload, WidgetConfig } from "./types";

export type {
  Attribution,
  InitConfig,
  SubmissionPayload,
  SubmitResult,
  WidgetConfig,
  WidgetField,
} from "./types";
export { ApiError } from "./api";


/**
 * Frozen default config — used when `/embed/config/public` fetch
 * fails (network blip, key revoked between page load and submission,
 * etc.). Kept intentionally simple: name + phone required, email
 * optional. The backend's `_default_document()` is the source of
 * truth for fresh orgs; this constant ONLY runs on the fetch-error
 * path so drift between them surfaces as "widget looks slightly
 * different when backend is down" — acceptable.
 */
const FALLBACK_CONFIG: WidgetConfig = {
  fields: [
    { key: "full_name", label: "Your name", placeholder: "Asha Reddy", required: true, order: 0, field_type: "text", field_source: "standard", entity: "contact" },
    { key: "phone", label: "Phone", placeholder: "+91 …", required: true, order: 1, field_type: "tel", field_source: "standard", entity: "contact" },
    { key: "email", label: "Email", placeholder: "you@…", required: false, order: 2, field_type: "email", field_source: "standard", entity: "contact" },
    { key: "notes", label: "Tell us more", placeholder: "Anything we should know?", required: false, order: 3, field_type: "textarea", field_source: "standard", entity: "contact" },
  ],
  submit_button_label: "Get a quote",
  thank_you_message: "Thanks — we'll reach out shortly.",
  thank_you_url: null,
  branding: {
    logo_url: null,
    accent_color: "#4F46E5",
    show_powered_by: true,
  },
  spam_protection: {
    recaptcha_enabled: false,
    recaptcha_site_key: null,
    min_fill_time_ms: 2000,
  },
};


export async function init(config: InitConfig): Promise<void> {
  if (!config || !config.key || !config.host || !config.mountId) {
    console.warn("[FurniCRM] init() called with incomplete config", config);
    return;
  }
  const mount = document.getElementById(config.mountId);
  if (!mount) {
    console.warn(
      `[FurniCRM] mount #${config.mountId} not found in DOM`,
    );
    return;
  }

  // Inject the base stylesheet on first init (idempotent across
  // multiple widget instances on the same page).
  injectStyles();

  renderLoading(mount);
  const attribution = captureAttribution();

  let widgetConfig: WidgetConfig;
  try {
    widgetConfig = await getConfig(config.key, config.host);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // Bad / revoked key — the widget shouldn't render. Show a
      // dev-friendly error in the mount so the integrator can fix
      // the snippet. Real visitors should never see this.
      renderError(
        mount,
        "This form is not active. Please contact the site owner.",
      );
      return;
    }
    console.warn(
      "[FurniCRM] config fetch failed, falling back to defaults",
      err,
    );
    widgetConfig = FALLBACK_CONFIG;
  }

  const recaptchaSiteKey =
    widgetConfig.spam_protection?.recaptcha_enabled &&
    widgetConfig.spam_protection.recaptcha_site_key
      ? widgetConfig.spam_protection.recaptcha_site_key
      : null;

  let handle: RenderedForm | null = null;

  const onSubmit = async (payload: SubmissionPayload): Promise<void> => {
    if (!handle) return;
    handle.setSubmitting(true);

    // Mint a fresh reCAPTCHA token on every submit — v3 tokens are
    // single-use + short-lived (2 min). Null on failure means we send
    // the payload without a token; the backend silent-drops it.
    if (recaptchaSiteKey) {
      payload.recaptcha_token = await getToken(recaptchaSiteKey, "submit");
    }

    try {
      await submitLead(config.key, config.host, payload);
      // Success — wipe the form, paint the thank-you.
      renderSuccessState(mount, widgetConfig);
    } catch (err) {
      handle.setSubmitting(false);
      if (err instanceof ApiError) {
        handle.showError(err.detail);
      } else {
        handle.showError(
          "Could not submit right now. Please try again in a moment.",
        );
      }
    }
  };

  handle = renderForm(mount, widgetConfig, onSubmit, attribution);

  // Per-org branding override: set `--fc-primary` inline on the
  // rendered `.furnicrm-form` container. Host-CSS variable overrides
  // still win (higher specificity via `#furnicrm-form` selector or
  // explicit declaration), but with no host CSS, the org's
  // `accent_color` from Settings → Embed Widget kicks in immediately.
  const formRoot = mount.querySelector<HTMLElement>(".furnicrm-form");
  if (formRoot && widgetConfig.branding.accent_color) {
    formRoot.style.setProperty(
      "--fc-primary",
      widgetConfig.branding.accent_color,
    );
  }

  // Pre-warm reCAPTCHA on first interaction. Loading the script lazily
  // (rather than on page load) means the host site pays zero perf cost
  // until a visitor actually engages with the form. By the time they
  // hit Submit, the script + ready callback have resolved, so the
  // token mint is sub-100ms instead of waiting on a fresh script fetch.
  if (recaptchaSiteKey) {
    const formEl = mount.querySelector<HTMLFormElement>("form");
    formEl?.addEventListener(
      "focusin",
      () => void warmRecaptcha(recaptchaSiteKey),
      { once: true },
    );
  }
}
