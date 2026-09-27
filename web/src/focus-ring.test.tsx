import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "./app/session";
import { AppShell } from "./app/shell";
import { Button } from "./components/ui/button";
import { Checkbox } from "./components/ui/checkbox";
import { Input } from "./components/ui/input";

/**
 * Which ring a control draws is decided in CSS, so these tests assert the half
 * that is decided in the DOM: whether a control is marked as accent-filled.
 * That mark is the only input the base layer has, so a variant that draws an
 * accent background without it is the §39.3 forbidden pair by construction.
 *
 * The CSS half -- that the mark actually flips the ring -- is covered in
 * src/css-output.test.ts, because that is the only place a build can prove it.
 */

const ACCENT_FILLED_BACKGROUND = /\bbg-primary\b/;

/*
 * Assembled from fragments, not written literally. Tailwind's scanner reads any
 * class-name-shaped string from any file in the source tree, so a test that
 * spelled either utility in full would make Tailwind emit it -- putting a
 * competing outline colour back into the built sheet and re-creating the very
 * bug these tests exist to prevent. The exclusions in index.css are a second
 * line of defence; these fragments are the one that cannot be
 * version-dependent.
 */
const RING = ["out", "line-", "ring"].join("");
const RING_ON_ACCENT = ["out", "line-", "ring-on-", "accent"].join("");

/** The shell reads the session, so it needs the provider and a live session. */
function renderShell() {
  const fetchMock = vi.fn((url: string) =>
    new Response(
      JSON.stringify(
        url === "/api/session/theme"
          ? { theme: "light" }
          : { authenticated: true, principal_id: "atlas.local.operator", expires_at: "" },
      ),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <SessionProvider>
      <AppShell>
        <p>body</p>
      </AppShell>
    </SessionProvider>,
  );
}

beforeEach(() => {
  window.location.hash = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Button variants and the focus ring they select", () => {
  const cases = [
    { variant: "default", accent: true },
    { variant: "outline", accent: false },
    { variant: "ghost", accent: false },
    { variant: "link", accent: false },
  ] as const;

  it.each(cases)("$variant marks itself accent-filled: $accent", ({ variant, accent }) => {
    render(<Button variant={variant}>press me</Button>);
    const button = screen.getByRole("button", { name: "press me" });
    expect(button.hasAttribute("data-on-accent")).toBe(accent);
  });

  it.each(cases)("$variant sets no outline colour of its own", ({ variant }) => {
    render(<Button variant={variant}>press me</Button>);
    const classes = screen.getByRole("button", { name: "press me" }).className;
    // The whole point: no variant may compete with the base layer.
    expect(classes).not.toContain(RING);
    expect(classes).not.toContain(RING_ON_ACCENT);
  });

  it("marks exactly the variants that paint an accent fill", () => {
    for (const { variant, accent } of cases) {
      const { unmount } = render(<Button variant={variant}>x</Button>);
      const button = screen.getByRole("button", { name: "x" });
      const painted = ACCENT_FILLED_BACKGROUND.test(button.className);
      // The invariant: marked <=> painted. Either both or neither.
      expect(painted).toBe(accent);
      unmount();
    }
  });

  it("defaults to the accent variant when none is named", () => {
    render(<Button>bare</Button>);
    const button = screen.getByRole("button", { name: "bare" });
    expect(button).toHaveAttribute("data-on-accent");
    expect(button.className).toMatch(ACCENT_FILLED_BACKGROUND);
  });

  it("still honours an explicit accent variant through asChild", () => {
    render(
      <Button asChild variant="default">
        <a href="#target">a link styled as a button</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "a link styled as a button" });
    expect(link).toHaveAttribute("data-on-accent");
  });
});

describe("controls that sit on a surface", () => {
  it("leaves an input and a checkbox unmarked, so they keep focus.ring", () => {
    render(
      <>
        <Input aria-label="organization" />
        <Checkbox aria-label="a grant" />
      </>,
    );
    expect(screen.getByLabelText("organization")).not.toHaveAttribute("data-on-accent");
    expect(screen.getByLabelText("a grant")).not.toHaveAttribute("data-on-accent");
  });

  it("marks only the active nav link, since only it is accent-filled", async () => {
    window.location.hash = "/roles";
    renderShell();
    const nav = await screen.findByRole("navigation", { name: "Sections" });
    const active = within(nav).getByRole("link", { name: "Roles" });
    const inactive = within(nav).getByRole("link", { name: "Dashboard" });

    expect(active).toHaveAttribute("aria-current", "page");
    expect(active.className).toMatch(ACCENT_FILLED_BACKGROUND);
    expect(active).toHaveAttribute("data-on-accent");

    expect(inactive).not.toHaveAttribute("aria-current");
    expect(inactive.className).not.toMatch(ACCENT_FILLED_BACKGROUND);
    expect(inactive).not.toHaveAttribute("data-on-accent");
  });

  it("marks the skip link, which becomes accent-filled on focus", async () => {
    renderShell();
    const skip = await screen.findByRole("link", { name: "Skip to main content" });
    // `focus:bg-primary` is the fill, so it needs the onAccent ring once shown.
    expect(skip.className).toMatch(/focus:bg-primary/);
    expect(skip).toHaveAttribute("data-on-accent");
  });
});
