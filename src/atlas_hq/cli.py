"""The ``atlas-hq`` command: boot the kernel and administer the platform.

Every subcommand hits the real registry or runtime — there is no command here
that reports a capability the kernel does not have (contract section 24).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from atlas_core.infrastructure.persistence.unit_of_work import create_sql_uow_factory
from atlas_core.kernel import BootResult, Kernel

INDENT = "  "


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
    report.add_argument("--actor", default="cli")

    workplace = sub.add_parser("workplace", help="workplaces and their workforce")
    workplace_sub = workplace.add_subparsers(dest="workplace_command", required=True)

    wp_list = workplace_sub.add_parser("list", help="list workplaces of an organization")
    wp_list.add_argument("organization_id")
    wp_list.add_argument("--kind", help="filter by workplace type (e.g. site, office)")

    wp_workforce = workplace_sub.add_parser("workforce", help="show the workforce of a workplace")
    wp_workforce.add_argument("workplace_id")

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

    return AuditService(uow_factory()).list_records(limit=limit)


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
    from atlas_plugins.report_studio import REPORT_RENDER, ReportRequest
    from atlas_sdk import Scope

    kernel, result = boot_kernel(args, with_persistence=True)
    kernel.enable_all()

    studio = _plugin_instance(kernel, "report_studio")
    if studio is None:
        print(  # noqa: T201
            "report_studio is not installed; cannot render reports",
        )
        return 2

    # Grant only the report-renderer role in the requested organization scope.
    scope = Scope(organization_id=args.organization_id)
    studio.context.authorization.grant(args.actor, "role.report_renderer", scope)

    if not studio.context.authorization.check(REPORT_RENDER, scope, args.actor):
        print(  # noqa: T201
            f"{args.actor!r} is not permitted to render reports in {args.organization_id!r}",
        )
        return 3

    report = studio.render(ReportRequest(organization_id=args.organization_id, actor_id=args.actor))
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


def _run_workplace(args: argparse.Namespace) -> int:
    """List workplaces and show a workplace's workforce through the real plugin.

    The workplace plugin's own services are the only path to its tables, so the
    CLI enables the plugin and calls it — it never queries ``wpop_*`` itself.
    """
    from atlas_plugins.workplace_operations import (
        WorkplaceOperationsPlugin,
    )
    from atlas_sdk import Scope, WorkplaceType

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
        # The CLI acts as a platform administrator granted the view capability.
        plugin.context.authorization.grant(
            "cli",
            "role.workplace_viewer",
            Scope(organization_id=organization_id),
        )
        workplaces = plugin.list_workplaces(organization_id, kind)
        lines = [f"Workplaces in {organization_id} ({len(workplaces)}):"]
        for workplace in workplaces:
            lines.append(f"{INDENT}{workplace.code} [{workplace.kind.value}] {workplace.name}")
            lines.append(f"{INDENT * 2}id: {workplace.workplace_id}")
        print("\n".join(lines))  # noqa: T201
        return 0

    if command == "workforce":
        workplace_id = args.workplace_id
        context = plugin.resolve_context(workplace_id)
        plugin.context.authorization.grant(
            "cli",
            "role.workplace_viewer",
            Scope(organization_id=context.organization_id),
        )
        members = plugin.list_workforce(workplace_id)
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
