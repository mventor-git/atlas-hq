# WEB API — the server boundary for the Atlas-HQ console

`src/atlas_web/` is the backend slice for the future shadcn/ui console. It is a
framework-agnostic service plus a standard-library HTTP adapter. It adds no web
framework and no frontend asset; a future framework adapter calls the same
`WebAppService.handle`.

It is **not** an authorization layer. It is a place where an HTTP request meets
the Core Roles Engine, and its only contribution to a decision is turning a Core
decision code into an HTTP status.

## The three rules

1. **The browser never holds an `ExecutionHandle`.** A login mints an opaque,
   random, server-side session id. The browser receives only that id, in an
   `HttpOnly; SameSite=Strict` cookie. The handle stays in the server's session
   store and is never serialized into a response.
2. **The web layer is not an evaluator.** Each request resolves the session's
   Core handle, asks Core to issue *that request's* handle, and has Core decide
   through `AuthorizationService.authorize`. There is no permission table, no
   second policy pass, and no `allowed = ...` in this package.
3. **A payload is never a fact.** Identity, channel, action, and the principal
   dimension of the execution scope come from Core. A caller-supplied actor,
   principal, channel, or policy context is refused, and `GET
   /api/self/monthly-report` accepts no principal at all.

## Session flow

```text
POST /api/session
  server reads ATLAS_WEB_OPERATOR_PRINCIPAL (config, never the request)
  server reads ATLAS_WEB_DEV_LOGIN        (the route is off without it)
  Core issues one handle for the active operator principal
  server stores {session_id -> handle, principal, expires_at}
  -> 201 + Set-Cookie: atlas_session=<opaque>; HttpOnly; SameSite=Strict

every later request
  cookie -> session record          (missing/unknown/revoked/expired -> 401)
  session handle -> Core            (re-resolved every request; dead -> 401)
  principal re-read from Core       (never from the request)
  Core issues this request's handle (capability, action, scope, channel=web)
  Core authorizes it                 (decision + mutation in ONE transaction)
  response carries no handle, no token, no UoW, no plugin internals

DELETE /api/session
  session marked revoked, Core handle revoked -> 204 + cleared cookie
  the id is refused from that moment, not at its expiry
```

Session handles live an hour; each request's own handle lives 60 seconds and
never leaves the server. A request handle is committed *before* the body runs
for the plugin routes, because a plugin owns its own transaction and has to be
able to resolve the handle Core just issued. The management routes keep the
handle, the decision, and the mutation in a single unit of work (contract
§38.11). A denied decision rolls that transaction back, and the durable denial
audit still commits through Core's independent unit of work.

## Routes

| Method | Path | Capability | Action |
| --- | --- | --- | --- |
| POST | `/api/session` | — (dev login) | — |
| GET | `/api/session` | — (live session) | — |
| DELETE | `/api/session` | — (live session) | — |
| GET/PUT | `/api/session/theme` | — (live session) | — |
| GET | `/api/capabilities` | `authorization.manage` | `authorization.catalogue.read` |
| GET | `/api/roles` | `authorization.manage` | `authorization.catalogue.read` |
| GET | `/api/principals` | `authorization.manage` | `authorization.principal.read` |
| GET | `/api/principals/{id}/permissions?organization_id=&workplace_id=` | `authorization.manage` | `authorization.principal.read` |
| GET | `/api/principals/{id}/grants?organization_id=&workplace_id=` | `authorization.manage` | `authorization.principal.read` |
| PUT | `/api/principals/{id}/capabilities/{capability}` | `authorization.manage` | `authorization.capability.set` |
| PUT | `/api/principals/{id}/roles/{role_id}` | `authorization.manage` | `authorization.role.set` |
| GET | `/api/reports` | `authorization.manage` | `authorization.catalogue.read` |
| POST | `/api/reports/{definition_id}/render` | `report.render` + the use case's own | `report.render` |
| GET | `/api/self/monthly-report` | `self.monthly.report.view` | `self.monthly.report.view` |
| POST | `/api/confirmations` | the named capability | the named action |

`authorization.manage` (`CapabilityKind.MANAGE`) is a new Core capability. It is
seeded like any other Core capability and belongs to no role, so a principal must
be granted it explicitly before any channel's management surface answers.

### The principal directory

`GET /api/principals` is the third Core-owned catalogue, beside the capability
and role lists, and it is authorized the same way: a live session, one request
handle, one Core decision on `authorization.manage` in the caller's own scope. It
exists so the console can offer a picker instead of a free-text id.

It is a **directory, not a view**: it names no principal, accepts none from the
caller (a query naming `principal_id`, `actor`, `identity_id`, `channel`,
`scope`, `subject_id`, or `user_id` is refused with
`422 principal_not_accepted`), and it projects only `principal_id`,
`display_name`, and `active`. A principal's stored metadata — the theme
preference — is a preference rather than an identity fact and is never on the
wire. Inactive principals are listed rather than hidden, because a management
view has to be able to see the principal it may reactivate. Entries come from
`AuthorizationManagementService.list_principals` inside the request's own unit of
work, ordered by id; this package reads no table.

### Grant state

`GET /api/principals/{id}/grants` is the query the Roles UI hydrates its
checkboxes from, and it is a read of the same Core state `PUT` writes. It has
exactly the protections of the permissions route: a live session, one request
handle, one Core decision on `authorization.manage` in the caller's own scope,
and `{id}` is only ever the resource being reported on. A query naming
`principal_id`, `principal`, `actor`, `identity_id`, `channel`, `scope`,
`subject_id`, or `user_id` is refused with `422 principal_not_accepted`.

The scope is **explicit**. `organization_id` or `workplace_id` must be named:
`422 scope_invalid` when neither is, because an unspecified scope would answer
for every scope at once. The reported scope is the named organization and
workplace with **no** principal dimension, so it is a management view of an
organization and never a peek at somebody's self scope. Nothing widens: a grant
held at a workplace does not answer an organization-wide question, and a self
grant does not answer either.

```json
{"principal_id": "user.7f3",
 "scope": {"organization_id": "org-1", "workplace_id": null, "principal_id": null},
 "capabilities": [{"capability_id": "self.monthly.report.view",
                   "direct": true, "role_ids": ["role.self_report_viewer"]}],
 "roles": [{"role_id": "role.self_report_viewer", "assigned": true}],
 "effective_capability_ids": ["self.monthly.report.view"]}
```

- `capabilities` is the **whole active catalogue**, not just the granted part, so
  the view can render every checkbox. Per capability, `direct` is the explicit
  audited grant and `role_ids` are the roles that also carry it at this scope;
  together they are the capability's sources. A capability that is effective but
  not `direct` is one a role provides, which is what a view needs in order to
  explain why unticking the box did not remove the permission.
- `roles` reports `assigned` for every active role, so an unheld role still gets
  a checkbox.
- `effective_capability_ids` is the union the server enforces. It is empty for a
  deactivated principal, whose stored state is still reported: a management view
  has to be able to see what it would be reactivating.

It is checkbox state and nothing else — no principal metadata and no theme — and
it grants nothing: the server rechecks authorization on the mutation regardless
of what this returned. A missing principal is `404 principal_unknown`, and a
principal the caller's own grant does not cover is the same `403
capability_denied` any other route gives.

### Management checkbox bodies

```json
{"checked": true, "scope": {"organization_id": "org-1", "workplace_id": null},
 "principal_id": "user.7f3", "confirmation_id": "conf_..."}
```

`checked` is **advisory**: it selects which Core call to make. Core rechecks
authorization, principal activity, and capability registration on both the grant
and the revoke, so a ticked box changes nothing on its own (§38.3).

`scope` carries the organization and workplace only. A self-scoped grant adds a
**top-level** `principal_id`; a `principal_id` nested inside `scope` is refused
with `422 scope_invalid` so a client can never believe it made a self grant when
it made an organization-wide one. `{id}` in the path is the *resource* the grant
is about; the execution scope is always the operator's own.

### The self report

`GET /api/self/monthly-report` takes no principal. A body or query naming
`principal_id`, `principal`, `actor`, `identity_id`, `channel`, `scope`,
`subject_id`, or `user_id` is refused with `422 principal_not_accepted`. The
plugin asks Core who the handle belongs to before it reads a row (§38.6).

### Reports

`GET /api/reports` discovers every enabled provider's definition through the
published `report.definition` contract with an empty probe, so this package names
no plugin and reads no plugin table (§13). `POST /api/reports/{id}/render` binds
`report.render` *and* the definition's declared `required_capabilities` onto the
request handle, and the handle's scope is the organization with no principal
dimension — which is exactly what Report Studio asks for. A self-scoped dataset
inside an organization render therefore contributes no rows, which is the correct
answer and not a gap.

### Theme

`GET/PUT /api/session/theme` is a self-scoped preference with no capability, no
policy, and no scope beyond the session. It is written through the new Core
`AuthorizationManagementService.set_principal_metadata`, delivered to deployed
databases by versioned migration `004_principal_metadata` (§38.15 — never
`create_all` only). Nothing in the authorization path reads it back, so it can
never widen what a principal may do.

### Confirmations

`POST /api/confirmations` takes `{"capability", "action", "scope", "resource_id"}`
and asks Core for a typed, one-time confirmation. It is authorized with
`authorize_confirmation_request`, the one check that does not consume a
confirmation, so a confirmation-required policy can still be satisfied. The
`confirmation_id` is then passed back on the mutation route and consumed by
Core's own decision — bound to the principal, capability, action, resource,
channel, and scope Core resolved. Replaying it is refused.

`resource_id` is the target the action is about, and it is part of the binding
rather than a hint. It is the `{id}` of the principal whose grant or role
assignment the caller is about to change, and the handle is issued for it, so
Core stores it on the confirmation. Consumption requires the executing handle to
resolve to **that same** target: a confirmation issued for one user does not
authorize a change to another, and omitting `resource_id` does not produce a
wildcard — a confirmation with no target matches only an execution that has no
target either. A mismatch is refused as `403 confirmation_required` and consumes
nothing.

## Error mapping

One fixed public message per status; Core's decision `reason` is never echoed.

| Core code / condition | Status |
| --- | --- |
| `handle_required`, `handle_invalid`, `persistence_required`, `session_unknown`, `session_revoked`, `session_expired` | 401 |
| `capability_denied`, `capability_binding_mismatch`, `policy_denied`, `assistant_required`, `confirmation_required` | 403 |
| `confirmation_consumed` | 409 |
| `request_invalid`, `scope_invalid`, `body_invalid`, `theme_invalid`, `principal_not_accepted` | 422 |
| unknown Core code | 403 (default deny) |
| unknown route / `NotFoundError` | 404 |
| wrong method on a known path | 405 |
| `login_disabled` | 404 |
| `operator_not_configured` | 503 |

## Configuration

| Variable | Meaning |
| --- | --- |
| `ATLAS_DATABASE_URL` | PostgreSQL URL. Without a UoW factory there is no service: `WebAppService.__init__` raises. |
| `ATLAS_WEB_DEV_LOGIN` | `1`/`true`/`yes`/`on` enables `POST /api/session`. Off by default. Refused on a non-loopback `--host`: the route mints a session for a fixed principal for anybody who can reach the listener, so `python -m atlas_web --host 0.0.0.0` with this on exits with an error instead of serving (`atlas_web.http.require_loopback_dev_login`). |
| `ATLAS_WEB_OPERATOR_PRINCIPAL` | The principal the dev login route acts as. Never read from a request. |

## Running

Three steps, in this order. The API listens on **8000**; the console's own dev
server is on **5175** and proxies `/api` here.

**1. Create the operator principal.** `POST /api/session` answers
`503 operator_not_configured` until the configured principal exists, is active,
and holds the capabilities the console needs — which is the
`No operator principal is configured` message on the sign-in page.
`atlas-hq operator-init` is the supported way to put one there:

```powershell
$env:ATLAS_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq"
.\.venv\Scripts\atlas-hq.exe operator-init `
  --principal atlas.local.operator `
  --organization org_local `
  --create-organization `
  --organization-name "Atlas Local" `
  --grant authorization.manage `
  --grant report.render `
  --grant self.monthly.report.view
```

| Flag | Requirement |
| --- | --- |
| `--principal` | **Required**, no default. The id `ATLAS_WEB_OPERATOR_PRINCIPAL` will name. |
| `--organization` | **Required.** The only organization any grant is scoped to; nothing wider is ever granted. |
| `--create-organization` | Opt-in. **Required on a database that does not have the organization yet** — a reachable-but-empty database is the case this exists for, since there is then no id to name. Without it, a missing `--organization` is a refusal that prints the command to run. Never a default, and it never overwrites: an organization that already exists is reused untouched. |
| `--organization-name` | The display name for the organization `--create-organization` makes. Only meaningful with that flag — it is refused on its own, because silently ignoring a name the operator typed would leave them believing they had named the organization. Defaults to the `--organization` value. The organization's `code` is that same value; nothing is generated. |
| `--grant` | Repeatable, optional, and the *only* source of authority. No flag, no grant. Accepted names: `authorization.manage`, `report.render`, `self.monthly.report.view`, `assistant.use`. An unrecognised name is refused rather than skipped. |
| `--allow-remote-database` | Required to point it at a non-loopback host, which is refused by default so the command cannot quietly write into a production database. |

The organization is written through the Core organization repository and audited
as `organization.created` under the same fixed actor as everything else the
command writes. It lands *before* the principal, so a refusal about a missing
organization leaves no half-bootstrapped operator behind.

There is no `--actor`: the audit actor is the fixed constant
`atlas-hq.operator-init`, so a command that could write its own actor into the
audit trail would be a way to forge one. The run is idempotent — an existing
principal is left active rather than "reactivated", an existing organization is
reused, and a grant that already exists is not duplicated — and it finishes
migration `004_principal_metadata` through the same migration runner every other
boot uses, rather than assuming `create_all` got there first.

Which capability each route needs:

| Route | Needs |
| --- | --- |
| `/api/capabilities`, `/api/roles`, `/api/principals`, `/api/reports` | `authorization.manage` |
| `/api/principals/{id}/permissions`, `/api/principals/{id}/grants` | `authorization.manage` |
| `PUT /api/principals/{id}/capabilities/{capability}` | `authorization.manage` |
| `POST /api/reports/{id}/render` | `report.render` (+ the definition's own) |
| `GET /api/self/monthly-report` | `self.monthly.report.view` |

**2. Start the API:**

```powershell
$env:ATLAS_WEB_DEV_LOGIN = "1"
$env:ATLAS_WEB_OPERATOR_PRINCIPAL = "atlas.local.operator"
.\.venv\Scripts\python.exe -m atlas_web --port 8000
```

**3. Start the console** (in `web/`, on port 5175):

```powershell
npm ci --ignore-scripts
npm rebuild esbuild @tailwindcss/oxide    # the only two in web/package.json#allowScripts
npm run dev      # http://127.0.0.1:5175, /api proxied to 127.0.0.1:8000
```

The adapter binds to loopback by default, and refuses to bind anything else
while `ATLAS_WEB_DEV_LOGIN` is on. It is a development server: it has no
TLS, no CSRF token, and no rate limiting, and it serves the API only. Put a real
reverse proxy in front of it before it is reachable by anyone else.

## Not in this slice

No frontend files, no CSRF token, no multi-instance session sharing (the session
store is process-local, so sessions do not survive a restart and do not work
across replicas), no refresh tokens, and no rate limiting.
