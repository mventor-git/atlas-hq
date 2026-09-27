import { useSession } from "../app/session";
import { PageHeading } from "../app/shell";
import { ErrorNotice } from "../app/async";
import { Badge, SuccessMark } from "../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { api } from "../lib/api";
import { useAsync } from "../lib/useAsync";

const SECTIONS = [
  {
    path: "/roles",
    title: "Roles",
    body: "Grant or revoke a capability or role for a principal at an organization, workplace, or self scope, and read back the effective permissions Core computed.",
  },
  {
    path: "/reports",
    title: "Reports",
    body: "Every report definition the enabled providers publish, discovered through the public contract. Render one for an organization.",
  },
  {
    path: "/self-report",
    title: "My monthly report",
    body: "Your own monthly report. The request names no principal, because the handle is the identity.",
  },
] as const;

export function DashboardPage() {
  const { session, theme } = useSession();
  const capabilities = useAsync(() => api.capabilities(), []);
  const reports = useAsync(() => api.reports(), []);

  const capabilityError = capabilities.error;
  const reportError = reports.error;

  return (
    <>
      <PageHeading
        title="Dashboard"
        lead={`Signed in as ${session?.principal_id ?? "unknown"}. The roles engine decides every action; this page only shows what it returned.`}
      />

      <div className="grid gap-4 md:grid-cols-2">
        {SECTIONS.map((section) => (
          <Card key={section.path}>
            <CardHeader>
              <CardTitle>
                <a
                  href={`#${section.path}`}
                  className="underline underline-offset-4"
                >
                  {section.title}
                </a>
              </CardTitle>
              <CardDescription>{section.body}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Catalogue</CardTitle>
            <CardDescription>
              Capabilities registered with Core, reached with the authorization.manage capability.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {capabilityError ? (
              <ErrorNotice error={capabilityError} onRetry={capabilities.reload} />
            ) : (
              <p className="text-sm">
                <span className="text-2xl font-semibold tabular-nums">
                  {capabilities.loading ? "\u2014" : capabilities.data?.capabilities.length ?? 0}
                </span>{" "}
                capabilities registered
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Report definitions</CardTitle>
            <CardDescription>Discovered from every enabled provider, with no plugin named here.</CardDescription>
          </CardHeader>
          <CardContent>
            {reportError ? (
              <ErrorNotice error={reportError} onRetry={reports.reload} />
            ) : (
              <p className="text-sm">
                <span className="text-2xl font-semibold tabular-nums">
                  {reports.loading ? "\u2014" : reports.data?.reports.length ?? 0}
                </span>{" "}
                definitions published
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Session</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Principal</dt>
              <dd>{session?.principal_id}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Session expires</dt>
              <dd>
                {session?.expires_at ? new Date(session.expires_at).toLocaleString() : "unknown"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Theme</dt>
              <dd>
                <Badge tone="neutral">{theme}</Badge>
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Credential held by the browser</dt>
              <dd className="flex items-center gap-2">
                <SuccessMark />
                One opaque cookie, HttpOnly
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </>
  );
}
