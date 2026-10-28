/**
 * Capture marketing attribution from the visitor's browser context.
 *
 * Called once at render time; the result rides with every submission
 * for the lifetime of the rendered widget. Refreshing the page or
 * navigating to a new URL with different UTMs produces a fresh
 * capture on the next render.
 *
 * All fields are optional in the result — direct traffic with no
 * UTMs has nothing to capture, which is fine: the backend stores
 * the partial JSON unchanged and reporting groups them as "direct".
 */
import type { Attribution } from "./types";

export function captureAttribution(): Attribution {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const href = typeof window === "undefined" ? null : window.location.href;
  const referrer =
    typeof document === "undefined" ? null : document.referrer || null;

  const params = new URLSearchParams(search);
  return {
    referrer,
    landing_url: href,
    utm_source: params.get("utm_source"),
    utm_medium: params.get("utm_medium"),
    utm_campaign: params.get("utm_campaign"),
    utm_content: params.get("utm_content"),
    utm_term: params.get("utm_term"),
  };
}
