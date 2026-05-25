/**
 * Form renderer — builds the widget's DOM tree from the org's
 * `WidgetConfig`. Three top-level exports:
 *
 *   - `renderForm(mount, config, onSubmit)` — initial render.
 *     Returns a `RenderedForm` handle the orchestrator uses to
 *     mark fields invalid + clear errors.
 *   - `renderSuccessState(mount, config)` — replaces the form
 *     with the thank-you message after a successful submission.
 *   - `renderError(mount, message)` — replaces the form with a
 *     generic error banner (used when even fetching the config
 *     fell over and the fallback path also failed).
 *
 * **XSS posture:** every visible string (labels, options, error
 * messages) is written via `textContent` or via `setAttribute` on
 * known-safe attributes (`name`, `id`, `placeholder`, `value`,
 * `aria-*`). `innerHTML` is NEVER used. The config payload comes
 * from our own backend, but defence-in-depth — a compromised
 * backend should not be able to XSS visitor browsers.
 *
 * Styles are deliberately minimal in this step. Step 7 ships
 * inline CSS + CSS-variable theming. Renderer emits semantic
 * `furnicrm-form__*` classes that Step 7's stylesheet hooks into.
 */
import type {
  Attribution,
  SubmissionPayload,
  WidgetConfig,
  WidgetField,
} from "./types";

/** Handle the orchestrator uses to interact with a rendered form. */
export interface RenderedForm {
  /** Mark these field keys invalid (red border + aria-invalid). */
  markInvalid(fieldKeys: string[]): void;
  /** Clear all field-level error state. */
  clearErrors(): void;
  /** Show a banner above the form (e.g. server-side error). */
  showError(message: string): void;
  /** Disable the submit button + show a "Submitting…" label. */
  setSubmitting(submitting: boolean): void;
}

/**
 * Submit-handler shape. The orchestrator passes one in; the
 * renderer invokes it with the collected payload after passing
 * client-side validation (required, email, phone length).
 */
export type SubmitHandler = (
  payload: SubmissionPayload,
) => Promise<void> | void;


// --- Public API ------------------------------------------------------


export function renderForm(
  mount: HTMLElement,
  config: WidgetConfig,
  onSubmit: SubmitHandler,
  attribution: Attribution,
): RenderedForm {
  clearChildren(mount);

  const root = document.createElement("div");
  root.className = "furnicrm-form";
  root.setAttribute("role", "form");

  const errorBanner = document.createElement("div");
  errorBanner.className = "furnicrm-form__error-banner";
  errorBanner.setAttribute("role", "alert");
  errorBanner.style.display = "none";
  root.appendChild(errorBanner);

  const form = document.createElement("form");
  form.className = "furnicrm-form__form";
  form.setAttribute("novalidate", "");

  const fieldElements = new Map<string, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>();
  const wrapperElements = new Map<string, HTMLElement>();

  const orderedFields = [...config.fields].sort((a, b) => a.order - b.order);
  for (const field of orderedFields) {
    const wrapper = buildFieldWrapper(field);
    form.appendChild(wrapper.wrapper);
    fieldElements.set(field.key, wrapper.input);
    wrapperElements.set(field.key, wrapper.wrapper);
  }

  // Honeypot — invisible to legit humans, irresistible to bots.
  // Step 8's backend rule silently drops submissions where this
  // arrives non-empty. Rendering it here is harmless until then.
  const honeypot = document.createElement("input");
  honeypot.type = "text";
  honeypot.name = "honeypot";
  honeypot.tabIndex = -1;
  honeypot.autocomplete = "off";
  honeypot.setAttribute("aria-hidden", "true");
  honeypot.style.cssText =
    "position:absolute;left:-9999px;width:1px;height:1px;opacity:0;";
  form.appendChild(honeypot);

  // Submit button
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "furnicrm-form__button";
  submit.textContent = config.submit_button_label;
  form.appendChild(submit);

  // Powered-by footer (when enabled)
  if (config.branding.show_powered_by) {
    const footer = document.createElement("div");
    footer.className = "furnicrm-form__powered-by";
    footer.textContent = "Powered by FurniCRM";
    form.appendChild(footer);
  }

  root.appendChild(form);
  mount.appendChild(root);

  const renderedAt = new Date().toISOString();

  // --- Submit handler -----------------------------------------------
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    handle.clearErrors();

    const values = collectValues(fieldElements);
    const invalid = validate(orderedFields, values);
    if (invalid.length > 0) {
      handle.markInvalid(invalid);
      return;
    }

    const payload: SubmissionPayload = {
      full_name: (values["full_name"] ?? "").trim(),
      phone: optString(values["phone"]),
      email: optString(values["email"]),
      interest: optString(values["interest"]),
      notes: optString(values["notes"]),
      honeypot: honeypot.value,
      rendered_at: renderedAt,
      attribution,
    };

    const result = onSubmit(payload);
    if (result instanceof Promise) {
      result.catch(() => {
        /* Orchestrator surfaces errors via handle.showError(); swallow here. */
      });
    }
  });

  const handle: RenderedForm = {
    markInvalid(fieldKeys: string[]): void {
      for (const key of fieldKeys) {
        const input = fieldElements.get(key);
        const wrapper = wrapperElements.get(key);
        if (input) input.setAttribute("aria-invalid", "true");
        if (wrapper) wrapper.classList.add("furnicrm-form__field--invalid");
      }
    },
    clearErrors(): void {
      errorBanner.textContent = "";
      errorBanner.style.display = "none";
      for (const input of fieldElements.values()) {
        input.removeAttribute("aria-invalid");
      }
      for (const wrapper of wrapperElements.values()) {
        wrapper.classList.remove("furnicrm-form__field--invalid");
      }
    },
    showError(message: string): void {
      errorBanner.textContent = message;
      errorBanner.style.display = "";
    },
    setSubmitting(submitting: boolean): void {
      submit.disabled = submitting;
      submit.textContent = submitting
        ? "Submitting…"
        : config.submit_button_label;
    },
  };

  return handle;
}


export function renderSuccessState(
  mount: HTMLElement,
  config: WidgetConfig,
): void {
  clearChildren(mount);
  const root = document.createElement("div");
  root.className = "furnicrm-form furnicrm-form--success";
  root.setAttribute("role", "status");

  const icon = document.createElement("div");
  icon.className = "furnicrm-form__success-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "✓";
  root.appendChild(icon);

  const message = document.createElement("p");
  message.className = "furnicrm-form__success-message";
  message.textContent = config.thank_you_message;
  root.appendChild(message);

  mount.appendChild(root);

  if (config.thank_you_url) {
    // Honour the org's configured thank-you redirect after a short
    // moment so visitors still see the success state briefly.
    window.setTimeout(() => {
      window.location.assign(config.thank_you_url as string);
    }, 1200);
  }
}


export function renderError(mount: HTMLElement, message: string): void {
  clearChildren(mount);
  const root = document.createElement("div");
  root.className = "furnicrm-form furnicrm-form--error";
  root.setAttribute("role", "alert");
  root.textContent = message;
  mount.appendChild(root);
}


export function renderLoading(mount: HTMLElement): void {
  clearChildren(mount);
  const root = document.createElement("div");
  root.className = "furnicrm-form furnicrm-form--loading";
  root.setAttribute("aria-busy", "true");
  root.textContent = "Loading…";
  mount.appendChild(root);
}


// --- Internals -------------------------------------------------------


function clearChildren(node: HTMLElement): void {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}


interface FieldWrapper {
  wrapper: HTMLElement;
  input: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
}


function buildFieldWrapper(field: WidgetField): FieldWrapper {
  const wrapper = document.createElement("div");
  wrapper.className = "furnicrm-form__field";
  wrapper.setAttribute("data-field-key", field.key);

  const id = `furnicrm-${field.key}`;
  const label = document.createElement("label");
  label.className = "furnicrm-form__label";
  label.setAttribute("for", id);
  label.textContent = field.label + (field.required ? " *" : "");
  wrapper.appendChild(label);

  const input = buildInput(field, id);
  wrapper.appendChild(input);

  return { wrapper, input };
}


function buildInput(
  field: WidgetField,
  id: string,
): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement {
  if (field.field_type === "textarea") {
    const el = document.createElement("textarea");
    el.id = id;
    el.name = field.key;
    el.className = "furnicrm-form__input furnicrm-form__textarea";
    el.rows = 3;
    if (field.placeholder) el.placeholder = field.placeholder;
    if (field.required) el.required = true;
    return el;
  }
  if (field.field_type === "select") {
    const el = document.createElement("select");
    el.id = id;
    el.name = field.key;
    el.className = "furnicrm-form__input furnicrm-form__select";
    if (field.required) el.required = true;
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = field.placeholder || "Choose…";
    el.appendChild(empty);
    for (const opt of field.options ?? []) {
      const option = document.createElement("option");
      option.value = opt;
      option.textContent = opt;
      el.appendChild(option);
    }
    return el;
  }
  const el = document.createElement("input");
  el.id = id;
  el.name = field.key;
  el.className = "furnicrm-form__input";
  el.type = htmlInputType(field.field_type);
  if (field.placeholder) el.placeholder = field.placeholder;
  if (field.required) el.required = true;
  return el;
}


function htmlInputType(t: WidgetField["field_type"]): string {
  switch (t) {
    case "email":
      return "email";
    case "tel":
      return "tel";
    default:
      return "text";
  }
}


function collectValues(
  fieldElements: Map<string, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, el] of fieldElements.entries()) {
    out[key] = (el.value ?? "").trim();
  }
  return out;
}


/**
 * Client-side validation. Mirrors the backend's rules so visitors
 * see immediate feedback rather than a round-trip. The backend
 * still re-validates — never trust the client.
 *
 * Returns the list of field keys that failed.
 */
function validate(
  fields: WidgetField[],
  values: Record<string, string>,
): string[] {
  const invalid: string[] = [];
  for (const field of fields) {
    const value = values[field.key] ?? "";
    if (field.required && !value) {
      invalid.push(field.key);
      continue;
    }
    if (!value) continue;
    if (field.field_type === "email" && !isLikelyEmail(value)) {
      invalid.push(field.key);
      continue;
    }
    if (field.field_type === "tel" && !isLikelyPhone(value)) {
      invalid.push(field.key);
      continue;
    }
  }
  return invalid;
}


function isLikelyEmail(v: string): boolean {
  // RFC 5322 is too much for v1. Catch the obvious mistakes:
  // exactly one @, dot in the host part, no whitespace.
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);
}


function isLikelyPhone(v: string): boolean {
  // Strip non-digits and require at least 7 — covers the shortest
  // valid international number formats without rejecting legit
  // Indian mobile / landline patterns.
  const digits = v.replace(/\D/g, "");
  return digits.length >= 7;
}


function optString(v: string | undefined): string | null {
  if (v === undefined) return null;
  const trimmed = v.trim();
  return trimmed || null;
}
