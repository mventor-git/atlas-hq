"""Helpers for building a synthetic, installable-looking plugin distribution.

A real distribution is just a directory on ``sys.path`` containing a module and
a matching ``.dist-info`` folder. ``importlib.metadata`` reads its entry points
exactly as it reads any installed package, so a test can prove discovery finds a
plugin *without editing core code* (contract section 17).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from atlas_core.infrastructure.discovery import PLUGIN_ENTRY_POINT_GROUP

DIST_INFO_TEMPLATE = """\
Metadata-Version: 2.1
Name: {name}
Version: {version}
"""

#: An entry-point group no real distribution advertises. Tests that want a
#: registry containing only their synthetic plugin boot the kernel against this
#: group; the eight real plugins stay invisible to them (contract section 17:
#: isolation is by entry point, not by folder).
TEST_ENTRY_POINT_GROUP = "atlas.test.plugins"

PLUGIN_MODULE_TEMPLATE = """\
from __future__ import annotations

from atlas_sdk import Plugin, PluginManifest

from atlas_sdk import (
    CapabilityId,
    ContractDeclaration,
    ContractId,
    EventId,
    ModuleDeclaration,
)


class {class_name}(Plugin):
    manifest = PluginManifest(
        plugin_id={plugin_id!r},
        name={name!r},
        version={version!r},
        cluster_id={cluster_id!r},
        requires_plugins={requires_plugins!r},
        modules={modules},
        provides_capabilities={provides_capabilities},
        consumes_capabilities={consumes_capabilities},
        provides_contracts={provides_contracts},
        consumes_contracts={consumes_contracts},
        publishes_events={publishes_events},
        subscribes_events={subscribes_events},
    )

    def initialize(self, context):
        self.context = context
        self._handler = _Handler(context)

    def bind_contracts(self):
        for declaration in self.manifest.provides_contracts:
            self.context.contracts.bind(
                declaration.contract_id, self.manifest.plugin_id, self._handler
            )


class _Handler:
    def __init__(self, context):
        self.context = context

    def handle(self, request):
        return {{"echo": request, "plugin_id": self.context.plugin_id}}
"""


def write_distribution(
    directory: Path,
    *,
    distribution_name: str = "synthetic-plugin",
    version: str = "0.1.0",
    module_name: str = "synthetic_plugin",
    class_name: str = "SyntheticPlugin",
    plugin_id: str = "synthetic.plugin",
    plugin_name: str = "Synthetic Plugin",
    cluster_id: str = "cluster.information_and_documents",
    requires_plugins: tuple[str, ...] = (),
    modules: tuple[str, ...] = ("synthetic.core",),
    provides_capabilities: tuple[str, ...] = ("synthetic.report",),
    consumes_capabilities: tuple[str, ...] = (),
    provides_contracts: tuple[tuple[str, str], ...] = (("synthetic.dataset", "1.0"),),
    consumes_contracts: tuple[str, ...] = (),
    publishes_events: tuple[str, ...] = ("synthetic.generated",),
    subscribes_events: tuple[str, ...] = (),
    entry_point_name: str | None = None,
    group: str = TEST_ENTRY_POINT_GROUP,
) -> Path:
    """Write a module + ``.dist-info`` exposing an ``atlas.plugins`` entry point.

    Returns the module path. ``directory`` must already be on ``sys.path``.
    """
    module_path = directory / f"{module_name}.py"
    module_path.write_text(
        PLUGIN_MODULE_TEMPLATE.format(
            class_name=class_name,
            plugin_id=plugin_id,
            name=plugin_name,
            version=version,
            cluster_id=cluster_id,
            requires_plugins=requires_plugins,
            modules=_repr_module_declarations(modules),
            provides_capabilities=_repr_capability_ids(provides_capabilities),
            consumes_capabilities=_repr_capability_ids(consumes_capabilities),
            provides_contracts=_repr_contract_declarations(provides_contracts),
            consumes_contracts=_repr_contract_ids(consumes_contracts),
            publishes_events=_repr_event_ids(publishes_events),
            subscribes_events=_repr_event_ids(subscribes_events),
        ),
        encoding="utf-8",
    )

    dist_info = directory / f"{distribution_name}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        DIST_INFO_TEMPLATE.format(name=distribution_name, version=version),
        encoding="utf-8",
    )

    entry_name = entry_point_name if entry_point_name is not None else plugin_id
    (dist_info / "entry_points.txt").write_text(
        textwrap.dedent(
            f"""\
            [{group}]
            {entry_name} = {module_name}:{class_name}
            """,
        ),
        encoding="utf-8",
    )
    return module_path


def refresh_metadata_cache() -> None:
    """Make ``importlib.metadata`` re-scan ``sys.path``.

    importlib caches distribution discovery per directory; after a test writes a
    new ``.dist-info`` directory the caches must be cleared or the new entry
    point is invisible until the process restarts. Both the import finder cache
    and the per-directory ``FastPath`` cache have to go — clearing only one lets
    a second distribution in the same directory stay hidden.
    """
    import importlib
    import importlib.metadata as metadata

    importlib.invalidate_caches()
    metadata.MetadataPathFinder.invalidate_caches()


__all__ = [
    "PLUGIN_ENTRY_POINT_GROUP",
    "TEST_ENTRY_POINT_GROUP",
    "refresh_metadata_cache",
    "write_distribution",
]


# --- source emitters ------------------------------------------------------
# These build the *source text* for SDK value objects rather than the objects
# themselves, because the synthetic module is a file on disk, not an import.


def _repr_module_declarations(module_ids: tuple[str, ...]) -> str:
    if not module_ids:
        return "()"
    inner = ", ".join(f"ModuleDeclaration(module_id={m!r})" for m in module_ids)
    return f"({inner},)"


def _repr_capability_ids(values: tuple[str, ...]) -> str:
    if not values:
        return "()"
    inner = ", ".join(f"CapabilityId({v!r})" for v in values)
    return f"({inner},)"


def _repr_contract_ids(values: tuple[str, ...]) -> str:
    if not values:
        return "()"
    inner = ", ".join(f"ContractId({v!r})" for v in values)
    return f"({inner},)"


def _repr_event_ids(values: tuple[str, ...]) -> str:
    if not values:
        return "()"
    inner = ", ".join(f"EventId({v!r})" for v in values)
    return f"({inner},)"


def _repr_contract_declarations(values: tuple[tuple[str, str], ...]) -> str:
    if not values:
        return "()"
    inner = ", ".join(
        f"ContractDeclaration(contract_id=ContractId({cid!r}), version={ver!r})"
        for cid, ver in values
    )
    return f"({inner},)"
