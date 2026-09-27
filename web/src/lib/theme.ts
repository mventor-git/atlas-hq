import type { Theme } from "./api";

/**
 * §39.6: Core owns the theme preference and it follows the principal across
 * channels. The browser may mirror it locally only to avoid a light-first
 * flash, and the mirror never wins over what Core returned. Light is the
 * default; `prefers-color-scheme` is an input to the preference, never the
 * preference.
 */

export const THEMES: readonly Theme[] = ["light", "dark"] as const;

/** The key `index.html` reads before React mounts. */
const CACHE_KEY = "atlas.theme.cache";

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(CACHE_KEY, theme);
  } catch {
    // A blocked localStorage is conformant: the value simply is not mirrored.
  }
}

/** The mirrored value, or null when nothing has been cached yet. */
export function cachedTheme(): Theme | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return isTheme(raw) ? raw : null;
  } catch {
    return null;
  }
}

/**
 * The first render, before Core has answered: the mirror if there is one,
 * otherwise light. §39.6 permits seeding from `prefers-color-scheme` only
 * while no Core-owned value exists, and skipping the mirror entirely is
 * preferred over storing a value that can disagree, so this stays simple.
 */
export function initialTheme(): Theme {
  return cachedTheme() ?? "light";
}
