import type { ReactNode } from "react";

import { Button } from "../components/ui/button";
import { navigate, useHashRoute } from "../lib/router";
import { useSession } from "./session";
import { ThemeSwitch } from "./theme-switch";

const NAV = [
  { path: "/", label: "Dashboard" },
  { path: "/roles", label: "Roles" },
  { path: "/reports", label: "Reports" },
  { path: "/self-report", label: "My monthly report" },
] as const;

/**
 * The shell: a skip link, a labelled nav with `aria-current` on the active
 * page, and a banner carrying the identity Core reported plus the theme
 * switch. The principal shown here is a display value from `GET /api/session`
 * -- it is not an input to anything.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const path = useHashRoute();
  const { session, signOut } = useSession();

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        // Accent-filled, so it carries `data-on-accent` and the base layer draws
        // focus.ring.onAccent on it. The plain focus.ring on an accent fill is
        // the forbidden 1.28:1 pair in the dark theme (§39.3).
        data-on-accent=""
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to main content
      </a>

      <header className="border-b border-input bg-card">
        <div className="mx-auto flex max-w-6xl flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
          <p className="text-sm font-semibold tracking-tight">Atlas-HQ console</p>
          <div className="flex flex-wrap items-center gap-4">
            <p className="text-sm text-muted-foreground">
              Operator: <span className="font-medium text-foreground">{session?.principal_id}</span>
            </p>
            <ThemeSwitch />
            <Button size="sm" variant="outline" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-4 md:flex-row md:gap-8">
        <nav aria-label="Sections" className="md:w-52 md:shrink-0">
          <ul className="flex flex-wrap gap-1 md:flex-col">
            {NAV.map((item) => {
              const active = path === item.path;
              return (
                <li key={item.path}>
                  <a
                    href={`#${item.path}`}
                    aria-current={active ? "page" : undefined}
                    // Only the active link is accent-filled, and only it needs
                    // the onAccent ring. `data-on-accent` is absent otherwise, so
                    // the inactive link keeps focus.ring on the canvas behind it.
                    data-on-accent={active ? "" : undefined}
                    onClick={(event) => {
                      event.preventDefault();
                      navigate(item.path);
                    }}
                    className={
                      active
                        ? "block rounded-md border border-input bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
                        : "block rounded-md border border-transparent px-3 py-2 text-sm hover:bg-card"
                    }
                  >
                    {item.label}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <main id="main" tabIndex={-1} className="min-w-0 flex-1 focus:outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}

/** Every page's <h1>. Focusable, so a route change moves focus here. */
export function PageHeading({ title, lead }: { title: string; lead?: string }) {
  return (
    <div className="mb-6">
      <h1
        data-page-heading=""
        tabIndex={-1}
        className="text-2xl font-semibold tracking-tight focus:outline-none"
      >
        {title}
      </h1>
      {lead ? <p className="mt-1 text-sm text-muted-foreground">{lead}</p> : null}
    </div>
  );
}
