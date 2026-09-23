"""The ``atlas-hq`` command: boot the kernel and print registry state.

Real admin operations (enable/disable a plugin, inspect a cluster) are D2; this
command proves the boot path runs end to end and shows what the registries hold.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from atlas_core.kernel import BootResult, Kernel

INDENT = "  "


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atlas-hq",
        description="Boot the Atlas platform core and report registry state.",
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
    return parser


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
        marker = f" — {len(members)} plugin(s)" if members else ""
        lines.append(f"{INDENT}{cluster.cluster_id}: {cluster.name}{marker}")

    plugins = kernel.registries.plugins.all()
    lines.append("")
    lines.append(f"Plugins ({len(plugins)}):")
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

    capabilities = kernel.registries.capabilities.all()
    lines.append("")
    lines.append(f"Capabilities ({len(capabilities)}):")
    for capability in capabilities:
        providers = ", ".join(kernel.registries.capabilities.providers_of(capability))
        lines.append(f"{INDENT}{capability} <- {providers}")

    contracts = kernel.registries.contracts.all()
    lines.append("")
    lines.append(f"Contracts ({len(contracts)}):")
    for impl in contracts:
        lines.append(
            f"{INDENT}{impl.declaration.contract_id} v{impl.declaration.version} "
            f"<- {impl.plugin_id}",
        )

    events = kernel.registries.events.all()
    lines.append("")
    lines.append(f"Events ({len(events)}):")
    for event in events:
        publishers = ", ".join(kernel.registries.events.publishers_of(event))
        subscribers = ", ".join(kernel.registries.events.subscribers_of(event))
        lines.append(f"{INDENT}{event} (publishers: {publishers}, subscribers: {subscribers})")

    if result.failed:
        lines.append("")
        lines.append(f"Failed plugins ({len(result.failed)}):")
        for plugin_id, reason in result.failed:
            lines.append(f"{INDENT}{plugin_id}: {reason}")

    return "\n".join(lines)


def render_json(kernel: Kernel, result: BootResult) -> str:
    import json

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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    kernel = Kernel(entry_point_group=args.entry_point_group)
    result = kernel.boot()

    if args.json:
        print(render_json(kernel, result))  # noqa: T201 - CLI output
    else:
        print(render_state(kernel, result))  # noqa: T201 - CLI output

    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
