/**
 * Auto-init from `<script>` data attributes.
 *
 * Customer install snippet:
 *
 *   <div id="crm-form"></div>
 *   <script src="https://crm-api.neuradigi.com/widget/v1/widget.js"
 *           data-key="pk_live_…"
 *           data-host="https://crm-api.neuradigi.com"
 *           data-mount="crm-form"></script>
 *
 * `data-mount` defaults to `"crm-form"` and `data-host` to the
 * production API URL, so the minimum-viable snippet is the first two
 * lines (no `data-host`, no `data-mount`).
 *
 * Auto-init happens at module-evaluation time so customers don't
 * have to wire up any JS themselves. The renderer waits for `mount`
 * to exist; if the `<script>` is placed BEFORE the `<div>` in the
 * DOM, we defer to `DOMContentLoaded`.
 */
import { init } from "./index";

// Re-export so manual (non-snippet) callers can still
// `import { init } from "/v1/widget.js"`.
export { init };
export { ApiError } from "./api";
export type {
  Attribution,
  InitConfig,
  SubmissionPayload,
  SubmitResult,
  WidgetConfig,
  WidgetField,
} from "./types";

const DEFAULT_HOST = "https://crm-api.neuradigi.com";
const DEFAULT_MOUNT = "crm-form";


function getScriptTag(): HTMLScriptElement | null {
  // `document.currentScript` works for non-async, non-defer scripts —
  // which is the install-snippet contract. Falls back to a query so
  // the loader still works if customers add `async` against guidance.
  const current = document.currentScript as HTMLScriptElement | null;
  if (current && current.src.includes("widget.js")) return current;
  return document.querySelector<HTMLScriptElement>(
    'script[src*="widget.js"]',
  );
}


function autoInit(): void {
  const script = getScriptTag();
  if (!script) {
    // Manual-init path (no script tag found, e.g. consumer imports
    // the ES module and calls `init()` themselves). Nothing to do.
    return;
  }
  const key = script.getAttribute("data-key");
  if (!key) {
    console.warn(
      "[FurniCRM] <script> tag is missing the required data-key attribute.",
    );
    return;
  }
  const mountId = script.getAttribute("data-mount") || DEFAULT_MOUNT;
  const host = script.getAttribute("data-host") || DEFAULT_HOST;

  const mountExists = document.getElementById(mountId) !== null;
  if (mountExists) {
    init({ key, host, mountId });
    return;
  }
  // Mount div not in the DOM yet — script tag rendered before the
  // <div>. Wait for parse to finish, then init.
  document.addEventListener(
    "DOMContentLoaded",
    () => init({ key, host, mountId }),
    { once: true },
  );
}


autoInit();
