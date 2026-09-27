"""The ``atlas-hq`` command: boot the kernel and administer the platform.

Every subcommand hits the real registry or runtime — there is no command here
that reports a capability the kernel does not have (contract section 24).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from sqlalchemy.engine import make_url

from atlas_core.infrastructure.persistence.session import resolve_database_url
from atlas_core.infrastructure.persistence.unit_of_work import create_sql_uow_factory
from atlas_core.kernel import BootResult, Kernel

INDENT = "  "
LOCAL_OPERATOR_ID = "atlas.local.operator"

#: The audit actor every ``operator-init`` record is written under. It is a
#: constant, not a flag: whoever ran the command is the local shell, and a
#: command that could name its own actor in the audit trail would be a way to
#: forge one.
OPERATOR_INIT_ACTOR = "atlas-hq.operator-init"

#: The complete set of capabilities ``operator-init`` will grant. Nothing is
#: granted implicitly — a name must be asked for — and an unrecognised name is
#: refused by the parser rather than skipped, so a typo can never quietly produce
#: an operator with fewer rights than the operator believes.
OPERATOR_INIT_GRANTS: tuple[str, ...] = (
    "assistant.use",
    "authorization.manage",
    "report.render",
    "self.monthly.report.view",
)


def _configured_operator_handle(
    kernel,
    capability,
    action,
    scope,
    *,
    channel,
    resource_id=None,
    additional_capabilities=(),
):
    """Issue a handle only for a preconfigured local service principal."""
    management = kernel.authorization_management
    principal = management.get_principal(LOCAL_OPERATOR_ID)
    if principal is None or not principal.active:
        raise PermissionError(f"local service principal {LOCAL_OPERATOR_ID!r} is not configured")
    return kernel.issue_execution_handle(
        principal_id=LOCAL_OPERATOR_ID,
        capability=capability,
        action=action,
        scope=scope,
        channel=channel,
        resource_id=resource_id,
        additional_capabilities=tuple(additional_capabilities),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas-hq",
        description="Boot the Atlas platform core and administer plugins.",
    )
    parser.add_argument(
        "--entry-point-group",
        default="atlas.plugins",
        help="entry-point group to discover plugins from (default: atlas.plugins)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable output instead of the human-readable report",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("boot", help="discover, validate and register every installed plugin")

    sub.add_parser("plugins", help="list plugins and their lifecycle state")
    sub.add_parser("clusters", help="list clusters and their plugins")
    sub.add_parser("contracts", help="list registered contracts")
    sub.add_parser("capabilities", help="list registered capabilities")
    sub.add_parser("events", help="list registered events")

    enable = sub.add_parser("enable", help="enable a plugin")
    enable.add_argument("plugin_id")

    disable = sub.add_parser("disable", help="disable a plugin")
    disable.add_argument("plugin_id")

    audit = sub.add_parser("audit", help="view recent audit records")
    audit.add_argument("--limit", type=int, default=10)

    report = sub.add_parser("report", help="render a report through Report Studio")
    report.add_argument("organization_id")

    workplace = sub.add_parser("workplace", help="workplaces and their workforce")
    workplace_sub = workplace.add_subparsers(dest="workplace_command", required=True)

    wp_list = workplace_sub.add_parser("list", help="list workplaces of an organization")
    wp_list.add_argument("organization_id")
    wp_list.add_argument("--kind", help="filter by workplace type (e.g. site, office)")

    wp_workforce = workplace_sub.add_parser("workforce", help="show the workforce of a workplace")
    wp_workforce.add_argument("workplace_id")

    operator = sub.add_parser(
        "operator-init",
        help="create or activate a local web operator principal and grant it named capabilities",
        description=(
            "Bring up the principal the web console's development login acts as. Refuses to "
            "run without an explicit principal id and an explicit organization scope, grants "
            f"only what --grant names, and audits under the fixed actor {OPERATOR_INIT_ACTOR!r}. "
            "It never invents an id: a --organization that does not exist yet is a refusal, "
            "unless --create-organization says out loud that it should be created."
        ),
    )
    operator.add_argument(
        "--principal",
        required=True,
        help="the principal id the dev login route will act as (required; no default)",
    )
    operator.add_argument(
        "--organization",
        required=True,
        help="the one organization every grant is scoped to (required; nothing wider is granted)",
    )
    operator.add_argument(
        "--create-organization",
        action="store_true",
        help="create the named organization when it does not exist yet (opt-in; the id is "
        "still the explicit --organization value, and an organization that already exists is "
        "reused and never overwritten)",
    )
    operator.add_argument(
        "--organization-name",
        default=None,
        help="display name for the organization --create-organization makes, used with "
        "--create-organization only (default: the --organization value)",
    )
    operator.add_argument(
        "--grant",
        action="append",
        default=[],
        choices=OPERATOR_INIT_GRANTS,
        metavar="CAPABILITY",
        help="grant CAPABILITY in that organization; repeatable, never implicit "
        f"(one of: {', '.join(OPERATOR_INIT_GRANTS)})",
    )
    operator.add_argument(
        "--allow-remote-database",
        action="store_true",
        help="permit a database host that is not loopback (refused by default, so this command "
        "cannot quietly write into a production database)",
    )

    return parser


# --- boot ------------------------------------------------------------------


def boot_kernel(
    args: argparse.Namespace,
    *,
    with_persistence: bool = False,
) -> tuple[Kernel, BootResult]:
    """Boot registries, adding PostgreSQL only for database-backed commands."""
    uow_factory = create_sql_uow_factory() if with_persistence else None
    kernel = Kernel(uow_factory=uow_factory, entry_point_group=args.entry_point_group)
    result = kernel.boot()
    return kernel, result


# --- reports ---------------------------------------------------------------


def render_state(kernel: Kernel, result: BootResult) -> str:
    """Render the registry state as a human-readable report."""
    lines: list[str] = []
    lines.append(
        f"Atlas-HQ - boot complete (discovered={result.discovered}, "
        f"registered={result.registered}, failed={len(result.failed)})"
    )

    clusters = kernel.registries.clusters.all()
    lines.append("")
    lines.append(f"Clusters ({len(clusters)}):")
    for cluster in clusters:
        members = kernel.registries.plugins.list_by_cluster(cluster.cluster_id)
        marker = f" - {len(members)} plugin(s)" if members else ""
        lines.append(f"{INDENT}{cluster.cluster_id}: {cluster.name}{marker}")

    lines.extend(render_plugins(kernel))
    lines.extend(render_capabilities(kernel))
    lines.extend(render_contracts(kernel))
    lines.extend(render_events(kernel))

    if result.failed:
        lines.append("")
        lines.append(f"Failed plugins ({len(result.failed)}):")
        for plugin_id, reason in result.failed:
            lines.append(f"{INDENT}{plugin_id}: {reason}")

    return "\n".join(lines)


def render_plugins(kernel: Kernel) -> list[str]:
    plugins = kernel.registries.plugins.all()
    lines = ["", f"Plugins ({len(plugins)}):"]
    for manifest in plugins:
        state = kernel.registries.plugins.lifecycle_state(manifest.plugin_id)
        lines.append(f"{INDENT}{manifest.plugin_id} v{manifest.version} [{state.label}]")
        lines.append(f"{INDENT * 2}cluster: {manifest.cluster_id}")
        if manifest.provides_capabilities:
            caps = ", ".join(sorted(manifest.provides_capabilities))
            lines.append(f"{INDENT * 2}provides capabilities: {caps}")
        if manifest.consumes_capabilities:
            caps = ", ".join(sorted(manifest.consumes_capabilities))
            lines.append(f"{INDENT * 2}consumes capabilities: {caps}")
        if manifest.provides_contracts:
            contracts = ", ".join(sorted(c.contract_id for c in manifest.provides_contracts))
            lines.append(f"{INDENT * 2}provides contracts: {contracts}")
        if manifest.consumes_contracts:
            contracts = ", ".join(sorted(manifest.consumes_contracts))
            lines.append(f"{INDENT * 2}consumes contracts: {contracts}")
        if manifest.publishes_events:
            events = ", ".join(sorted(manifest.publishes_events))
            lines.append(f"{INDENT * 2}publishes events: {events}")
        if manifest.subscribes_events:
            events = ", ".join(sorted(manifest.subscribes_events))
            lines.append(f"{INDENT * 2}subscribes events: {events}")
        if manifest.module_ids():
            lines.append(f"{INDENT * 2}modules: {', '.join(manifest.module_ids())}")
    return lines


def render_clusters(kernel: Kernel) -> str:
    lines = ["", f"Clusters ({len(kernel.registries.clusters.all())}):"]
    for cluster in kernel.registries.clusters.all():
        members = kernel.registries.plugins.list_by_cluster(cluster.cluster_id)
        lines.append(f"{INDENT}{cluster.cluster_id}: {cluster.name}")
        if cluster.description:
            lines.append(f"{INDENT * 2}{cluster.description}")
        for member in members:
            state = kernel.registries.plugins.lifecycle_state(member.plugin_id)
            lines.append(f"{INDENT * 2}{member.plugin_id} [{state.label}]")
    return "\n".join(lines)


def render_capabilities(kernel: Kernel) -> list[str]:
    capabilities = kernel.registries.capabilities.all()
    lines = ["", f"Capabilities ({len(capabilities)}):"]
    for capability in capabilities:
        providers = ", ".join(kernel.registries.capabilities.providers_of(capability))
        lines.append(f"{INDENT}{capability} <- {providers}")
    return lines


def render_contracts(kernel: Kernel) -> list[str]:
    contracts = kernel.registries.contracts.all()
    lines = ["", f"Contracts ({len(contracts)}):"]
    for impl in contracts:
        bound = "bound" if impl.is_bound else "unbound"
        lines.append(
            f"{INDENT}{impl.declaration.contract_id} v{impl.declaration.version} "
            f"<- {impl.plugin_id} ({bound})"
        )
    return lines


def render_events(kernel: Kernel) -> list[str]:
    events = kernel.registries.events.all()
    lines = ["", f"Events ({len(events)}):"]
    for event in events:
        publishers = ", ".join(kernel.registries.events.publishers_of(event))
        subscribers = ", ".join(kernel.registries.events.subscribers_of(event))
        lines.append(f"{INDENT}{event} (publishers: {publishers}, subscribers: {subscribers})")
    return lines


def render_audit(kernel: Kernel, limit: int) -> str:
    records = _audit_records(kernel, limit)
    lines = ["", f"Audit records ({len(records)}):"]
    for entry in records:
        scope = f" org={entry.scope.organization_id}" if entry.scope.organization_id else ""
        lines.append(
            f"{INDENT}{entry.occurred_at.isoformat()} {entry.action} by {entry.actor}{scope}"
        )
        if entry.details:
            lines.append(f"{INDENT * 2}{json.dumps(entry.details, default=str)}")
    return "\n".join(lines)


def _audit_records(kernel: Kernel, limit: int) -> list:
    uow_factory = kernel.uow_factory
    if uow_factory is None:
        raise RuntimeError("audit requires a PostgreSQL-backed unit-of-work factory")
    from atlas_core.application.audit import AuditService
    from atlas_core.domain.role import AUDIT_READ
    from atlas_sdk import Channel, Scope

    scope = Scope(principal_id=LOCAL_OPERATOR_ID)
    handle = _configured_operator_handle(
        kernel,
        AUDIT_READ,
        "audit.read",
        scope,
        channel=Channel.CORE,
    )
    uow = uow_factory()
    try:
        policy = kernel._policy.bind_uow(uow)
        authorization = kernel._authorization.for_uow(uow, policy=policy)
        return AuditService(uow, resolver=authorization._handle_resolver).list_records(
            limit=limit,
            execution_handle=handle,
        )
    finally:
        uow.close()


# --- json ------------------------------------------------------------------


def render_json(kernel: Kernel, result: BootResult) -> str:
    payload = {
        "discovered": result.discovered,
        "registered": result.registered,
        "failed": [{"plugin_id": pid, "reason": reason} for pid, reason in result.failed],
        "clusters": [c.cluster_id for c in kernel.registries.clusters.all()],
        "plugins": [
            {
                "plugin_id": m.plugin_id,
                "version": m.version,
                "cluster_id": m.cluster_id,
                "state": kernel.registries.plugins.lifecycle_state(m.plugin_id).label,
            }
            for m in kernel.registries.plugins.all()
        ],
        "capabilities": sorted(kernel.registries.capabilities.all()),
        "contracts": sorted(
            str(impl.declaration.contract_id) for impl in kernel.registries.contracts.all()
        ),
        "events": sorted(str(e) for e in kernel.registries.events.all()),
    }
    return json.dumps(payload, indent=2)


# --- dispatch --------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command

    if command is None or command == "boot":
        kernel, result = boot_kernel(args)
        if args.json:
            print(render_json(kernel, result))  # noqa: T201
        else:
            print(render_state(kernel, result))  # noqa: T201
        return 1 if result.failed else 0

    if command == "report":
        return _run_report(args)

    if command == "operator-init":
        return _run_operator_init(args)

    if command == "workplace":
        return _run_workplace(args)

    kernel, result = boot_kernel(
        args,
        with_persistence=command in {"audit", "enable", "disable"},
    )

    if command == "plugins":
        out = "\n".join(render_plugins(kernel))
    elif command == "clusters":
        out = render_clusters(kernel)
    elif command == "contracts":
        out = "\n".join(render_contracts(kernel))
    elif command == "capabilities":
        out = "\n".join(render_capabilities(kernel))
    elif command == "events":
        out = "\n".join(render_events(kernel))
    elif command == "audit":
        out = render_audit(kernel, args.limit)
    elif command == "enable":
        kernel.enable(args.plugin_id)
        state = kernel.registries.plugins.lifecycle_state(args.plugin_id)
        out = f"plugin {args.plugin_id} -> {state.label}"
    elif command == "disable":
        kernel.disable(args.plugin_id)
        state = kernel.registries.plugins.lifecycle_state(args.plugin_id)
        out = f"plugin {args.plugin_id} -> {state.label}"
    else:
        out = render_state(kernel, result)

    print(out)  # noqa: T201
    return 1 if result.failed else 0


def _run_report(args: argparse.Namespace) -> int:
    """Render through Report Studio, discovered and enabled like any plugin."""
    from atlas_core.domain.role import AUDIT_READ, PEOPLE_EMPLOYEE_READ
    from atlas_plugins.report_studio import REPORT_RENDER, ReportRequest
    from atlas_sdk import CapabilityId, Channel, Scope

    kernel, result = boot_kernel(args, with_persistence=True)
    kernel.enable_all()

    studio = _plugin_instance(kernel, "report_studio")
    if studio is None:
        print(  # noqa: T201
            "report_studio is not installed; cannot render reports",
        )
        return 2

    scope = Scope(organization_id=args.organization_id)
    try:
        execution_handle = _configured_operator_handle(
            kernel,
            REPORT_RENDER,
            "report.render",
            scope,
            channel=Channel.WEB,
            resource_id=args.organization_id,
            additional_capabilities=(
                PEOPLE_EMPLOYEE_READ,
                CapabilityId("workplace.view"),
                CapabilityId("attendance.view"),
                AUDIT_READ,
            ),
        )
    except PermissionError as error:
        print(str(error))  # noqa: T201
        return 2

    report = studio.render(
        ReportRequest(organization_id=args.organization_id),
        execution_handle=execution_handle,
    )
    print(report.render())  # noqa: T201
    kernel.dispatcher.dispatch_pending()
    return 0


def _plugin_instance(kernel: Kernel, plugin_id: str):
    """The live instance of an enabled plugin, or None.

    The CLI reaches a plugin's own API only for the two administration commands
    that must call it (``report`` and ``workplace``). Everything else uses
    registry metadata alone.
    """
    instances = getattr(kernel, "_instances", {})
    return instances.get(plugin_id)


# --- local operator bootstrap ----------------------------------------------


def _non_loopback_database_refusal(allow_remote: bool) -> str | None:
    """Refuse a non-loopback database unless the operator says so out loud.

    This command writes grants, so pointing it at a production database by
    accident is the failure worth designing against. ``ATLAS_DATABASE_URL`` is
    configuration, not consent.
    """
    if allow_remote:
        return None
    host = make_url(resolve_database_url()).host or ""
    if host in {"localhost", "::1"} or host.startswith("127."):
        return None
    return (
        f"database host {host!r} is not loopback; this command is for a local database. "
        "Pass --allow-remote-database if that is genuinely intended."
    )


def _record_deferred_migrations() -> None:
    """Finish a migration that ``create_all`` had to run first.

    ``create_sql_uow_factory`` migrates *before* ``create_all``, so on a brand-new
    database the ``principal`` table does not exist yet and
    ``004_principal_metadata`` is deliberately left unrecorded for the next run.
    A second pass through the same runner records it now, so the column and its
    version marker arrive together instead of trailing a process restart.

    ``ensure_schema`` comes first for the same reason ``create_sql_uow_factory``
    calls it first: on a first run against an empty database the target schema
    does not exist yet, and ``apply_migrations`` would fail with "no schema has
    been selected to create in".
    """
    from atlas_core.infrastructure.persistence.migrations import apply_migrations
    from atlas_core.infrastructure.persistence.session import (
        create_session_factory_with_engine,
        ensure_schema,
    )

    _factory, engine = create_session_factory_with_engine()
    try:
        ensure_schema(engine)
        apply_migrations(engine)
    finally:
        engine.dispose()


def _missing_organization_refusal(principal_id: str, organization_id: str) -> str:
    """The one message for a scope that does not exist, with the command to run.

    A first ``operator-init`` against a reachable but empty database cannot name an
    organization, because there is not one to name. The refusal therefore carries
    the exact command that fixes it rather than only reporting the absence.
    """
    return (
        f"organization {organization_id!r} does not exist, and this command will not invent "
        "one. Create it explicitly, then re-run this command unchanged:\n"
        f"{INDENT}atlas-hq operator-init --principal {principal_id} "
        f"--organization {organization_id} --create-organization "
        f'--organization-name "<name>"'
    )


def _ensure_organization(
    kernel: Kernel,
    principal_id: str,
    organization_id: str,
    name: str,
    *,
    create: bool,
) -> str:
    """Return ``"reused"`` or ``"created"`` for the named organization.

    The write goes through the Core organization repository — the same seam
    :class:`~atlas_core.application.organization.OrganizationService` adds to — and
    is audited under the fixed :data:`OPERATOR_INIT_ACTOR`, because an id chosen
    on a command line is not an authority Core may attribute to anyone else.

    The explicit id, the name, and the code are all the operator's. The code is
    the organization id, so nothing here invents a value nobody typed.

    An organization that is already there is returned as ``"reused"`` and left
    exactly as it is: a second run, a renamed organization, and a database that
    was populated by something else all converge on the same untouched row.
    """
    from atlas_core.domain.audit import AuditRecord
    from atlas_core.domain.identifiers import OrganizationId
    from atlas_core.domain.organization import Organization

    uow_factory = kernel.uow_factory
    if uow_factory is None:
        raise RuntimeError("organization bootstrap requires a PostgreSQL UoW factory")
    key = OrganizationId(organization_id)
    with uow_factory() as uow:
        if uow.organizations.get(key) is not None:
            return "reused"
        if not create:
            raise ValueError(_missing_organization_refusal(principal_id, organization_id))
        uow.organizations.add(Organization(organization_id=key, name=name, code=organization_id))
        uow.audit.append(
            AuditRecord(
                actor=OPERATOR_INIT_ACTOR,
                action="organization.created",
                organization_id=organization_id,
                details={
                    "organization_id": organization_id,
                    "name": name,
                    "code": organization_id,
                },
            )
        )
    return "created"


def _run_operator_init(args: argparse.Namespace) -> int:
    """Create or activate the console's local operator principal, idempotently.

    The dev login route reads ``ATLAS_WEB_OPERATOR_PRINCIPAL`` and answers 503
    until that principal exists, is active, and holds the capabilities the
    console needs. This command is the supported way to put one there.

    What it deliberately will not do: name an actor (the audit actor is the fixed
    :data:`OPERATOR_INIT_ACTOR`), infer a scope, grant a capability that was not
    asked for by name, write to a database the operator has not acknowledged, or
    invent an id. An organization that does not exist is therefore a refusal
    until ``--create-organization`` asks for it by name — which is what makes the
    first run against a reachable but empty database work without guessing.

    A grant lands in exactly the two scopes the console authorizes against, and
    both are named on the command line rather than guessed. The operator's *own*
    scope is what every management route and the self report decide on (§38.3:
    "one Core decision on ``authorization.manage`` in the caller's own scope"),
    and the organization is what ``report.render`` decides on. Nothing is granted
    anywhere else: ``Scope(principal_id=X)`` can only ever authorize actions about
    X itself.
    """
    from atlas_sdk import CapabilityId, NotFoundError, Scope, ScopeError

    principal_id = args.principal.strip()
    organization_id = args.organization.strip()
    organization_name = (args.organization_name or "").strip()
    if not principal_id or not organization_id:
        print("--principal and --organization are both required and must not be blank")  # noqa: T201
        return 2
    if args.organization_name is not None and not organization_name:
        print("--organization-name must not be blank")  # noqa: T201
        return 2
    if organization_name and not args.create_organization:
        print(  # noqa: T201
            "--organization-name only means something with --create-organization; "
            "an organization this run did not create is never renamed"
        )
        return 2

    try:
        refusal = _non_loopback_database_refusal(args.allow_remote_database)
        if refusal is not None:
            print(refusal)  # noqa: T201
            return 2

        kernel, _result = boot_kernel(args, with_persistence=True)
        kernel.enable_all()
        # After the boot, not before: on a first run against an empty database the
        # factory's own migration pass ran before ``create_all`` built the
        # ``principal`` table, so 004 is still unrecorded until now.
        _record_deferred_migrations()
        # Before the principal: a scope that is missing is a refusal, and a
        # refusal that had already created a principal would be a partial write.
        organization_state = _ensure_organization(
            kernel,
            principal_id,
            organization_id,
            organization_name or organization_id,
            create=args.create_organization,
        )
        management = kernel.authorization_management

        principal = management.create_principal(
            principal_id,
            display_name=f"Local web operator {principal_id}",
            actor=OPERATOR_INIT_ACTOR,
        )
        if not principal.active:
            principal = management.set_principal_active(
                principal_id, True, actor=OPERATOR_INIT_ACTOR
            )

        own_scope = Scope(principal_id=principal_id)
        organization_scope = Scope(organization_id=organization_id)
        granted: list[str] = []
        for name in args.grant:
            capability = CapabilityId(name)
            for scope in (own_scope, organization_scope):
                management.grant_capability(
                    principal_id, capability, scope, actor=OPERATOR_INIT_ACTOR
                )
            granted.append(name)
    except (ValueError, ScopeError, NotFoundError) as error:
        # A blank scope, a missing organization, a missing ATLAS_DATABASE_URL, or
        # a --grant naming a capability no installed plugin provides. All are
        # refusals, not crashes.
        print(f"operator-init refused: {error}")  # noqa: T201
        return 2

    print(f"operator principal {principal_id} is active in {organization_id}")  # noqa: T201
    print(f"{INDENT}own scope: {principal_id}")  # noqa: T201
    print(f"{INDENT}organization: {organization_id} ({organization_state})")  # noqa: T201
    for name in granted:
        print(f"{INDENT}granted: {name} (both scopes)")  # noqa: T201
    if not granted:
        print(f"{INDENT}granted: (none)")  # noqa: T201
    # A plugin that failed to boot is not this command's problem unless it owns a
    # requested capability, and that case already raised and refused above. So
    # the exit code reports the operator, not the registry.
    return 0


def _run_workplace(args: argparse.Namespace) -> int:
    """List workplaces and show a workplace's workforce through the real plugin.

    The workplace plugin's own services are the only path to its tables, so the
    CLI enables the plugin and calls it — it never queries ``wpop_*`` itself.
    """
    from atlas_plugins.workplace_operations import (
        WORKPLACE_VIEW,
        WorkplaceOperationsPlugin,
    )
    from atlas_sdk import Channel, Scope, WorkplaceType

    kernel, result = boot_kernel(args, with_persistence=True)
    kernel.enable_all()

    plugin = _plugin_instance(kernel, "workplace_operations")
    if plugin is None or not isinstance(plugin, WorkplaceOperationsPlugin):
        print("workplace_operations is not installed; cannot administer workplaces")  # noqa: T201
        return 2

    command = args.workplace_command

    if command == "list":
        organization_id = args.organization_id
        kind = WorkplaceType(args.kind) if args.kind else None
        scope = Scope(organization_id=organization_id)
        try:
            execution_handle = _configured_operator_handle(
                kernel,
                WORKPLACE_VIEW,
                "workplace.list",
                scope,
                channel=Channel.CORE,
                resource_id=organization_id,
            )
        except PermissionError as error:
            print(str(error))  # noqa: T201
            return 2
        workplaces = plugin.list_workplaces(
            organization_id,
            kind,
            execution_handle=execution_handle,
        )
        lines = [f"Workplaces in {organization_id} ({len(workplaces)}):"]
        for workplace in workplaces:
            lines.append(f"{INDENT}{workplace.code} [{workplace.kind.value}] {workplace.name}")
            lines.append(f"{INDENT * 2}id: {workplace.workplace_id}")
        print("\n".join(lines))  # noqa: T201
        return 0

    if command == "workforce":
        workplace_id = args.workplace_id
        try:
            lookup_context = _configured_operator_handle(
                kernel,
                WORKPLACE_VIEW,
                "workplace.context",
                Scope(principal_id=LOCAL_OPERATOR_ID),
                channel=Channel.CORE,
                resource_id=workplace_id,
            )
        except PermissionError as error:
            print(str(error))  # noqa: T201
            return 2
        context = plugin.resolve_workplace_context(
            workplace_id,
            execution_handle=lookup_context,
        )
        scope = Scope(organization_id=context.organization_id)
        try:
            execution_handle = _configured_operator_handle(
                kernel,
                WORKPLACE_VIEW,
                "workplace.workforce.read",
                scope,
                channel=Channel.CORE,
                resource_id=workplace_id,
            )
        except PermissionError as error:
            print(str(error))  # noqa: T201
            return 2
        members = plugin.list_workforce(
            workplace_id,
            execution_handle=execution_handle,
        )
        lines = [
            f"{context.name} [{context.kind.value}] ({context.code})",
            f"{INDENT}workforce: {len(members)} member(s)",
        ]
        for member in members:
            lines.append(
                f"{INDENT}{member.employee_number} {member.full_name} ({member.employee_id})",
            )
        print("\n".join(lines))  # noqa: T201
        return 0

    print(f"unknown workplace command: {command!r}")  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(main())
