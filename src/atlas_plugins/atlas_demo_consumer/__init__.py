"""Demo Plugin B — consumes Demo Plugin A's contract without importing it.

This plugin is the proof of Gate K (contract section 9): it asks the registry
for implementations of the contract id ``demo.greeting``, calls them through the
invoker, and reacts to the ``demo.greeted`` event. It never imports
``atlas_plugins.atlas_demo`` and has no reference to it anywhere in its source.

Both the contract id and the event id are spelled here as *literal strings* on
purpose. Sharing a constant module would be implementation coupling by another
name; sharing a published id string is the sanctioned channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlas_sdk import (
    ContractId,
    EventId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from atlas_sdk import DomainEvent, PluginContext

#: Gate K — the contract id is a literal string, not an import. Whatever plugin
#: happens to be installed and enabled to provide this contract answers the call.
GREETING_CONTRACT = ContractId("demo.greeting")

#: The event Demo Plugin A publishes; B subscribes to the *id*, never the module.
GREETED_EVENT = EventId("demo.greeted")


@dataclass
class GreetingReceived:
    """Local record of a greeting event this plugin observed."""

    employee_id: str
    full_name: str
    actor_id: str


class AtlasDemoConsumerPlugin(Plugin):
    """Demo Plugin B: a contract consumer and event subscriber."""

    manifest = PluginManifest(
        plugin_id="atlas_demo_consumer",
        name="Atlas Demo Consumer",
        version="0.1.0",
        # Consuming a greeting produced by platform plumbing is still governance.
        cluster_id="cluster.governance_and_management",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="demo.greeting_log",
                consumes=("demo.greeting",),
                subscribes=(GREETED_EVENT,),
            ),
        ),
        consumes_contracts=(GREETING_CONTRACT,),
        subscribes_events=(GREETED_EVENT,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        #: Greetings observed from events, in arrival order. A plugin keeps its
        #: own state; other plugins reach it only through the contract.
        self.observed: list[GreetingReceived] = []

    def bind_subscriptions(self) -> dict[EventId, Callable[[DomainEvent], None]]:
        return {GREETED_EVENT: self._on_greeted}

    def bind_contracts(self) -> None:
        # This plugin provides no contracts. It consumes one: the greeting
        # contract owned by Demo Plugin A, reached through the invoker.
        pass

    def _on_greeted(self, event: DomainEvent) -> None:
        self.observed.append(
            GreetingReceived(
                employee_id=str(event.payload.get("employee_id", "")),
                full_name=str(event.payload.get("full_name", "")),
                actor_id=str(event.payload.get("actor_id", "")),
            ),
        )

    def call_greeting(self, employee_id: str, actor_id: str, organization_id: str) -> object:
        """Invoke whichever plugin currently provides ``demo.greeting``.

        The return type is deliberately ``object`` to B: the consumer knows the
        contract's *id*, not the provider's response class (contract section 9).
        """
        request = _GreetingRequest(
            employee_id=employee_id,
            actor_id=actor_id,
            organization_id=organization_id,
        )
        return self.context.invoker.invoke(GREETING_CONTRACT, request)


@dataclass(frozen=True)
class _GreetingRequest:
    """B's own request shape.

    The contract id is the agreement; the request object is built by the caller.
    The provider accepts it structurally — both sides spell the same fields —
    which keeps B from importing A's classes.
    """

    employee_id: str
    actor_id: str
    organization_id: str


__all__ = ["AtlasDemoConsumerPlugin", "GREETING_CONTRACT", "GREETED_EVENT"]
