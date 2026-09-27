import { useState } from "react";

import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { useSession } from "./session";

/**
 * The development login.
 *
 * There is no principal field and no credential field, and there cannot be:
 * the operator is server configuration read from ATLAS_WEB_OPERATOR_PRINCIPAL,
 * and the route itself is off unless ATLAS_WEB_DEV_LOGIN says so. A 404 here
 * means the switch is off, which is a different message from a 503.
 */
export function SignIn() {
  const { signIn } = useSession();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ title: string; detail: string } | null>(null);

  async function onSignIn() {
    setBusy(true);
    setFailure(null);
    try {
      await signIn();
    } catch (error) {
      const code = (error as { code?: string }).code;
      if (code === "login_disabled") {
        setFailure({
          title: "The development login is off",
          detail: "Set ATLAS_WEB_DEV_LOGIN=1 on the server to enable POST /api/session.",
        });
      } else if (code === "operator_not_configured") {
        setFailure({
          title: "No operator principal is configured",
          detail:
            "Run `atlas-hq operator-init --principal atlas.local.operator --organization org_local --create-organization --organization-name \"Atlas Local\" --grant authorization.manage`, then set ATLAS_WEB_OPERATOR_PRINCIPAL to atlas.local.operator. See web/README.md.",
        });
      } else if (code === "network_unavailable" || code === "unknown") {
        setFailure({
          title: "The API is not reachable",
          detail: "Start the Atlas web API on http://127.0.0.1:8000 and try again.",
        });
      } else {
        setFailure({
          title: "Sign in failed",
          detail: (error as Error).message || "The request could not be completed.",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      id="main"
      className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center gap-6 p-6"
    >
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Atlas-HQ console</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Development login. The server acts as the operator principal it is configured with; this
          page never names one, and there is nothing to type.
        </p>
      </div>

      {failure ? <Alert tone="danger" title={failure.title}>{failure.detail}</Alert> : null}

      <Button onClick={onSignIn} disabled={busy} size="lg">
        {busy ? "Signing in\u2026" : "Sign in as the configured operator"}
      </Button>

      <p className="text-xs text-muted-foreground">
        The browser receives one opaque <code>atlas_session</code> cookie. No capability, handle, or
        unit of work is ever sent to this page.
      </p>
    </main>
  );
}
