/**
 * Renderer unit tests — assert the renderer's contract without
 * touching the network. The orchestrator (index.ts) wires the
 * onSubmit callback to the API client; here we pass a spy.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  renderError,
  renderForm,
  renderSuccessState,
} from "../src/renderer";
import type { Attribution, SubmissionPayload, WidgetConfig } from "../src/types";


const ATTRIBUTION: Attribution = {
  referrer: null,
  landing_url: null,
  utm_source: null,
  utm_medium: null,
  utm_campaign: null,
  utm_content: null,
  utm_term: null,
};

function makeConfig(overrides: Partial<WidgetConfig> = {}): WidgetConfig {
  return {
    fields: [
      { key: "full_name", label: "Name", required: true, order: 0, field_type: "text" },
      { key: "phone", label: "Phone", required: true, order: 1, field_type: "tel" },
      { key: "email", label: "Email", required: false, order: 2, field_type: "email" },
      { key: "interest", label: "Interest", required: false, order: 3, field_type: "select", options: ["Sofas", "Beds"] },
      { key: "notes", label: "Notes", required: false, order: 4, field_type: "textarea" },
    ],
    submit_button_label: "Submit",
    thank_you_message: "Thanks!",
    thank_you_url: null,
    branding: { logo_url: null, accent_color: "#000000", show_powered_by: true },
    ...overrides,
  };
}


describe("renderForm", () => {
  let mount: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = "";
    mount = document.createElement("div");
    mount.id = "furnicrm-form";
    document.body.appendChild(mount);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders one wrapper per field + a button + a powered-by footer", () => {
    renderForm(mount, makeConfig(), vi.fn(), ATTRIBUTION);
    const wrappers = mount.querySelectorAll(".furnicrm-form__field");
    expect(wrappers.length).toBe(5);
    expect(mount.querySelector(".furnicrm-form__button")?.textContent).toBe(
      "Submit",
    );
    expect(mount.querySelector(".furnicrm-form__powered-by")).not.toBeNull();
  });

  it("includes a hidden honeypot input", () => {
    renderForm(mount, makeConfig(), vi.fn(), ATTRIBUTION);
    const honeypot = mount.querySelector('input[name="honeypot"]');
    expect(honeypot).not.toBeNull();
    expect((honeypot as HTMLInputElement).getAttribute("aria-hidden")).toBe("true");
  });

  it("marks required fields invalid when submitted empty", () => {
    const onSubmit = vi.fn();
    renderForm(mount, makeConfig(), onSubmit, ATTRIBUTION);
    const form = mount.querySelector("form") as HTMLFormElement;
    form.requestSubmit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      mount.querySelector('[data-field-key="full_name"]')?.classList.contains("furnicrm-form__field--invalid"),
    ).toBe(true);
    expect(
      mount.querySelector('[data-field-key="phone"]')?.classList.contains("furnicrm-form__field--invalid"),
    ).toBe(true);
  });

  it("invokes the submit callback with the expected payload shape", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderForm(mount, makeConfig(), onSubmit, {
      ...ATTRIBUTION,
      utm_source: "test",
    });

    (mount.querySelector('input[name="full_name"]') as HTMLInputElement).value = "Asha Reddy";
    (mount.querySelector('input[name="phone"]') as HTMLInputElement).value = "+91 9876543210";
    (mount.querySelector('input[name="email"]') as HTMLInputElement).value = "asha@example.com";
    (mount.querySelector('select[name="interest"]') as HTMLSelectElement).value = "Sofas";

    (mount.querySelector("form") as HTMLFormElement).requestSubmit();
    expect(onSubmit).toHaveBeenCalledOnce();
    const payload = onSubmit.mock.calls[0][0] as SubmissionPayload;
    expect(payload.full_name).toBe("Asha Reddy");
    expect(payload.phone).toBe("+91 9876543210");
    expect(payload.email).toBe("asha@example.com");
    expect(payload.interest).toBe("Sofas");
    expect(payload.attribution.utm_source).toBe("test");
    expect(typeof payload.rendered_at).toBe("string");
    expect(payload.honeypot).toBe("");
  });

  it("rejects malformed email client-side", () => {
    const onSubmit = vi.fn();
    renderForm(mount, makeConfig(), onSubmit, ATTRIBUTION);
    (mount.querySelector('input[name="full_name"]') as HTMLInputElement).value = "X";
    (mount.querySelector('input[name="phone"]') as HTMLInputElement).value = "1234567";
    (mount.querySelector('input[name="email"]') as HTMLInputElement).value = "not-an-email";

    (mount.querySelector("form") as HTMLFormElement).requestSubmit();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      mount.querySelector('[data-field-key="email"]')?.classList.contains("furnicrm-form__field--invalid"),
    ).toBe(true);
  });

  it("never writes via innerHTML (XSS posture)", () => {
    // If a label tries to inject a script, it should render as text not as HTML.
    const cfg = makeConfig({
      fields: [
        { key: "full_name", label: "<script>alert(1)</script>", required: true, order: 0, field_type: "text" },
      ],
    });
    renderForm(mount, cfg, vi.fn(), ATTRIBUTION);
    expect(mount.querySelector("script")).toBeNull();
    // The literal text shows through:
    expect(mount.textContent).toContain("<script>");
  });
});


describe("renderSuccessState", () => {
  it("replaces mount content with the thank-you message", () => {
    const mount = document.createElement("div");
    document.body.appendChild(mount);
    renderSuccessState(mount, makeConfig({ thank_you_message: "Got it!" }));
    expect(mount.textContent).toContain("Got it!");
    expect(mount.querySelector(".furnicrm-form--success")).not.toBeNull();
  });
});


describe("renderError", () => {
  it("replaces mount content with the error message", () => {
    const mount = document.createElement("div");
    document.body.appendChild(mount);
    renderError(mount, "Something broke");
    expect(mount.textContent).toContain("Something broke");
    expect(mount.querySelector(".furnicrm-form--error")).not.toBeNull();
  });
});
