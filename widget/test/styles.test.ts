/**
 * Tests for the inline-style injection helper. The renderer relies
 * on a single `<style data-furnicrm>` tag being present in the host
 * page's <head> exactly once — multiple widgets on the same page (or
 * accidental double-mounting) must not duplicate the stylesheet.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { getStyles, injectStyles } from "../src/styles";


describe("injectStyles", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
  });

  it("injects exactly one <style data-furnicrm> tag", () => {
    injectStyles();
    const tags = document.head.querySelectorAll("style[data-furnicrm]");
    expect(tags.length).toBe(1);
    expect(tags[0].textContent).toContain("--fc-primary");
  });

  it("is idempotent — calling twice still only yields one tag", () => {
    injectStyles();
    injectStyles();
    injectStyles();
    expect(document.head.querySelectorAll("style[data-furnicrm]").length).toBe(1);
  });
});


describe("getStyles", () => {
  it("returns a non-empty CSS string exposing the variable contract", () => {
    const css = getStyles();
    expect(css.length).toBeGreaterThan(0);
    expect(css).toContain("--fc-primary");
    expect(css).toContain(".furnicrm-form__button");
  });
});
