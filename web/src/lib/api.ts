/**
 * The whole browser-side view of the server.
 *
 * The browser holds exactly one credential: the opaque `atlas_session`
 * cookie, sent automatically by `credentials: "include"`. There is no token
 * here, no principal in any request body, no capability handle, and no unit of
 * work. `atlas_web` is the only thing this file talks to, and the roles engine
 * on the server stays authoritative: nothing in here decides, caches, or
 * predicts a permission.
 */

const BASE = "/api";

export type Theme = "light" | "dark";

/** A refusal from the server, carrying the status and the public code only. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  /** A dead or absent session. The only case worth re-authenticating for. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  /** Serialised as JSON. `undefined` sends no body at all. */
  body?: unknown;
  query?: Record<string, string | undefined>;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    // An empty scope is a scope the caller did not name. Sending it as a blank
    // query parameter would ask Core about a scope nobody chose.
    if (value) query.set(key, value);
  }
  const search = query.toString();
  const url = `${BASE}${path}${search ? `?${search}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? "GET",
      credentials: "include",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (cause) {
    throw new NetworkError("the Atlas API could not be reached");
  }

  if (response.status === 204) return undefined as T;

  const raw = await response.text();
  let payload: unknown = {};
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = {};
    }
  }

  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } }).error;
    throw new ApiError(
      response.status,
      error?.code ?? "unknown",
      error?.message ?? "the request could not be completed",
    );
  }
  return payload as T;
}

// --- wire types, mirroring src/atlas_web/service.py -------------------------

export type SessionInfo = { authenticated: true; principal_id: string; expires_at: string };
export type LoginResult = {
  authenticated: true;
  principal_id: string;
  development_only: boolean;
};

export type Capability = {
  capability_id: string;
  kind: string;
  name: string;
  provider_id: string;
};

export type Role = {
  role_id: string;
  name: string;
  capabilities: string[];
  owner_plugin_id: string | null;
};

/**
 * One entry of the principal directory: enough to pick a subject, and nothing
 * else. A principal's stored metadata (its theme preference) is a preference
 * rather than an identity fact, so it is not on the wire.
 */
export type Principal = {
  principal_id: string;
  display_name: string;
  active: boolean;
};

/**
 * The grant scope as the checkbox body carries it: organization and workplace
 * only. A `principal_id` nested here is refused with 422 `scope_invalid`, so it
 * is not even expressible in this type.
 */
export type GrantScope = {
  organization_id?: string | null;
  workplace_id?: string | null;
};

/**
 * The management checkbox body.
 *
 * A self-scoped grant adds a *top-level* `principal_id`. Keeping it out of
 * `GrantScope` is what stops a caller from nesting it by accident, which is
 * the mistake the server is built to refuse.
 */
export type CheckboxRequest = {
  checked: boolean;
  scope: GrantScope;
  principal_id?: string;
  confirmation_id?: string;
};

export type EffectivePermissions = {
  principal_id: string;
  scope: { organization_id: string | null; workplace_id: string | null; principal_id: string | null };
  capabilities: string[];
  direct_capabilities: string[];
  role_ids: string[];
};

/**
 * One capability's state at the reported scope: the explicit audited grant, and
 * the roles that also carry it. Together they are the capability's sources, which
 * is what explains why unticking a box did not remove the permission.
 */
export type GrantCapabilityState = {
  capability_id: string;
  direct: boolean;
  role_ids: string[];
};

/** One role's state at the reported scope. `assigned` is false for an unheld role. */
export type GrantRoleState = { role_id: string; assigned: boolean };

/**
 * Every capability's and role's state for one subject in one named scope, in a
 * single read. This is what the management view hydrates its checkboxes from, so
 * an empty box means Core reports nothing held rather than that nothing was asked.
 *
 * The scope is explicit on the server: naming no organization or workplace is
 * `422 scope_invalid` rather than an answer for every scope at once. The reported
 * scope carries no principal dimension, so this is a management view of an
 * organization and never a peek at somebody's self scope.
 */
export type GrantState = {
  principal_id: string;
  scope: { organization_id: string | null; workplace_id: string | null; principal_id: string | null };
  capabilities: GrantCapabilityState[];
  roles: GrantRoleState[];
  effective_capability_ids: string[];
};

export type UseCase = {
  use_case_id: string;
  title: string;
  summary: string;
  owner: string;
  audience: string;
  scope: string;
  date_grain: string;
  required_capabilities: string[];
  surfaces: string[];
  review_status: string;
  version: string;
};

export type ReportGroup = { key: (string | number | null)[]; count: number; rows: (string | number | null)[][] };
export type ReportSection = {
  dataset_id: string;
  title: string;
  installed: boolean;
  note: string;
  columns: string[];
  groups: ReportGroup[];
};

export type ReportDefinitionSummary = {
  definition_id: string;
  title: string;
  dataset_ids: string[];
  use_case: Partial<UseCase>;
};

export type SelfMonthlyReport = {
  principal_id: string;
  use_case: Partial<UseCase>;
  sections: ReportSection[];
  audit_id: string;
};

// --- routes ----------------------------------------------------------------

export const api = {
  /**
   * The development login. The body is empty and is read by nobody: the
   * operator is server configuration. Returns 404 `login_disabled` unless
   * ATLAS_WEB_DEV_LOGIN is on, and 503 if no operator is configured.
   */
  login: () => request<LoginResult>("/session", { method: "POST" }),

  session: () => request<SessionInfo>("/session"),

  logout: () => request<void>("/session", { method: "DELETE" }),

  theme: {
    get: () => request<{ theme: Theme }>("/session/theme"),
    put: (theme: Theme) => request<{ theme: Theme }>("/session/theme", { method: "PUT", body: { theme } }),
  },

  capabilities: () => request<{ capabilities: Capability[] }>("/capabilities"),

  roles: () => request<{ roles: Role[] }>("/roles"),

  /**
   * The principal directory, as Core holds it. Read-only and self-authorized: the
   * caller's own session decides it, exactly as the two catalogues above do.
   */
  principals: () => request<{ principals: Principal[] }>("/principals"),

  /**
   * The subject's effective permissions as Core computed them, for the
   * organization/workplace named here. The principal is the *resource*, never
   * a scope dimension, so it travels in the path.
   */
  permissions: (principalId: string, scope: { organization_id?: string; workplace_id?: string }) =>
    request<EffectivePermissions>(`/principals/${encodeURIComponent(principalId)}/permissions`, {
      query: scope,
    }),

  setCapability: (principalId: string, capabilityId: string, body: CheckboxRequest) =>
    request<{ capability_id: string; checked: boolean }>(
      `/principals/${encodeURIComponent(principalId)}/capabilities/${encodeURIComponent(capabilityId)}`,
      { method: "PUT", body },
    ),

  setRole: (principalId: string, roleId: string, body: CheckboxRequest) =>
    request<{ role_id: string; checked: boolean }>(
      `/principals/${encodeURIComponent(principalId)}/roles/${encodeURIComponent(roleId)}`,
      { method: "PUT", body },
    ),

  /**
   * Every capability's and role's checkbox state for one subject, in the
   * organization/workplace scope named here. The principal is the *resource*
   * being reported on, never a scope dimension, so it travels in the path and
   * the named scope travels in the query.
   */
  grants: (principalId: string, scope: { organization_id?: string; workplace_id?: string }) =>
    request<GrantState>(`/principals/${encodeURIComponent(principalId)}/grants`, { query: scope }),

  reports: () => request<{ reports: ReportDefinitionSummary[] }>("/reports"),

  /**
   * Report Studio is asked for an organization and nothing else, so the body
   * carries exactly `organization_id`. The handle's scope is the server's.
   */
  renderReport: (definitionId: string, organizationId: string) =>
    request<{ definition_id: string; organization_id: string; sections: ReportSection[]; audit_id: string }>(
      `/reports/${encodeURIComponent(definitionId)}/render`,
      { method: "POST", body: { organization_id: organizationId } },
    ),

  /**
   * The session principal's own monthly report. No principal, actor, channel,
   * or scope is accepted, so none is sent: the server refuses any of them with
   * 422 `principal_not_accepted` (§38.6).
   */
  selfMonthlyReport: () => request<SelfMonthlyReport>("/self/monthly-report"),

  /**
   * Ask Core for a typed, one-time confirmation of a pending action.
   *
   * `resource_id` is required and is part of the binding, not a hint: it is the
   * target the action is about — the `{id}` of the principal whose grant is about
   * to change — and Core stores it on the confirmation. Consumption needs the
   * executing handle to resolve to that same target, so omitting it does not
   * produce a wildcard: a confirmation with no target matches only an execution
   * that has no target either.
   */
  confirmation: (body: {
    capability: string;
    action: string;
    scope: GrantScope;
    resource_id: string;
  }) => request<{ confirmation_id: string }>("/confirmations", { method: "POST", body }),
};

export type Api = typeof api;
