import { ErrorNotice } from "../app/async";
import { PageHeading } from "../app/shell";
import { Badge } from "../components/ui/badge";
import { EmptyState, Loading } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { api, type ReportSection } from "../lib/api";
import { useAsync } from "../lib/useAsync";

/**
 * The on-demand self report.
 *
 * The request is a bare `GET /api/self/monthly-report` with no query string
 * and no body. There is deliberately no principal field on this page: the
 * server refuses one with 422 `principal_not_accepted`, and the handle is the
 * identity (§38.6).
 */
export function SelfReportPage() {
  const report = useAsync(() => api.selfMonthlyReport(), []);

  return (
    <>
      <PageHeading
        title="My monthly report"
        lead="Your own report, on demand. The server resolves who you are from the session handle; this page never names a principal."
      />

      <Button
        variant="outline"
        className="mb-4"
        onClick={report.reload}
        disabled={report.loading}
      >
        {report.loading ? "Loading\u2026" : "Refresh"}
      </Button>

      {report.error ? (
        <ErrorNotice error={report.error} onRetry={report.reload} />
      ) : report.loading ? (
        <Loading label="Asking Core for your report\u2026" />
      ) : report.data === null ? (
        <Loading label="Asking Core for your report\u2026" />
      ) : report.data.sections.length === 0 ? (
        <EmptyState title="No sections were returned">
          The self-reporting plugin published no dataset for your principal.
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <UseCaseCard useCase={report.data.use_case} auditId={report.data.audit_id} />
          {report.data.sections.map((section) => (
            <SectionCard key={section.dataset_id} section={section} />
          ))}
        </div>
      )}
    </>
  );
}

function UseCaseCard({
  useCase,
  auditId,
}: {
  useCase: Partial<Record<string, unknown>> & { use_case_id?: string; title?: string };
  auditId: string;
}) {
  const entries = Object.entries(useCase).filter(([, value]) => value !== undefined && value !== "");
  if (entries.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{useCase.title ?? "Use case"}</CardTitle>
        <CardDescription>Declared metadata for this report, owned by the plugin.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          {entries.map(([key, value]) => (
            <div key={key}>
              <dt className="text-muted-foreground">{key.replace(/_/g, " ")}</dt>
              <dd>{Array.isArray(value) ? value.join(", ") || "\u2014" : String(value)}</dd>
            </div>
          ))}
          <div>
            <dt className="text-muted-foreground">audit id</dt>
            <dd className="font-mono text-xs">{auditId}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

export function SectionCard({ section }: { section: ReportSection }) {
  const rows = section.groups.flatMap((group) => group.rows);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {section.title}{" "}
          {section.installed ? (
            <Badge tone="success">installed</Badge>
          ) : (
            <Badge tone="warning">not installed</Badge>
          )}
        </CardTitle>
        <CardDescription>
          <span className="font-mono text-xs">{section.dataset_id}</span>
          {section.note ? <span className="ml-2">{section.note}</span> : null}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState title="No rows in this section">
            The dataset answered with an empty group for this scope.
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-4">
            {section.groups.length === 1 ? (
              <GroupTable section={section} group={section.groups[0]} />
            ) : (
              section.groups.map((group) => (
                <div key={group.key.join("|")}>
                  <h3 className="mb-1 text-sm font-medium">
                    {group.key.filter((part) => part !== null).join(" \u203a ") || "Group"}
                    <span className="ml-2 text-muted-foreground">
                      {group.count} {group.count === 1 ? "row" : "rows"}
                    </span>
                  </h3>
                  <GroupTable section={section} group={group} />
                </div>
              ))
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GroupTable({
  section,
  group,
}: {
  section: ReportSection;
  group: ReportSection["groups"][number];
}) {
  return (
    <Table>
      <TableCaption>
        {section.title}
        {group.key.length > 0
          ? ` \u2014 ${group.key.filter((part) => part !== null).join(" \u203a ")}`
          : ""}
        . {group.count} {group.count === 1 ? "row" : "rows"}.
      </TableCaption>
      <TableHeader>
        <TableRow>
          {section.columns.map((column) => (
            <TableHead key={column} scope="col">
              {column}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {group.rows.map((row, index) => (
          <TableRow key={`${group.key.join("|")}-${index}`}>
            {row.map((cell, cellIndex) => (
              <TableCell key={section.columns[cellIndex] ?? cellIndex}>
                {cell === null ? "\u2014" : String(cell)}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
