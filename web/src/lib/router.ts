import { useEffect, useRef, useState } from "react";

/**
 * A hash router, because four pages do not justify a routing dependency. It
 * keeps the two things a router owes an assistive technology: the active link
 * is announced as current, and moving to a new page moves focus to that
 * page's heading.
 */

export function currentPath(): string {
  const raw = window.location.hash.replace(/^#/, "");
  return raw.startsWith("/") ? raw : "/";
}

export function navigate(path: string): void {
  window.location.hash = path;
}

export function useHashRoute(): string {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const onChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return path;
}

/** Move focus to the new page's <h1> so a keyboard user is not left behind. */
export function useFocusHeading(path: string): void {
  const previous = useRef(path);
  useEffect(() => {
    if (previous.current === path) return;
    previous.current = path;
    const heading = document.querySelector<HTMLElement>("[data-page-heading]");
    heading?.focus();
  }, [path]);
}
