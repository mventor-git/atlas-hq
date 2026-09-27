import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * A guard on the build output, not on the source.
 *
 * Two classes of bug only exist here. Tailwind v4 scans source text for class
 * names and silently drops any it does not recognise, so a component can look
 * right in the editor and compile to no rule at all. And CSS selection is
 * decided by specificity, so a rule can be present, correct on its own, and
 * still never apply because another rule with equal specificity comes later --
 * which is exactly what happened to the focus ring: every Button variant set
 * both `focus.ring` and `focus.ring.onAccent`, and the onAccent one won
 * everywhere, so no control ever drew the ring its background called for.
 *
 * ponytail: one build into a temp directory, then assertions on the emitted
 * rules. Replace this with real visual regression if the component set grows;
 * do not grow it into one.
 */

const ROOT = process.cwd();

/*
 * Test files are not a source of production classes, and this file is the
 * reason that exclusion has to be real. Three assertions below name the two
 * Tailwind outline colour utilities as strings, and the automatic scanner reads
 * any class-name-shaped string out of any file in the source tree -- including a
 * test asserting that a component does *not* set them. So the needles are
 * assembled from fragments below, and index.css also excludes test files from
 * the scan, as a second line of defence. The fragments are not obfuscation:
 * they are the only way to assert the absence of a class name from inside a file
 * the class-name scanner reads.
 */
const RING = ["out", "line-", "ring"].join("");
const RING_ON_ACCENT = ["out", "line-", "ring-on-", "accent"].join("");

let emitted = "";

try {
  const outDir = mkdtempSync(join(tmpdir(), "atlas-web-css-"));
  execFileSync("node", [resolve(ROOT, "node_modules/vite/bin/vite.js"), "build", "--outDir", outDir], {
    cwd: ROOT,
    stdio: "pipe",
  });
  const assets = readdirSync(join(outDir, "assets"));
  const cssFile = assets.find((name) => name.endsWith(".css"));
  if (cssFile === undefined) throw new Error(`no CSS asset in ${assets.join(", ")}`);
  emitted = readFileSync(join(outDir, "assets", cssFile), "utf8");
} catch (cause) {
  if (!existsSync(join(ROOT, "node_modules/vite/bin/vite.js"))) {
    throw new Error(`vite is not installed: ${String(cause)}`);
  }
  throw cause;
}

/** Every `selector { declarations }` in the sheet, minified onto one line. */
function rules(): { selector: string; body: string }[] {
  return [...emitted.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    // A selector list may follow the previous rule's `}`, so keep only the
    // last compound selector, which is the one that carries the declarations.
    selector: match[1].trim().split("}").pop()?.trim() ?? "",
    body: match[2].trim(),
  }));
}

/** The first rule whose declarations match `pattern`. */
function ruleWith(pattern: RegExp): { selector: string; body: string } | undefined {
  return rules().find((rule) => pattern.test(rule.body));
}

/** How many attribute/pseudo-class selectors a selector carries; more wins. */
function specificity(selector: string): number {
  return (selector.match(/\[|\]|:[a-z-]+|:not\(/gi) ?? []).length;
}

describe("the emitted stylesheet", () => {
  it("carries both theme token blocks", () => {
    // The minifier drops attribute-selector quotes, so match the unquoted form.
    expect(emitted).toMatch(/:root[^{]*\{[^}]*--background:\s*#f7f2eb/);
    expect(emitted).toMatch(/:root\[data-theme=dark\][^{]*\{[^}]*--background:\s*#41444b/);
  });

  it("tints the native checkbox from the accent token, with no dropped tick hack", () => {
    expect(ruleWith(/accent-color:\s*var\(--primary\)/)).toBeDefined();
    // The `after:` variant is not used at all, so there is no empty pseudo.
    expect(emitted).not.toContain("::after");
  });

  it("never falls back to a raw hex for a role it has a token for", () => {
    // §39.3: raw hex is forbidden in components. Two things are not a
    // component: the `:root` token block in index.css, which is the one place
    // a §39 value may appear, and Tailwind's own build-time internals
    // (`#0000` transparent, and the `--tw-ring-*` properties the `ring-*`
    // utilities register). This app styles focus with `outline`, not `ring`.
    const withoutTailwindInternals = emitted
      .replace(/:root[^{]*\{[^}]*\}/g, "")
      .replace(/@property[^{]*\{[^}]*\}/g, "")
      .replace(/--tw-[a-z-]+:[^;}]*/g, "");
    const hexes = [...withoutTailwindInternals.matchAll(/#[0-9a-f]{3,8}\b/gi)]
      .map((match) => match[0].toLowerCase())
      .filter((hex) => hex !== "#0000");
    expect(hexes).toEqual([]);
  });

  it("emits the screen-reader-only utility the shell relies on", () => {
    expect(emitted).toMatch(/\.sr-only/);
  });
});

describe("§39.5 the focus ring actually selected", () => {
  /**
   * The default. Every control with no `data-on-accent` matches only this, so
   * this is the pair a canvas or surface control draws.
   */
  it("draws focus.ring from the base rule alone", () => {
    const rule = ruleWith(/outline:\s*2px solid var\(--ring\)/);
    expect(rule).toBeDefined();
    expect(rule?.body).toMatch(/outline-offset:\s*2px/);
    // The plain rule must carry no accent ring, or the default would be wrong.
    expect(rule?.body).not.toContain("--focus-ring-on-accent");
  });

  /**
   * The accent case. §39.3 forbids `focus.ring` on an accent fill in the dark
   * theme (1.28:1), so an accent-filled control must resolve to
   * `focus.ring.onAccent` and nothing else.
   */
  it("swaps to focus.ring.onAccent for an accent-filled control", () => {
    const rule = rules().find((candidate) =>
      candidate.selector.includes("[data-on-accent]:focus-visible"),
    );
    expect(rule).toBeDefined();
    expect(rule?.body).toMatch(/outline-color:\s*var\(--focus-ring-on-accent\)/);
    // The swap sets the colour only, so the width and offset stay shared.
    expect(rule?.body).not.toMatch(/outline:\s/);
  });

  /**
   * The regression proper. Equal-specificity rules are decided by source
   * order, so the old Button base set both the plain and the accent outline
   * colour utility, and the accent one won on every variant. The fix is that
   * the accent rule must outrank the plain one, not merely follow it.
   */
  it("gives the onAccent rule strictly higher specificity than the plain rule", () => {
    const plain = ruleWith(/outline:\s*2px solid var\(--ring\)/);
    const accent = rules().find((rule) => rule.selector.includes("[data-on-accent]:focus-visible"));
    expect(plain).toBeDefined();
    expect(accent).toBeDefined();
    // `[data-on-accent]:focus-visible` carries one more compound selector than
    // a bare `:focus-visible`, so the accent ring wins by specificity.
    expect(specificity(accent?.selector ?? "")).toBeGreaterThan(specificity(plain?.selector ?? ""));
  });

  /**
   * The other half of determinism: if a component emitted its own outline
   * colour, it would land in the utilities layer, which beats the base layer
   * and would silently re-break the pairing above.
   */
  it("emits no component-level outline colour that could override the base", () => {
    const utilities = rules().filter(
      (rule) =>
        /outline-color:\s*var\(--/.test(rule.body) && !rule.selector.includes(":focus-visible"),
    );
    expect(utilities.map((rule) => rule.selector)).toEqual([]);
  });

  it("keeps exactly one rule that assigns an outline colour", () => {
    // Anchored on the assignment so `transition-property: ...outline-color...`
    // is not mistaken for one. The old sheet had three.
    const colouring = rules().filter((rule) => /outline-color:\s*var\(--/.test(rule.body));
    expect(colouring).toHaveLength(1);
    expect(colouring[0].selector).toContain("[data-on-accent]:focus-visible");
  });

  it("emits no stray ring utility, even named inside a test assertion", () => {
    // Assembled from fragments, because naming it literally would make
    // Tailwind's scanner emit it -- which is the bug this asserts against.
    expect(emitted).not.toContain(RING);
    expect(emitted).not.toContain(RING_ON_ACCENT);
  });
});
