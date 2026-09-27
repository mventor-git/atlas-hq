import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "../app/session";
import { AppShell, PageHeading } from "../app/shell";
import { SelfReportPage } from "./self-report";
import { capabilitySource, checkboxBody, loadProblem, roleSource, scopeProblem, SELF_SCOPE_UNAVAILABLE, type GrantTarget } from "./roles";
import type { GrantCapabilityState, GrantRoleState } from "../lib/api";

/**
 * Page smoke tests. They render against a stubbed API rather than a fixture of
 * made-up data, so every assertion is about what the console does with a real
 * response shape: it renders it, or it shows an empty state, or it shows a
 * refusal. Nothing here asserts on a value the server would not send.
 */

const SESSION = { authenticated: true as const, principal_id: "atlas.local.operator", expires_at: "" };
const THEME = { theme: "light" as const };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.location.hash = "";
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * Answer the session and theme probes, then let a page answer itself. A route
 * may answer with a promise so a test can hold a response open and prove what the
 * page does when it arrives late.
 */
function withSession(routes: Record<string, () => Response | Promise<Response>>) {
  fetchMock.mockImplementation((url: string) => {
    const path = url.split("?")[0];
    const route = routes[path];
    if (route) return route();
    if (path === "/api/session") return jsonResponse(200, SESSION);
    if (path === "/api/session/theme") return jsonResponse(200, THEME);
    // The principal directory is a real route, so a page test that does not care
    // about it still gets a real (empty) answer rather than a 404 it never stubbed.
    if (path === "/api/principals") return jsonResponse(200, { principals: [] });
    return jsonResponse(404, { error: { code: "route_unknown", message: "not found" } });
  });
}

function renderShell(ui: React.ReactElement) {
  return render(
    <SessionProvider>
      <AppShell>{ui}</AppShell>
    </SessionProvider>,
  );
}

describe("the app shell", () => {
  it("marks the current section and gives the page a focusable heading", async () => {
    withSession({});
    renderShell(<PageHeading title="Dashboard" lead="A summary." />);

    const nav = screen.getByRole("navigation", { name: "Sections" });
    await waitFor(() => {
      expect(within(nav).getByRole("link", { name: "Dashboard" })).toHaveAttribute(
        "aria-current",
        "page",
      );
    });

    const heading = screen.getByRole("heading", { level: 1, name: "Dashboard" });
    // A route change moves focus here, so a keyboard user is not left behind.
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(screen.getByText("atlas.local.operator")).toBeInTheDocument();
  });

  it("offers a light and a dark option and marks the stored one current", async () => {
    withSession({});
    renderShell(<PageHeading title="Dashboard" />);

    const light = await screen.findByRole("button", { name: /Light/ });
    const dark = await screen.findByRole("button", { name: /Dark/ });
    // The tick and aria-pressed are the non-colour signal for the current theme.
    expect(light).toHaveAttribute("aria-pressed", "true");
    expect(dark).toHaveAttribute("aria-pressed", "false");
  });
});

describe("the self monthly report page", () => {
  it("asks for the report with no principal and renders the sections Core returned", async () => {
    const report = {
      principal_id: "atlas.local.operator",
      use_case: { use_case_id: "uc.self", title: "Monthly self report" },
      audit_id: "audit.1",
      sections: [
        {
          dataset_id: "self.monthly.attendance",
          title: "Attendance",
          installed: true,
          note: "",
          columns: ["month", "hours"],
          groups: [{ key: [], count: 1, rows: [["2026-08", 160]] }],
        },
      ],
    };
    withSession({ "/api/self/monthly-report": () => jsonResponse(200, report) });
    renderShell(<SelfReportPage />);

    expect(await screen.findByRole("heading", { name: /Attendance/ })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "month" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "2026-08" })).toBeInTheDocument();

    // The request named nothing: the handle is the identity (§38.6).
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/self/monthly-report");
    expect(call).toBeDefined();
    expect((call?.[1] as RequestInit).body).toBeUndefined();
  });

  it("shows a real empty state rather than a blank page when there are no sections", async () => {
    withSession({
      "/api/self/monthly-report": () =>
        jsonResponse(200, { principal_id: "p", use_case: {}, audit_id: "a", sections: [] }),
    });
    renderShell(<SelfReportPage />);

    expect(await screen.findByText("No sections were returned")).toBeInTheDocument();
  });

  it("shows a 403 as a readable refusal, not as a blank region", async () => {
    withSession({
      "/api/self/monthly-report": () =>
        jsonResponse(403, { error: { code: "capability_denied", message: "this action is not permitted" } }),
    });
    renderShell(<SelfReportPage />);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Not permitted")).toBeInTheDocument();
    // The public code is shown; Core's decision reason never is.
    expect(within(alert).getByText("capability_denied")).toBeInTheDocument();
    expect(within(alert).getByText(/refused this action/)).toBeInTheDocument();
  });
});

describe("the roles checkbox body", () => {
  const base: GrantTarget = {
    principalId: "user.7f3",
    kind: "organization",
    organizationId: "org-1",
    workplaceId: "wp-1",
  };

  it("puts a self grant's principal at the top level, never inside scope", () => {
    const body = checkboxBody(true, { ...base, kind: "self" });
    expect(body.principal_id).toBe("user.7f3");
    expect(body.scope).not.toHaveProperty("principal_id");
  });

  it("sends only the organization for an organization grant", () => {
    const body = checkboxBody(true, base);
    expect(body.principal_id).toBeUndefined();
    expect(body.scope).toEqual({ organization_id: "org-1", workplace_id: null });
  });

  it("sends both for a workplace grant", () => {
    const body = checkboxBody(false, { ...base, kind: "workplace" });
    expect(body.scope).toEqual({ organization_id: "org-1", workplace_id: "wp-1" });
    expect(body.checked).toBe(false);
  });

  it("carries a confirmation id only when one was issued", () => {
    expect(checkboxBody(true, base, "conf_1").confirmation_id).toBe("conf_1");
    expect(checkboxBody(true, base).confirmation_id).toBeUndefined();
  });

  it("refuses to build a grant the server would reject with 422", () => {
    expect(scopeProblem({ ...base, principalId: "  " })).toMatch(/principal/i);
    expect(scopeProblem({ ...base, kind: "organization", organizationId: "" })).toMatch(/organization/i);
    expect(scopeProblem({ ...base, kind: "workplace", workplaceId: "" })).toMatch(/workplace/i);
    expect(scopeProblem(base)).toBeNull();
  });

  it("will not read a self scope, because the server reports none", () => {
    expect(loadProblem({ ...base, kind: "self" })).toMatch(/own scope/i);
    expect(loadProblem(base)).toBeNull();
  });

  it("blocks a self grant in the save path too, not only in the read path", () => {
    // The picker disables the option, so this is the second lock: even a
    // self-scoped target that reached the rows could not be written.
    expect(scopeProblem({ ...base, kind: "self" })).toBe(SELF_SCOPE_UNAVAILABLE);
  });
});

describe("reading a checkbox source", () => {
  const direct: GrantCapabilityState = { capability_id: "a", direct: true, role_ids: [] };
  const viaRole: GrantCapabilityState = { capability_id: "b", direct: false, role_ids: ["role.payroll"] };
  const both: GrantCapabilityState = { capability_id: "c", direct: true, role_ids: ["role.payroll"] };
  const grants = {
    principal_id: "user.7f3",
    scope: { organization_id: "org-1", workplace_id: null, principal_id: null },
    capabilities: [direct, viaRole, both],
    roles: [{ role_id: "role.payroll", assigned: true } satisfies GrantRoleState],
    effective_capability_ids: ["a", "b", "c"],
  };

  it("names the source in words: direct, via role, or both", () => {
    expect(capabilitySource(grants, "a").source).toBe("direct");
    expect(capabilitySource(grants, "b").source).toBe("via role role.payroll");
    expect(capabilitySource(grants, "c").source).toBe("direct and via role role.payroll");
  });

  it("counts a role-provided capability as held, and an unheld one as not", () => {
    expect(capabilitySource(grants, "b").granted).toBe(true);
    expect(capabilitySource(grants, "zzz")).toEqual({
      granted: false,
      source: "Not reported by Core",
      reported: true,
    });
    expect(roleSource(grants, "role.payroll")).toEqual({
      granted: true,
      source: "assigned",
      reported: true,
    });
  });

  it("admits when nothing has been read, rather than claiming nothing is held", () => {
    expect(capabilitySource(null, "a")).toEqual({
      granted: false,
      source: "Not loaded yet",
      reported: false,
    });
  });
});

describe("the principal picker", () => {
  it("selects a principal from the Core directory and marks an inactive one", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/principals": () =>
        jsonResponse(200, {
          principals: [
            { principal_id: "atlas.local.operator", display_name: "Local operator", active: true },
            { principal_id: "user.retired", display_name: "Retired account", active: false },
          ],
        }),
      "/api/capabilities": () => jsonResponse(200, { capabilities: [] }),
      "/api/roles": () => jsonResponse(200, { roles: [] }),
      "/api/principals/user.retired/grants": () =>
        jsonResponse(200, {
          principal_id: "user.retired",
          scope: { organization_id: "org-1", workplace_id: null, principal_id: null },
          capabilities: [],
          roles: [],
          effective_capability_ids: [],
        }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    const picker = await screen.findByLabelText("Principal");
    // Inactive is stated in words, not only in a style (§39.3).
    expect(within(picker).getByRole("option", { name: /Retired account.*inactive/i })).toBeInTheDocument();

    await user.selectOptions(picker, "user.retired");
    // The chosen id is the one every later call is about.
    expect(screen.getByLabelText("Principal id")).toHaveValue("user.retired");

    await user.type(screen.getByLabelText("Organization id"), "org-1");
    await user.click(screen.getByRole("button", { name: /Load grant state/ }));
    expect(await screen.findByText("Effective capabilities for user.retired")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).startsWith("/api/principals/user.retired/grants"),
    );
    expect(call).toBeDefined();
  });

  it("still says so in words when the directory cannot be read", async () => {
    withSession({ "/api/principals": () => jsonResponse(403, { error: { code: "capability_denied", message: "this action is not permitted" } }) });
    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
    // The typed field stays, so a principal id can still be entered and verified.
    expect(screen.getByLabelText("Principal id")).toBeInTheDocument();
  });
});

/** One `GET /api/principals/{id}/grants` answer, in the server's shape. */
function grantState(
  capabilities: GrantCapabilityState[] = [],
  roles: GrantRoleState[] = [],
  organizationId: string | null = "org-1",
) {
  return {
    principal_id: "user.7f3",
    scope: { organization_id: organizationId, workplace_id: null, principal_id: null },
    capabilities,
    roles,
    effective_capability_ids: capabilities.filter((item) => item.direct || item.role_ids.length > 0).map((item) => item.capability_id),
  };
}

const CAPABILITY_CATALOGUE = {
  capabilities: [
    { capability_id: "attendance.record", kind: "manage", name: "Record attendance", provider_id: "attendance_operations" },
    { capability_id: "payroll.read", kind: "view", name: "Read payroll", provider_id: "employee_finance" },
  ],
};

const ROLE_CATALOGUE = {
  roles: [{ role_id: "role.payroll", name: "Payroll reader", capabilities: ["payroll.read"], owner_plugin_id: null }],
};

/** Fill in a subject and an organization scope, then read the grant state. */
async function loadGrants(user: ReturnType<typeof userEvent.setup>, principalId = "user.7f3") {
  await user.type(await screen.findByLabelText("Principal id"), principalId);
  await user.type(screen.getByLabelText("Organization id"), "org-1");
  await user.click(screen.getByRole("button", { name: /Load grant state/ }));
}

describe("hydrating the checkboxes from grant state", () => {
  it("ticks a box for a direct grant and a box for a role, and names each source", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(
          200,
          grantState(
            [
              { capability_id: "attendance.record", direct: true, role_ids: [] },
              { capability_id: "payroll.read", direct: true, role_ids: ["role.payroll"] },
            ],
            [{ role_id: "role.payroll", assigned: true }],
          ),
        ),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    const attendance = await screen.findByRole("checkbox", { name: "Record attendance" });
    // Before the read, a box may not claim anything about what is held.
    expect(attendance).not.toBeChecked();
    expect(attendance).toBeDisabled();

    await loadGrants(user);

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: "Record attendance" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "Read payroll" })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: "Payroll reader" })).toBeChecked();
    });

    // The source is words, wired to the box with aria-describedby so it is read
    // out with the control rather than only drawn beside it.
    const source = (name: string) =>
      document.getElementById(screen.getByRole("checkbox", { name }).getAttribute("aria-describedby") as string);
    expect(source("Record attendance")).toHaveTextContent("direct");
    expect(source("Read payroll")).toHaveTextContent("direct and via role role.payroll");
    expect(source("Payroll reader")).toHaveTextContent("assigned");

    // A capability no source grants stays empty and says so.
    const none = screen.getByRole("checkbox", { name: "Record attendance" });
    expect(none).toBeEnabled();
  });

  it("leaves an unheld capability and role unticked and labels them not granted", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(
          200,
          grantState(
            [
              { capability_id: "payroll.read", direct: false, role_ids: ["role.payroll"] },
              { capability_id: "attendance.record", direct: false, role_ids: [] },
            ],
            [{ role_id: "role.payroll", assigned: false }],
          ),
        ),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Read payroll" })).toBeEnabled());
    expect(screen.getByRole("checkbox", { name: "Read payroll" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Payroll reader" })).not.toBeChecked();
    // The whole catalogue gets a box, held or not.
    expect(screen.getByText("not granted")).toBeInTheDocument();
    expect(screen.getByText("not assigned")).toBeInTheDocument();
  });

  it("summarises the effective capabilities with their source", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(
          200,
          grantState(
            [
              { capability_id: "attendance.record", direct: true, role_ids: [] },
              { capability_id: "payroll.read", direct: false, role_ids: ["role.payroll"] },
            ],
            [{ role_id: "role.payroll", assigned: true }],
          ),
        ),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    expect(await screen.findByText("Effective capabilities for user.7f3")).toBeInTheDocument();
    // 2 effective, 1 direct, 1 via a role, 1 role assigned — counted in words.
    expect(screen.getByText(/2 effective capabilities/)).toHaveTextContent("1 granted directly");
    expect(screen.getByText(/2 effective capabilities/)).toHaveTextContent("1 granted by a role");
    const table = screen.getByRole("table");
    expect(within(table).getByRole("cell", { name: "attendance.record" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "via role role.payroll" })).toBeInTheDocument();
  });

  it("reports an unknown principal as not found and ticks nothing", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.ghost/grants": () =>
        jsonResponse(404, { error: { code: "principal_unknown", message: "not found" } }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user, "user.ghost");

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Not found")).toBeInTheDocument();
    expect(within(alert).getByText("principal_unknown")).toBeInTheDocument();
    // No report means no claim: nothing is ticked and the boxes stay disabled.
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).toBeDisabled();
    expect(screen.queryByText("Effective capabilities for user.ghost")).not.toBeInTheDocument();
  });

  it("retires the report when the scope changes, so it cannot describe another scope", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(
          200,
          grantState([{ capability_id: "attendance.record", direct: true, role_ids: [] }], []),
        ),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);
    expect(await screen.findByRole("checkbox", { name: "Record attendance" })).toBeChecked();

    await user.selectOptions(screen.getByLabelText("Grant scope"), "workplace");
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).not.toBeChecked();
    expect(screen.queryByText("Effective capabilities for user.7f3")).not.toBeInTheDocument();
  });

  it("marks the grant region busy while a read is in flight and offers a retry when it fails", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    let releaseGrants: (response: Response) => void = () => {};
    const inFlight = new Promise<Response>((resolve) => {
      releaseGrants = resolve;
    });
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => {
        attempts += 1;
        return attempts === 1
          ? inFlight
          : jsonResponse(200, grantState([{ capability_id: "attendance.record", direct: true, role_ids: [] }]));
      },
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    await user.type(await screen.findByLabelText("Principal id"), "user.7f3");
    await user.type(screen.getByLabelText("Organization id"), "org-1");
    await user.click(screen.getByRole("button", { name: /Load grant state/ }));

    // The whole page body is the region: every box and the summary is
    // provisional while a read is outstanding.
    await waitFor(() => expect(document.querySelector("[aria-busy]")).toHaveAttribute("aria-busy", "true"));

    // A refusal is retryable in place, and the retry asks the same question.
    releaseGrants(jsonResponse(403, { error: { code: "capability_denied", message: "not permitted" } }));
    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
    expect(document.querySelector("[aria-busy]")).toHaveAttribute("aria-busy", "false");

    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("checkbox", { name: "Record attendance" })).toBeChecked();
    expect(attempts).toBe(2);
    expect(document.querySelector("[aria-busy]")).toHaveAttribute("aria-busy", "false");
  });

  it("discards a read that answers after the operator has moved to another principal", async () => {
    const user = userEvent.setup();
    let releaseFirst: (response: Response) => void = () => {};
    const first = new Promise<Response>((resolve) => {
      releaseFirst = resolve;
    });
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      // The first subject's read never arrives until this test says so.
      "/api/principals/user.7f3/grants": () => first,
      "/api/principals/user.7f8/grants": () =>
        jsonResponse(200, {
          ...grantState(),
          principal_id: "user.7f8",
          capabilities: [{ capability_id: "payroll.read", direct: true, role_ids: [] }],
          effective_capability_ids: ["payroll.read"],
        }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    const field = await screen.findByLabelText("Principal id");
    await user.type(field, "user.7f3");
    await user.type(screen.getByLabelText("Organization id"), "org-1");
    await user.click(screen.getByRole("button", { name: /Load grant state/ }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("user.7f3/grants"))).toBe(true),
    );

    // Move to the other subject while the first read is still outstanding.
    await user.clear(field);
    await user.type(field, "user.7f8");
    await user.click(screen.getByRole("button", { name: /Load grant state/ }));
    expect(await screen.findByText("Effective capabilities for user.7f8")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Read payroll" })).toBeChecked());
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).not.toBeChecked();

    // The first read finally answers, carrying the *other* subject's state. It
    // must not be drawn: the selection has moved on and the report is stale.
    releaseFirst(
      jsonResponse(200, {
        ...grantState([{ capability_id: "attendance.record", direct: true, role_ids: [] }]),
        principal_id: "user.7f3",
      }),
    );
    await waitFor(() => expect(screen.getByText("Effective capabilities for user.7f8")).toBeInTheDocument());
    expect(screen.queryByText("Effective capabilities for user.7f3")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Read payroll" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).not.toBeChecked();
  });

  it("drops a pending confirmation when the target changes, so it cannot be applied elsewhere", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState()),
      "/api/principals/user.7f8/grants": () => jsonResponse(200, grantState([], [], "org-1")),
      "/api/principals/user.7f3/capabilities/payroll.read": () =>
        jsonResponse(403, { error: { code: "confirmation_required", message: "not permitted" } }),
      "/api/confirmations": () => jsonResponse(201, { confirmation_id: "conf_7f3" }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);
    const prompt = await screen.findByText("This change needs a confirmation");
    const region = prompt.closest("[data-slot=alert]") as HTMLElement;
    expect(within(region).getByText(/Read payroll for/)).toHaveTextContent("user.7f3");

    // Switch subject while the question is open.
    const field = screen.getByLabelText("Principal id");
    await user.clear(field);
    await user.type(field, "user.7f8");

    // The question is gone rather than left to be answered for a new principal:
    // a confirmation is bound to the target it was asked about.
    await waitFor(() => expect(screen.queryByText("This change needs a confirmation")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Confirm and retry" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/confirmations")).toBe(false);
    // The optimistic tick went with it, and the new target says what it can prove.
    expect(screen.getByRole("checkbox", { name: "Read payroll" })).not.toBeChecked();
    expect(await screen.findAllByText(/Load the grant state before changing it/)).not.toHaveLength(0);
  });

  it("sends the selected organization and workplace to the grant state read", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState([], [], "org-1")),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    await user.type(await screen.findByLabelText("Principal id"), "user.7f3");
    await user.selectOptions(screen.getByLabelText("Grant scope"), "workplace");
    await user.type(screen.getByLabelText("Organization id"), "org-1");
    await user.type(screen.getByLabelText("Workplace id"), "wp-1");
    await user.click(screen.getByRole("button", { name: /Load grant state/ }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/grants"));
      expect(call?.[0]).toBe("/api/principals/user.7f3/grants?organization_id=org-1&workplace_id=wp-1");
    });
    // The read is a GET with no body, and the principal is the resource in the
    // path rather than a fact in the request.
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/grants"));
    expect((call?.[1] as RequestInit).body).toBeUndefined();
  });

  it("offers no self scope, explains why in words, and sends no self grant", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState()),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    const scope = await screen.findByLabelText("Grant scope");
    // Offered, disabled, and labelled as unavailable — hidden would leave its
    // absence unexplained.
    const self = within(scope).getByRole("option", { name: /Self \(this principal\)/ });
    expect(self).toBeDisabled();
    expect(self).toHaveTextContent("not available yet");

    // The reason is words, not a style, and it is wired to the control with
    // aria-describedby so it is announced with the scope.
    const note = document.getElementById(scope.getAttribute("aria-describedby") as string);
    expect(note).toHaveTextContent(/no grant state for a principal's own scope/i);
    expect(scope).toHaveAccessibleDescription(/no grant state for a principal's own scope/i);

    // And the boxes are not offered as if they knew anything.
    await user.type(screen.getByLabelText("Principal id"), "user.7f3");
    await user.type(screen.getByLabelText("Organization id"), "org-1");
    expect(await screen.findAllByText(/Load the grant state before changing it/)).not.toHaveLength(0);
    expect(screen.getByRole("checkbox", { name: "Record attendance" })).toBeDisabled();
  });

  it("never puts a principal in a grant body, because self scope cannot be used", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState()),
      "/api/principals/user.7f3/capabilities/attendance.record": () =>
        jsonResponse(200, { capability_id: "attendance.record", checked: true }),
      "/api/principals/user.7f3/roles/role.payroll": () =>
        jsonResponse(200, { role_id: "role.payroll", assigned: true }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    await user.click(screen.getByRole("checkbox", { name: "Record attendance" }));
    await waitFor(() => expect(screen.getByText(/Core accepted the change/)).toBeInTheDocument());
    await user.click(screen.getByRole("checkbox", { name: "Payroll reader" }));
    await waitFor(() => expect(screen.getAllByText(/Core accepted the change/)).toHaveLength(2));

    // A management grant names its scope, never the subject, on both routes.
    const writes = fetchMock.mock.calls.filter(([url]) => /\/(capabilities|roles)\//.test(String(url)));
    expect(writes).toHaveLength(2);
    for (const [, init] of writes) {
      const body = JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;
      expect(body.principal_id).toBeUndefined();
      expect(body.scope).toEqual({ organization_id: "org-1", workplace_id: null });
    }
  });
});

describe("saving a grant", () => {
  it("sends the Core-shaped body and reports what the server actually said", async () => {
    const user = userEvent.setup();
    let granted = false;
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(200, grantState([{ capability_id: "attendance.record", direct: granted, role_ids: [] }])),
      "/api/principals/user.7f3/capabilities/attendance.record": () => {
        granted = true;
        return jsonResponse(200, { capability_id: "attendance.record", checked: true });
      },
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Record attendance" });
    await user.click(box);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) =>
        String(url).endsWith("/api/principals/user.7f3/capabilities/attendance.record"),
      );
      expect(call).toBeDefined();
      // The organization scope travels with the change, and no confirmation is
      // sent when none was issued.
      expect(JSON.parse((call?.[1] as RequestInit).body as string)).toEqual({
        checked: true,
        scope: { organization_id: "org-1", workplace_id: null },
      });
    });
    expect(await screen.findByText(/Core accepted the change/)).toBeInTheDocument();
    expect(box).toBeChecked();
  });

  it("rolls the box back and says why when the roles engine refuses", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState()),
      "/api/principals/user.7f3/capabilities/payroll.read": () =>
        jsonResponse(403, { error: { code: "capability_denied", message: "this action is not permitted" } }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);

    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
    // A refused save never leaves a box showing a change the server refused.
    expect(box).not.toBeChecked();
  });

  it("rolls a revocation back when the server refuses it", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () =>
        jsonResponse(200, grantState([{ capability_id: "payroll.read", direct: true, role_ids: [] }])),
      "/api/principals/user.7f3/capabilities/payroll.read": () =>
        jsonResponse(403, { error: { code: "policy_denied", message: "this action is not permitted" } }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    expect(await screen.findByRole("checkbox", { name: "Read payroll" })).toBeChecked();
    await user.click(box);

    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
    expect(box).toBeChecked();
  });

  it("keeps the boxes disabled until a principal is named", async () => {
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);

    expect(await screen.findByRole("checkbox", { name: "Record attendance" })).toBeDisabled();
  });
});

describe("a confirmation-required policy", () => {
  /** The routes one capability needs, refusing the first attempt. */
  function confirmationRoutes(
    capability: Pick<GrantCapabilityState, "direct">,
    afterFirst: (attempt: number) => Response,
    onSave: () => void = () => {},
  ) {
    let attempts = 0;
    return {
      routes: {
        "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
        "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
        "/api/principals/user.7f3/grants": () =>
          jsonResponse(200, grantState([{ capability_id: "payroll.read", role_ids: [], ...capability }])),
        "/api/principals/user.7f3/capabilities/payroll.read": () => {
          attempts += 1;
          if (attempts === 1) {
            return jsonResponse(403, {
              error: { code: "confirmation_required", message: "this action is not permitted" },
            });
          }
          const response = afterFirst(attempts);
          if (response.status === 200) onSave();
          return response;
        },
        "/api/confirmations": () => jsonResponse(201, { confirmation_id: "conf_7f3" }),
      },
      attempts: () => attempts,
    };
  }

  it("asks for a bound confirmation, then retries the same change with it", async () => {
    const user = userEvent.setup();
    const held = { direct: false };
    const { routes, attempts } = confirmationRoutes(held, () => jsonResponse(200, { capability_id: "payroll.read", checked: true }), () => {
      held.direct = true;
    });
    withSession(routes);

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);

    // The prompt names the capability, the action, and the target, because that
    // is exactly what Core binds the confirmation to.
    const prompt = await screen.findByText("This change needs a confirmation");
    const region = prompt.closest("[data-slot=alert]") as HTMLElement;
    expect(within(region).getByText("authorization.manage")).toBeInTheDocument();
    expect(within(region).getByText("authorization.capability.set")).toBeInTheDocument();
    expect(within(region).getByText(/Read payroll for/)).toHaveTextContent("user.7f3");
    expect(within(region).getByText(/Read payroll for/)).toHaveTextContent("org-1 / no workplace");
    // The answer is where the keyboard is.
    expect(document.activeElement).toBe(within(region).getByRole("button", { name: "Confirm and retry" }));

    await user.click(within(region).getByRole("button", { name: "Confirm and retry" }));

    expect(await screen.findByText(/Core accepted the change/)).toBeInTheDocument();
    expect(box).toBeChecked();
    expect(attempts()).toBe(2);

    // The confirmation names the target, so it cannot be replayed on another.
    const confirmation = fetchMock.mock.calls.find(([url]) => url === "/api/confirmations");
    expect(JSON.parse((confirmation?.[1] as RequestInit).body as string)).toEqual({
      capability: "authorization.manage",
      action: "authorization.capability.set",
      scope: { organization_id: "org-1", workplace_id: null },
      resource_id: "user.7f3",
    });

    // The retry is the same change, carrying the confirmation Core issued.
    const retry = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith("/api/principals/user.7f3/capabilities/payroll.read"),
    );
    expect(JSON.parse((retry[1][1] as RequestInit).body as string)).toEqual({
      checked: true,
      scope: { organization_id: "org-1", workplace_id: null },
      confirmation_id: "conf_7f3",
    });
    // A role change asks for the role action, not the capability one.
    expect(
      fetchMock.mock.calls.filter(([url]) => url === "/api/confirmations"),
    ).toHaveLength(1);
  });

  it("restores the box and gives a reason when the change is declined", async () => {
    const user = userEvent.setup();
    const { routes } = confirmationRoutes({ direct: false }, () => jsonResponse(200, {}));
    withSession(routes);

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);
    const prompt = await screen.findByText("This change needs a confirmation");
    const region = prompt.closest("[data-slot=alert]") as HTMLElement;

    await user.click(within(region).getByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Declined. Nothing was changed.")).toBeInTheDocument();
    expect(box).not.toBeChecked();
    // Declining asks Core for nothing.
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/confirmations")).toBe(false);
    // Focus comes back to the box the user was working with.
    expect(document.activeElement).toBe(box);
  });

  it("restores the box and says so when the confirmation is already consumed", async () => {
    const user = userEvent.setup();
    const { routes } = confirmationRoutes({ direct: false }, () =>
      jsonResponse(409, { error: { code: "confirmation_consumed", message: "the request conflicts with the current state" } }),
    );
    withSession(routes);

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);
    const prompt = await screen.findByText("This change needs a confirmation");
    await user.click(
      within(prompt.closest("[data-slot=alert]") as HTMLElement).getByRole("button", { name: "Confirm and retry" }),
    );

    expect(await screen.findByText("Already used")).toBeInTheDocument();
    expect(screen.getByText("confirmation_consumed")).toBeInTheDocument();
    expect(box).not.toBeChecked();
    expect(screen.queryByText("This change needs a confirmation")).not.toBeInTheDocument();
  });

  it("does not ask twice when the retry is refused again", async () => {
    const user = userEvent.setup();
    const { routes, attempts } = confirmationRoutes({ direct: false }, () =>
      jsonResponse(403, { error: { code: "confirmation_required", message: "this action is not permitted" } }),
    );
    withSession(routes);

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    const box = screen.getByRole("checkbox", { name: "Read payroll" });
    await user.click(box);
    const prompt = await screen.findByText("This change needs a confirmation");
    await user.click(
      within(prompt.closest("[data-slot=alert]") as HTMLElement).getByRole("button", { name: "Confirm and retry" }),
    );

    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
    expect(attempts()).toBe(2);
    expect(screen.queryByText("This change needs a confirmation")).not.toBeInTheDocument();
    expect(box).not.toBeChecked();
  });

  it("asks for the role action when the changed box is a role", async () => {
    const user = userEvent.setup();
    withSession({
      "/api/capabilities": () => jsonResponse(200, CAPABILITY_CATALOGUE),
      "/api/roles": () => jsonResponse(200, ROLE_CATALOGUE),
      "/api/principals/user.7f3/grants": () => jsonResponse(200, grantState([], [{ role_id: "role.payroll", assigned: false }])),
      "/api/principals/user.7f3/roles/role.payroll": () =>
        jsonResponse(403, { error: { code: "confirmation_required", message: "this action is not permitted" } }),
      "/api/confirmations": () => jsonResponse(201, { confirmation_id: "conf_role" }),
    });

    const { RolesPage } = await import("./roles");
    renderShell(<RolesPage />);
    await loadGrants(user);

    await user.click(screen.getByRole("checkbox", { name: "Payroll reader" }));
    const prompt = await screen.findByText("This change needs a confirmation");
    const region = prompt.closest("[data-slot=alert]") as HTMLElement;
    expect(within(region).getByText("authorization.role.set")).toBeInTheDocument();
    expect(within(region).getByText(/Payroll reader for/)).toHaveTextContent("user.7f3");
  });
});
