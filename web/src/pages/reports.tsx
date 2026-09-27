import { useId, useState } from "react";

import { ErrorNotice } from "../app/async";
import { PageHeading } from "../app/shell";
import { EmptyState, Loading } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { api, type ReportDefinitionSummary } from "../lib/api";
import { useAsync } from "../lib/useAsync";
import { SectionCard } from "./self-report";

/**
 * The report catalogue and one render.
 *
 * `GET /api/reports` discovers every enabled provider's definition through the
 * published contract, so this page names no plugin. A render asks Report Studio
 * for an organization and nothing else, because that is the scope the plugin
 * requests; a self-scoped dataset inside an organization render correctly
 * contributes no rows, and the page says so rather than hiding it.
 */
export function ReportsPage() {
  const definitions = useAsync(() => api.reports(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [organizationId, setOrganizationId] = useState("");

  const chosen = definitions.data?.reports.find((report) => report.definition_id === selected) ?? null;

  return (
    <>
      <PageHeading
        title="Reports"
        lead="Definitions published by enabled providers, discovered through the public reporting contract. Rendering one is a real Report Studio call for an organization."
      />

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Definitions</CardTitle>
            <CardDescription>
              {definitions.loading
                ? "Asking every provider\u2026"
                : `${definitions.data?.reports.length ?? 0} published`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {definitions.error ? (
              <ErrorNotice error={definitions.error} onRetry={definitions.reload} />
            ) : definitions.loading ? (
              <Loading label="Loading definitions\u2026" />
            ) : definitions.data === null ? (
              <Loading label="Loading definitions\u2026" />
            ) : definitions.data.reports.length === 0 ? (
              <EmptyState title="No report definitions">
                No enabled provider published a definition.
              </EmptyState>
            ) : (
              <ul className="flex flex-col gap-1">
                {definitions.data.reports.map((report) => (
                  <li key={report.definition_id}>
                    <DefinitionButton
                      report={report}
                      active={report.definition_id === selected}
                      onSelect={() => setSelected(report.definition_id)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <div className="min-w-0">
          {chosen ? (
            <RenderPanel
              report={chosen}
              organizationId={organizationId}
              onOrganizationChange={setOrganizationId}
            />
          ) : (
            <EmptyState title="Choose a definition">
              Select a report on the left to render it for an organization.
            </EmptyState>
          )}
        </div>
      </div>
    </>
  );
}

function DefinitionButton({
  report,
  active,
  onSelect,
}: {
  report: ReportDefinitionSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const id = useId();
  return (
    <>
      <Button
        id={`${id}-tab`}
        variant={active ? "default" : "outline"}
        onClick={onSelect}
        aria-pressed={active}
        className="h-auto w-full justify-start py-2 text-left"
      >
        <span aria-hidden="true">{active ? "\u2713 " : ""}</span>
        <span className="min-w-0">
          <span className="block truncate">{report.title}</span>
          <span className="block truncate text-xs font-normal opacity-90">
            {report.definition_id}
          </span>
        </span>
      </Button>
    </>
  );
}

function RenderPanel({
  report,
  organizationId,
  onOrganizationChange,
}: {
  report: ReportDefinitionSummary;
  organizationId: string;
  onOrganizationChange: (value: string) => void;
}) {
  const id = useId();
  const [rendered, setRendered] = useState<Awaited<ReturnType<typeof api.renderReport>> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function render() {
    setBusy(true);
    setError(null);
    try {
      setRendered(await api.renderReport(report.definition_id, organizationId.trim()));
    } catch (cause) {
      setError(cause);
      setRendered(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{report.title}</CardTitle>
          <CardDescription>
            <span className="font-mono text-xs">{report.definition_id}</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-muted-foreground">Datasets</dt>
              <dd>
                {report.dataset_ids.length > 0 ? (
                  <ul className="flex flex-wrap gap-1">
                    {report.dataset_ids.map((dataset) => (
                      <li key={dataset}>
                        <Badge tone="neutral">{dataset}</Badge>
                      </li>
                    ))}
                  </ul>
                ) : (
                  "None declared"
                )}
              </dd>
            </div>
            {report.use_case?.title ? (
              <div>
                <dt className="text-muted-foreground">Use case</dt>
                <dd>
                  {report.use_case.title}
                  {report.use_case.review_status ? (
                    <Badge tone="info" className="ml-2">
                      {report.use_case.review_status}
                    </Badge>
                  ) : null}
                </dd>
              </div>
            ) : null}
            {report.use_case?.required_capabilities?.length ? (
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">Required capabilities</dt>
                <dd>
                  <ul className="flex flex-wrap gap-1">
                    {report.use_case.required_capabilities.map((capability) => (
                      <li key={capability}>
                        <Badge tone="neutral">{capability}</Badge>
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            ) : null}
          </dl>

          <form
            className="mt-4 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              void render();
            }}
          >
            <div className="flex-1">
              <Label htmlFor={`${id}-org`}>Organization id</Label>
              <Input
                id={`${id}-org`}
                value={organizationId}
                onChange={(event) => onOrganizationChange(event.target.value)}
                placeholder="org-1"
                autoComplete="off"
                className="mt-1"
                aria-describedby={`${id}-org-help`}
              />
              <p id={`${id}-org-help`} className="mt-1 text-xs text-muted-foreground">
                Report Studio is asked for the organization itself, so this render has no principal
                dimension. A self-scoped dataset contributes no rows here by design.
              </p>
            </div>
            <Button type="submit" disabled={busy || !organizationId.trim()}>
              {busy ? "Rendering\u2026" : "Render"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {error ? <ErrorNotice error={error} /> : null}

      {rendered ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">
            Organization <code className="font-mono text-xs">{rendered.organization_id}</code>{" "}
            &middot; audit <code className="font-mono text-xs">{rendered.audit_id}</code>
          </p>
          {rendered.sections.length === 0 ? (
            <EmptyState title="The render returned no sections">
              Every dataset on this definition produced nothing for that organization.
            </EmptyState>
          ) : (
            rendered.sections.map((section) => (
              <SectionCard key={section.dataset_id} section={section} />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
