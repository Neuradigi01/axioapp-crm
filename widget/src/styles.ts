/**
 * Inline base stylesheet for the widget.
 *
 * Kept as a TypeScript template literal (rather than a separate
 * `.css` file imported via `?raw`) so the bundler and the test
 * runner agree on the value: vitest's CSS handler intercepts
 * `*.css` imports before the `?raw` query is honoured, leaving the
 * stylesheet empty at test time. Inlining sidesteps that mismatch.
 *
 * Visual conventions:
 *   1. CSS variables (the `--fc-*` contract) declared on
 *      `.furnicrm-form` carry every visual concern. Host sites
 *      override one, keep the rest — variables cascade down.
 *   2. Low-specificity single-class selectors (no `body` ancestor,
 *      no `!important`) so host class-name overrides win without
 *      specificity tricks.
 *   3. Per-org `branding.accent_color` is applied inline at render
 *      time via `style="--fc-primary: …"` on `.furnicrm-form`, so
 *      the org accent kicks in even before host CSS loads. Host
 *      variable overrides on an ancestor still win because they're
 *      more specific.
 *
 * `injectStyles()` appends a single `<style data-furnicrm>` tag to
 * `<head>` the first time it's called; subsequent calls are no-ops
 * (idempotent — multiple widgets on the same page must not
 * duplicate the stylesheet).
 */
const CSS = `
.furnicrm-form {
  --fc-primary: #4F46E5;
  --fc-primary-contrast: #ffffff;
  --fc-bg: transparent;
  --fc-text: #111827;
  --fc-muted: #6b7280;
  --fc-border: #d1d5db;
  --fc-border-focus: var(--fc-primary);
  --fc-error: #dc2626;
  --fc-radius: 6px;
  --fc-spacing: 12px;
  --fc-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --fc-font-size: 15px;

  display: flex;
  flex-direction: column;
  gap: var(--fc-spacing);
  font-family: var(--fc-font);
  font-size: var(--fc-font-size);
  color: var(--fc-text);
  background: var(--fc-bg);
  line-height: 1.4;
}
.furnicrm-form__form {
  display: flex;
  flex-direction: column;
  gap: var(--fc-spacing);
}
.furnicrm-form__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.furnicrm-form__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--fc-text);
}
.furnicrm-form__input {
  padding: 8px 10px;
  border: 1px solid var(--fc-border);
  border-radius: var(--fc-radius);
  font: inherit;
  color: inherit;
  background: #ffffff;
  outline: none;
  width: 100%;
  box-sizing: border-box;
}
.furnicrm-form__input::placeholder {
  color: var(--fc-muted);
}
.furnicrm-form__input:focus {
  border-color: var(--fc-border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--fc-primary) 18%, transparent);
}
.furnicrm-form__textarea {
  resize: vertical;
  min-height: 70px;
}
.furnicrm-form__field--invalid .furnicrm-form__input {
  border-color: var(--fc-error);
}
.furnicrm-form__field--invalid .furnicrm-form__input:focus {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--fc-error) 18%, transparent);
}
.furnicrm-form__error {
  color: var(--fc-error);
  font-size: 13px;
}
.furnicrm-form__error-banner {
  padding: 8px 12px;
  border-radius: var(--fc-radius);
  background: color-mix(in srgb, var(--fc-error) 8%, transparent);
  color: var(--fc-error);
  font-size: 13px;
}
.furnicrm-form__button {
  padding: 10px 16px;
  border: 0;
  border-radius: var(--fc-radius);
  background: var(--fc-primary);
  color: var(--fc-primary-contrast);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s;
}
.furnicrm-form__button:hover:not(:disabled) {
  filter: brightness(0.92);
}
.furnicrm-form__button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.furnicrm-form__powered-by {
  font-size: 12px;
  color: var(--fc-muted);
  text-align: right;
  margin-top: 4px;
}
.furnicrm-form--loading {
  color: var(--fc-muted);
  font-style: italic;
  padding: 16px 0;
}
.furnicrm-form--success {
  text-align: center;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
}
.furnicrm-form__success-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--fc-primary) 14%, transparent);
  color: var(--fc-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
}
.furnicrm-form__success-message {
  margin: 0;
  color: var(--fc-text);
}
.furnicrm-form--error {
  padding: 12px;
  border-radius: var(--fc-radius);
  background: color-mix(in srgb, var(--fc-error) 8%, transparent);
  color: var(--fc-error);
  font-size: 14px;
}
`;

const TAG_MARKER = "data-furnicrm";

export function injectStyles(): void {
  if (typeof document === "undefined") return;
  if (document.querySelector(`style[${TAG_MARKER}]`)) return;
  const tag = document.createElement("style");
  tag.setAttribute(TAG_MARKER, "");
  tag.textContent = CSS;
  document.head.appendChild(tag);
}

export function getStyles(): string {
  return CSS;
}
