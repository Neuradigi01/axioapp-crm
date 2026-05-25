/**
 * Step 5 placeholder test. Confirms `init()`:
 *   - doesn't throw with a valid config + a mount div in the DOM
 *   - warns + bails when the mount div is missing
 *   - warns + bails on incomplete config (no `key`)
 *
 * Step 6 will add real renderer tests (form fields render, submit
 * handler fires, etc.).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { init } from "../src/index";

describe("init()", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the placeholder when the mount div exists", () => {
    const mount = document.createElement("div");
    mount.id = "furnicrm-form";
    document.body.appendChild(mount);

    init({
      key: "pk_live_test",
      host: "http://localhost:8000",
      mountId: "furnicrm-form",
    });

    expect(mount.textContent).toContain("FurniCRM widget");
  });

  it("warns + bails when the mount div is missing", () => {
    const warn = vi.spyOn(console, "warn");
    init({
      key: "pk_live_test",
      host: "http://localhost:8000",
      mountId: "nope",
    });
    expect(warn).toHaveBeenCalled();
  });

  it("warns + bails on incomplete config", () => {
    const warn = vi.spyOn(console, "warn");
    init({ key: "", host: "", mountId: "" });
    expect(warn).toHaveBeenCalled();
  });
});
