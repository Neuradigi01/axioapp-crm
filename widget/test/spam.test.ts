/**
 * Tests for the lazy reCAPTCHA client.
 *
 * We don't actually load Google's script — jsdom can't run it and we
 * don't want the test suite to hit the network. Instead we stub
 * `document.head.appendChild` to capture the injected `<script>` tag,
 * then synthesise its `onload` event and seed `window.grecaptcha`
 * with a fake of the v3 surface we use (`ready`, `execute`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, resetForTests, warmRecaptcha } from "../src/spam";


function installGrecaptchaStub(token: string = "fake-token"): void {
  (window as unknown as { grecaptcha: unknown }).grecaptcha = {
    ready: (cb: () => void) => cb(),
    execute: vi.fn().mockResolvedValue(token),
  };
}


/**
 * Replace `document.head.appendChild` with a hook that, when a
 * `<script>` is added, immediately fires its `onload` callback —
 * simulating the script loading instantly. The original appendChild
 * is restored after each test.
 */
function autoFireScriptOnload(): () => void {
  const real = document.head.appendChild.bind(document.head);
  const spy = vi
    .spyOn(document.head, "appendChild")
    .mockImplementation((node) => {
      const out = real(node);
      if ((node as HTMLElement).tagName === "SCRIPT") {
        // Defer to a microtask so the awaiter is parked first.
        queueMicrotask(() => (node as HTMLScriptElement).onload?.(new Event("load")));
      }
      return out;
    });
  return () => spy.mockRestore();
}


describe("spam.ts", () => {
  let restoreAppend: () => void;

  beforeEach(() => {
    resetForTests();
    restoreAppend = autoFireScriptOnload();
  });

  afterEach(() => {
    restoreAppend();
    resetForTests();
  });

  it("warmRecaptcha injects the script tag exactly once", async () => {
    installGrecaptchaStub();
    await warmRecaptcha("6Lc-site");
    await warmRecaptcha("6Lc-site");
    await warmRecaptcha("6Lc-site");

    const scripts = document.head.querySelectorAll(
      'script[src^="https://www.google.com/recaptcha/api.js"]',
    );
    expect(scripts.length).toBe(1);
    expect(scripts[0].getAttribute("src")).toContain("render=6Lc-site");
  });

  it("getToken returns the grecaptcha-issued token", async () => {
    installGrecaptchaStub("real-token-abc");
    const token = await getToken("6Lc-site", "submit");
    expect(token).toBe("real-token-abc");
  });

  it("getToken returns null when grecaptcha never appears", async () => {
    // No installGrecaptchaStub — onload fires but window.grecaptcha
    // stays undefined.
    const token = await getToken("6Lc-site", "submit");
    expect(token).toBeNull();
  });

  it("getToken returns null when grecaptcha.execute throws", async () => {
    (window as unknown as { grecaptcha: unknown }).grecaptcha = {
      ready: (cb: () => void) => cb(),
      execute: vi.fn().mockRejectedValue(new Error("network")),
    };
    const token = await getToken("6Lc-site", "submit");
    expect(token).toBeNull();
  });

  it("getToken passes the requested action through to grecaptcha", async () => {
    const exec = vi.fn().mockResolvedValue("t");
    (window as unknown as { grecaptcha: unknown }).grecaptcha = {
      ready: (cb: () => void) => cb(),
      execute: exec,
    };
    await getToken("6Lc-site", "submit");
    expect(exec).toHaveBeenCalledWith("6Lc-site", { action: "submit" });
  });
});
