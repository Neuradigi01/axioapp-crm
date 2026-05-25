/**
 * Shared widget types. Mirror the backend's public-config schema so
 * the renderer in Step 6 can render the form straight off whatever
 * `GET /api/v1/embed/config/public?key=…` returns.
 *
 * Keep this file dependency-free — it's imported by every other
 * widget source file and changing its shape ripples broadly.
 */

export type WidgetFieldKey =
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
  | "select";

export interface WidgetField {
  key: WidgetFieldKey;
  label: string;
  placeholder?: string | null;
  required: boolean;
  order: number;
  field_type: WidgetFieldType;
  options?: string[] | null;
}

export interface WidgetBranding {
  logo_url: string | null;
  accent_color: string;
  show_powered_by: boolean;
}

export interface WidgetConfig {
  fields: WidgetField[];
  submit_button_label: string;
  thank_you_message: string;
  thank_you_url: string | null;
  branding: WidgetBranding;
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
