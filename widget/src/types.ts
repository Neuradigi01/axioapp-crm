/**
 * Shared widget types. Mirror the backend's public-config schema so
 * the renderer in Step 6 can render the form straight off whatever
 * `GET /api/v1/embed/config/public?key=…` returns.
 *
 * Keep this file dependency-free — it's imported by every other
 * widget source file and changing its shape ripples broadly.
 */

/**
 * Standard field keys — the 5 baked-in fields that always route into
 * their own top-level slot on the submission payload. Custom-source
 * fields use arbitrary string keys and route into `custom_data`.
 */
export type WidgetStandardFieldKey =
  | "full_name"
  | "phone"
  | "email"
  | "interest"
  | "notes";

export type WidgetFieldType =
  | "text"
  | "email"
  | "tel"
  | "textarea"
  | "select"
  | "number"
  | "date";

/**
 * Where a field's value gets routed at submission time:
 *   - "standard": one of the 5 baked-in keys → top-level payload slot
 *     (full_name / phone / email / interest / notes).
 *   - "custom":   free-form key → `payload.custom_data[key]` → contact's
 *     custom_data JSONB. The Owner opts these in via Settings.
 */
export type WidgetFieldSource = "standard" | "custom";

export interface WidgetField {
  key: string;
  label: string;
  placeholder?: string | null;
  required: boolean;
  order: number;
  field_type: WidgetFieldType;
  options?: string[] | null;
  field_source: WidgetFieldSource;
}

export interface WidgetBranding {
  logo_url: string | null;
  accent_color: string;
  show_powered_by: boolean;
}

/**
 * Public projection of the org's spam-protection settings. The
 * `recaptcha_secret_key` lives server-side ONLY and never appears
 * here — this is what reaches the visitor's browser.
 */
export interface WidgetSpamProtection {
  recaptcha_enabled: boolean;
  recaptcha_site_key: string | null;
  min_fill_time_ms: number;
}

export interface WidgetConfig {
  fields: WidgetField[];
  submit_button_label: string;
  thank_you_message: string;
  thank_you_url: string | null;
  branding: WidgetBranding;
  spam_protection: WidgetSpamProtection;
}

/**
 * Configuration passed into `init()`. The loader (Step 6) builds
 * this from `<script>` data attributes; manual `init()` callers
 * supply it directly.
 *
 * - `key`: the customer's `pk_live_…` embed key.
 * - `host`: backend API base URL (e.g. `https://api.furnicrm.app`).
 * - `mountId`: id of the `<div>` the form renders into.
 */
export interface InitConfig {
  key: string;
  host: string;
  mountId: string;
}

/**
 * Captured at render time, sent with every submission. All fields
 * optional — visitors arriving via direct traffic have nothing to
 * capture. Mirrors the backend's `SubmissionAttribution` Pydantic
 * shape exactly.
 */
export interface Attribution {
  referrer: string | null;
  landing_url: string | null;
  utm_source: string | null;
  utm_medium: string | null;
  utm_campaign: string | null;
  utm_content: string | null;
  utm_term: string | null;
}

/**
 * The POST body the widget sends to `/api/v1/embed/leads`.
 * `full_name` is the only required string at the schema level
 * (the backend's Pydantic enforces it). Everything else is gated
 * by the org's widget config — the renderer enforces required
 * fields client-side too so the visitor gets immediate feedback.
 * `honeypot` is empty for legit humans; bots fill every field
 * including hidden ones, which Step 8's backend rule traps.
 * `rendered_at` is set when the form was first painted — Step 8
 * uses it for a min-fill-time spam check.
 */
export interface SubmissionPayload {
  full_name: string;
  phone?: string | null;
  email?: string | null;
  interest?: string | null;
  notes?: string | null;
  honeypot?: string;
  rendered_at?: string;
  /**
   * Google reCAPTCHA v3 token. Populated by the orchestrator
   * (via spam.ts → grecaptcha.execute) when the org's widget
   * config has `recaptcha_enabled=true`. Absent on submissions
   * from orgs that haven't enabled reCAPTCHA.
   */
  recaptcha_token?: string | null;
  /**
   * Org-defined custom field values keyed by the custom field's
   * `field_key`. Routed into the contact's `custom_data` JSONB
   * server-side. Empty `{}` when no custom fields are opted in
   * to the widget.
   */
  custom_data?: Record<string, string>;
  attribution: Attribution;
}

/**
 * Response shape from `/api/v1/embed/leads`. `lead_id` is null on
 * silent-drop cases (honeypot triggered, future spam gates). The
 * widget treats `ok=true` as success regardless of whether a lead
 * actually landed — bots learn nothing.
 */
export interface SubmitResult {
  ok: boolean;
  lead_id: string | null;
  thank_you_url: string | null;
}
