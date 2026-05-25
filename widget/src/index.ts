/**
 * FurniCRM embeddable widget — entry point.
 *
 * Step 5 ships a placeholder `init()` that proves the bundle loads
 * + finds its mount div. Step 6 replaces the body with the real
 * form renderer + submission flow.
 *
 * The bundle is served at `<host>/v1/widget.js` and consumed by a
 * `<script type="module" src="…">` tag on customer websites. Step 6
 * adds a loader that auto-runs `init()` from `<script data-key="…">`
 * attributes so customers don't have to write any JS themselves.
 */
import type { InitConfig } from "./types";

export type { InitConfig, WidgetConfig, WidgetField } from "./types";

export function init(config: InitConfig): void {
  if (!config || !config.key || !config.host || !config.mountId) {
    console.warn(
      "[FurniCRM] init() called with incomplete config",
      config,
    );
    return;
  }
  console.log("[FurniCRM] widget loaded", config);

  const mount = document.getElementById(config.mountId);
  if (!mount) {
    console.warn(
      `[FurniCRM] mount #${config.mountId} not found in DOM`,
    );
    return;
  }
  // Step 5 placeholder. Step 6's renderer replaces this with the
  // actual form DOM tree built from the org's widget config.
  mount.textContent =
    "FurniCRM widget — Step 5 placeholder (form renderer ships in Step 6).";
}
