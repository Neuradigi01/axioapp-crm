/**
 * Lazy reCAPTCHA v3 client.
 *
 * The widget loads `https://www.google.com/recaptcha/api.js` on
 * demand — never at page load — so the host site pays no perf cost
 * for orgs that haven't enabled reCAPTCHA, and orgs that have enabled
 * it pay only when a visitor actually interacts with the form.
 *
 * Three exported helpers:
 *
 *   - `warmRecaptcha(siteKey)`  — eager preload triggered on first
 *     form focus. The grecaptcha API ships its own state machine
 *     (`grecaptcha.ready(...)`), so the warm-up just ensures the
 *     script + ready callback have resolved before submit time.
 *   - `getToken(siteKey, action)` — issues a fresh token. Returns
 *     null on any failure (script load error, grecaptcha throws,
 *     network blip). The orchestrator passes null through to the
 *     backend, which silent-drops with `reason: "recaptcha_invalid"`.
 *   - `resetForTests()` — wipes the cached state so tests run in
 *     isolation.
 *
 * **Idempotency:** loading the script twice would inject two
 * `<script>` tags and double-bind `grecaptcha.ready`. The module-
 * level `scriptPromise` ensures every caller awaits the same load.
 */

type Grecaptcha = {
  ready: (cb: () => void) => void;
  execute: (siteKey: string, opts: { action: string }) => Promise<string>;
};

declare global {
  interface Window {
    grecaptcha?: Grecaptcha;
  }
}


const SCRIPT_BASE_URL = "https://www.google.com/recaptcha/api.js";

let scriptPromise: Promise<void> | null = null;


/**
 * Inject the grecaptcha script tag and wait for `grecaptcha.ready`
 * to fire. Safe to call repeatedly — second + subsequent calls
 * await the same in-flight promise.
 */
function loadScript(siteKey: string): Promise<void> {
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src^="${SCRIPT_BASE_URL}"]`,
    );
    if (existing && window.grecaptcha) {
      // Script already on the page (another widget instance or the
      // host site loaded it). Skip re-injection; just wait for ready.
      window.grecaptcha.ready(() => resolve());
      return;
    }

    const tag = document.createElement("script");
    tag.src = `${SCRIPT_BASE_URL}?render=${encodeURIComponent(siteKey)}`;
    tag.async = true;
    tag.defer = true;
    tag.onload = () => {
      if (!window.grecaptcha) {
        reject(new Error("grecaptcha not present after script load"));
        return;
      }
      window.grecaptcha.ready(() => resolve());
    };
    tag.onerror = () => reject(new Error("recaptcha script load failed"));
    document.head.appendChild(tag);
  });

  // Reset the promise on failure so a later submit can retry the load.
  scriptPromise.catch(() => {
    scriptPromise = null;
  });

  return scriptPromise;
}


/**
 * Eagerly pre-warm reCAPTCHA on first user interaction. Awaiting this
 * in the orchestrator's focus handler is optional — `getToken` will
 * load on demand too — but warming up shaves the script-fetch latency
 * off the submit click.
 */
export async function warmRecaptcha(siteKey: string): Promise<void> {
  try {
    await loadScript(siteKey);
  } catch {
    /* Swallowed — getToken will surface the failure as a null token. */
  }
}


/**
 * Issue a fresh reCAPTCHA token for `action`. Returns null on any
 * failure (script unreachable, grecaptcha throws, the host page's
 * CSP forbids loading Google's script). The backend treats both
 * "missing token" and "invalid token" identically, so null is the
 * caller-visible signal for either failure.
 */
export async function getToken(
  siteKey: string,
  action: string,
): Promise<string | null> {
  try {
    await loadScript(siteKey);
    if (!window.grecaptcha) return null;
    return await window.grecaptcha.execute(siteKey, { action });
  } catch {
    return null;
  }
}


/** Test-only — drops the cached load promise + global so each test
 * starts with a clean slate. */
export function resetForTests(): void {
  scriptPromise = null;
  if (typeof window !== "undefined") {
    delete window.grecaptcha;
  }
  if (typeof document !== "undefined") {
    document
      .querySelectorAll(`script[src^="${SCRIPT_BASE_URL}"]`)
      .forEach((tag) => tag.remove());
  }
}
