import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { describeError } from "../lib/errors";
import { useSession } from "../app/session";

/**
 * One place that turns a thrown error into an accessible, actionable message.
 * Every page routes its failure through here, so a 401 always leads to the
 * login, a 403 always says the roles engine refused it, and a 422 always says
 * what to fix. Nothing here invents a status the server did not send.
 */
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { onUnauthenticated } = useSession();
  const friendly = describeError(error);

  return (
    <Alert
      tone="danger"
      title={friendly.title}
      action={
        friendly.reauthenticate ? (
          <Button size="sm" variant="outline" onClick={onUnauthenticated}>
            Sign in again
          </Button>
        ) : onRetry ? (
          <Button size="sm" variant="outline" onClick={onRetry}>
            Try again
          </Button>
        ) : null
      }
    >
      <p>{friendly.detail}</p>
      <p className="mt-1 text-xs">
        {friendly.status === null ? "code" : "HTTP"}: <code>{friendly.code}</code>
        {friendly.status === null ? "" : ` (${friendly.status})`}
      </p>
    </Alert>
  );
}
