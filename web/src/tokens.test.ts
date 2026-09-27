import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { applyTheme, cachedTheme, initialTheme, isTheme } from "./lib/theme";

/**
 * contract.md §39.5 requires every token pair in both themes to be verified by
 * an automated run rather than by eye, and a failing pair blocks the change
 * that introduced it. The Python test `tests/test_design_token_contrast.py`
 * owns the §39.2 table itself; this run covers the two things that can only be
 * checked on the frontend side: that `index.css` still says what the table
 * says, and that the derived `fg.muted` role clears the text minimum it has to
 * clear in each theme.
 */

// The vitest root is `web/`, and jsdom makes `import.meta.url` an http URL, so
// the token file is resolved from the root rather than from the module URL.
const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

function block(selector: string): string {
  const start = css.indexOf(selector);
  if (start === -1) throw new Error(`${selector} is missing from index.css`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

const LIGHT = block(':root,\n:root[data-theme="light"]');
const DARK = block(':root[data-theme="dark"]');

function value(source: string, variable: string): string {
  const match = new RegExp(`${variable}\\s*:\\s*([^;]+);`).exec(source);
  if (match === null) throw new Error(`${variable} is not defined`);
  return match[1].trim().replace(/^#/, "").toLowerCase();
}

function luminance(hex: string): number {
  const channels = [0, 2, 4].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function ratio(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const TEXT_MINIMUM = 4.5;
const NON_TEXT_MINIMUM = 3;

/** The §39.2 table, transcribed into §39.8 variable names. */
const CONTRACT: Record<string, [string, string]> = {
  background: ["f7f2eb", "41444b"],
  card: ["eae2d6", "52575d"],
  border: ["eeeeee", "52575d"],
  primary: ["8b9a6e", "cabfab"],
  foreground: ["2d0000", "dfd8c8"],
  input: ["757d6f", "dfd8c8"],
  "primary-foreground": ["2d0000", "41444b"],
  ring: ["2d0000", "dfd8c8"],
  "focus-ring-on-accent": ["2d0000", "41444b"],
  "success-foreground": ["2d0000", "2d0000"],
  success: ["c7d3c0", "c7d3c0"],
  "success-indicator": ["2a7c13", "2a7c13"],
  "warning-foreground": ["2d0000", "2d0000"],
  warning: ["c8a96b", "c8a96b"],
  "danger-foreground": ["6d0808", "6d0808"],
  danger: ["ffdada", "ffdada"],
  "info-foreground": ["2d0000", "2d0000"],
  info: ["fbe6c2", "fbe6c2"],
};

describe("the §39.8 variable mapping", () => {
  /**
   * §39.8 fixes the variable *names*, so a rename is a contract change rather
   * than a taste question. Each row asserts the variable exists in both themes
   * and that the Tailwind `--color-*` alias points at exactly that variable, so
   * a utility such as `bg-primary` can only ever resolve through `--primary`.
   */
  it.each([
    ["--background", "--color-background"],
    ["--card", "--color-card"],
    ["--border", "--color-border"],
    ["--input", "--color-input"],
    ["--primary", "--color-primary"],
    ["--primary-foreground", "--color-primary-foreground"],
    ["--foreground", "--color-foreground"],
    ["--muted-foreground", "--color-muted-foreground"],
    ["--ring", "--color-ring"],
    ["--focus-ring-on-accent", "--color-ring-on-accent"],
    ["--success", "--color-success"],
    ["--success-foreground", "--color-success-foreground"],
    ["--success-indicator", "--color-success-indicator"],
    ["--warning", "--color-warning"],
    ["--warning-foreground", "--color-warning-foreground"],
    ["--danger", "--color-danger"],
    ["--danger-foreground", "--color-danger-foreground"],
    ["--info", "--color-info"],
    ["--info-foreground", "--color-info-foreground"],
  ])("%s is defined in both themes and aliased from %s", (variable, colorVariable) => {
    expect(LIGHT).toContain(`${variable}:`);
    expect(DARK).toContain(`${variable}:`);
    expect(css).toContain(`${colorVariable}: var(${variable});`);
  });

  it("keeps the §39.8 variable names free of the invented Atlas-only ones", () => {
    // The earlier revision invented --bg-canvas, --fg-default, --state-*-ink
    // and friends. §39.8 names the variables, so those are gone.
    for (const retired of [
      "--bg-canvas",
      "--bg-surface",
      "--fg-default",
      "--fg-muted",
      "--accent-default",
      "--on-accent-default",
      "--focus-ring:",
      "--state-",
    ]) {
      expect(css).not.toContain(retired);
    }
  });

  it("switches theme through data-theme, with no .dark class anywhere (§39.6)", () => {
    expect(css).toContain(':root[data-theme="dark"]');
    expect(css).not.toMatch(/^\s*\.dark\b/m);
    // `lib/theme.ts` is what writes the attribute; nothing else may.
    expect(readFileSync(resolve(process.cwd(), "src/lib/theme.ts"), "utf8")).toContain(
      "documentElement.dataset.theme",
    );
  });
});

describe("§39.2 token values in index.css", () => {
  it.each(Object.entries(CONTRACT))(
    "%s matches the contract in both themes",
    (variable, [light, dark]) => {
      expect(value(LIGHT, `--${variable}`)).toBe(light);
      expect(value(DARK, `--${variable}`)).toBe(dark);
    },
  );

  it("keeps border.divider out of every text and fill role (§39.3)", () => {
    // #EEEEEE is a border.divider value only. A light muted ink, a light
    // success ink, or an on-accent ink equal to it would break that rule.
    expect(value(LIGHT, "--muted-foreground")).not.toBe("eeeeee");
    expect(value(LIGHT, "--border")).toBe("eeeeee");
  });

  it("defines both focus roles in both themes (§39.2)", () => {
    // Both roles must exist in both themes, so no surface needs a theme-specific
    // name. In the light theme they resolve to the same value because #2D0000
    // already clears 3:1 on the light accent fill; only the dark theme needs
    // them to differ, and there `ring` is the forbidden pair.
    for (const variable of ["--ring", "--focus-ring-on-accent"]) {
      expect(LIGHT).toContain(`${variable}:`);
      expect(DARK).toContain(`${variable}:`);
    }
    expect(value(DARK, "--ring")).not.toBe(value(DARK, "--focus-ring-on-accent"));
  });
});

describe("§39.5 contrast, measured in both themes", () => {
  const theme = (name: "light" | "dark") => (name === "light" ? LIGHT : DARK);

  it.each(["light", "dark"] as const)("%s body ink clears the text minimum", (name) => {
    const source = theme(name);
    const ink = value(source, "--foreground");
    expect(ratio(ink, value(source, "--background"))).toBeGreaterThanOrEqual(TEXT_MINIMUM);
    expect(ratio(ink, value(source, "--card"))).toBeGreaterThanOrEqual(TEXT_MINIMUM);
  });

  it.each(["light", "dark"] as const)("%s control boundaries clear the non-text minimum", (name) => {
    const source = theme(name);
    const control = value(source, "--input");
    expect(ratio(control, value(source, "--background"))).toBeGreaterThanOrEqual(NON_TEXT_MINIMUM);
    expect(ratio(control, value(source, "--card"))).toBeGreaterThanOrEqual(NON_TEXT_MINIMUM);
  });

  it.each(["light", "dark"] as const)("%s on-accent ink clears the text minimum", (name) => {
    const source = theme(name);
    expect(ratio(value(source, "--primary-foreground"), value(source, "--primary"))).toBeGreaterThanOrEqual(
      TEXT_MINIMUM,
    );
  });

  it.each(["light", "dark"] as const)(
    "%s focus.ring.onAccent clears the non-text minimum on the accent fill",
    (name) => {
      const source = theme(name);
      expect(ratio(value(source, "--focus-ring-on-accent"), value(source, "--primary"))).toBeGreaterThanOrEqual(
        NON_TEXT_MINIMUM,
      );
    },
  );

  it.each(["light", "dark"] as const)(
    "%s focus.ring clears the non-text minimum on canvas and surface",
    (name) => {
      const source = theme(name);
      const ring = value(source, "--ring");
      expect(ratio(ring, value(source, "--background"))).toBeGreaterThanOrEqual(NON_TEXT_MINIMUM);
      expect(ratio(ring, value(source, "--card"))).toBeGreaterThanOrEqual(NON_TEXT_MINIMUM);
    },
  );

  it("keeps the dark focus.ring on an accent fill a forbidden pair, not a pass (§39.3)", () => {
    // The carve-out is load-bearing: if a future palette change made this pass,
    // `focus.ring.onAccent` would look redundant rather than required.
    expect(ratio(value(DARK, "--ring"), value(DARK, "--primary"))).toBeLessThan(NON_TEXT_MINIMUM);
  });

  it.each(["light", "dark"] as const)("%s state ink clears the text minimum on its own fill", (name) => {
    const source = theme(name);
    for (const state of ["success", "warning", "danger", "info"]) {
      expect(
        ratio(value(source, `--${state}-foreground`), value(source, `--${state}`)),
      ).toBeGreaterThanOrEqual(TEXT_MINIMUM);
    }
  });

  it.each(["light", "dark"] as const)(
    "%s success indicator stays non-text only (§39.2 carve-out)",
    (name) => {
      const source = theme(name);
      const measured = ratio(value(source, "--success-indicator"), value(source, "--success"));
      // Clears 3:1 as an indicator...
      expect(measured).toBeGreaterThanOrEqual(NON_TEXT_MINIMUM);
      // ...and still fails 4.5:1, which is exactly why it may not be body text.
      expect(measured).toBeLessThan(TEXT_MINIMUM);
    },
  );

  it.each(["light", "dark"] as const)("%s derived fg.muted clears the text minimum", (name) => {
    // §39.2: fg.muted is derived, must reach 4.5:1 on the background it is used
    // on, and is settled by measurement rather than by palette.
    const source = theme(name);
    const muted = value(source, "--muted-foreground");
    expect(ratio(muted, value(source, "--background"))).toBeGreaterThanOrEqual(TEXT_MINIMUM);
    expect(ratio(muted, value(source, "--card"))).toBeGreaterThanOrEqual(TEXT_MINIMUM);
  });

  it("keeps both border.divider values decorative and below the non-text minimum", () => {
    expect(ratio(value(LIGHT, "--border"), value(LIGHT, "--background"))).toBeLessThan(NON_TEXT_MINIMUM);
    expect(ratio(value(DARK, "--border"), value(DARK, "--card"))).toBeLessThan(NON_TEXT_MINIMUM);
  });
});

describe("§39.6 theme preference", () => {
  it("rejects anything that is not a §39.2 theme", () => {
    expect(isTheme("light")).toBe(true);
    expect(isTheme("dark")).toBe(true);
    expect(isTheme("solarized")).toBe(false);
    expect(isTheme(null)).toBe(false);
  });

  it("defaults to light when nothing is cached (§39.6)", () => {
    localStorage.clear();
    expect(cachedTheme()).toBeNull();
    expect(initialTheme()).toBe("light");
  });

  it("mirrors a choice onto the document and the local cache", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(cachedTheme()).toBe("dark");
    // The mirror exists only to avoid a light-first flash; Core owns the value.
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(cachedTheme()).toBe("light");
  });
});
