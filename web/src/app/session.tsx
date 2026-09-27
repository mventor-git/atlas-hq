import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, type SessionInfo, type Theme } from "../lib/api";
import { applyTheme, initialTheme, isTheme } from "../lib/theme";

/**
 * The live session, the theme, and nothing else.
 *
 * The session state this holds is *a display of what the server said*, not a
 * credential and not a permission. The browser's only credential is the
 * HttpOnly cookie it cannot read, which is why there is no token in this file
 * and no reason for one.
 */

interface SessionContextValue {
  session: SessionInfo | null;
  checking: boolean;
  theme: Theme;
  setTheme: (theme: Theme) => void;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  /** Called by any page that hits a 401, so the shell re-checks the session. */
  onUnauthenticated: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  // Paint the mirror immediately so there is no light-first flash (§39.6).
  useEffect(() => applyTheme(theme), [theme]);

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      const live = await api.session();
      setSession(live);
      // Core's stored preference wins over the local mirror on every load.
      const stored = await api.theme.get();
      if (isTheme(stored.theme)) setThemeState(stored.theme);
    } catch {
      // A missing or dead session is the normal signed-out state, not an error
      // worth shouting about: 401 simply means there is no session.
      setSession(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(async () => {
    const result = await api.login();
    setSession({ authenticated: true, principal_id: result.principal_id, expires_at: "" });
    const stored = await api.theme.get();
    if (isTheme(stored.theme)) setThemeState(stored.theme);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setSession(null);
    }
  }, []);

  const setTheme = useCallback(
    (next: Theme) => {
      setThemeState(next);
      applyTheme(next);
      // Core owns the preference so it follows the principal to every channel.
      // A failure here is not fatal: the mirror already painted, and the next
      // load will take the stored value again.
      void api.theme.put(next).catch(() => undefined);
    },
    [],
  );

  const value = useMemo(
    () => ({ session, checking, theme, setTheme, signIn, signOut, onUnauthenticated: refresh }),
    [session, checking, theme, setTheme, signIn, signOut, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

// Re-exported so a page can validate a theme value it typed without importing
// from two places.
export { isTheme };
export type { Theme };
