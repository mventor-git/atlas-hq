"""Workflow engine with handle-bound Core authorization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    ExecutionHandle,
    NotFoundError,
    WorkflowCase,
)
from atlas_sdk.context import WorkflowPort

from ..domain.execution import ExecutionFacts
from ..domain.identifiers import new_id
from .execution_guard import require_execution_handle


class WorkflowDefinition:
    def __init__(
        self,
        workflow_id: str,
        initial_state: str,
        transitions: Mapping[str, Sequence[str]],
    ) -> None:
        self.workflow_id = workflow_id
        self.initial_state = initial_state
        self.transitions = {state: tuple(targets) for state, targets in transitions.items()}

    def allows(self, from_state: str, to_state: str) -> bool:
        return to_state in self.transitions.get(from_state, ())


class WorkflowService(WorkflowPort):
    def __init__(self, *, resolver: Any | None = None, authorization: Any | None = None) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._cases: dict[str, WorkflowCase] = {}
        self._resolver = resolver
        self._authorization = authorization

    def _authorize(self, handle: ExecutionHandle, action: str) -> None:
        facts = require_execution_handle(
            handle,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        if not isinstance(facts, ExecutionFacts) or self._authorization is None:
            raise AuthorizationError("a Core ExecutionHandle resolver is required")
        decision = self._authorization.authorize(
            handle,
            CapabilityId("policy.evaluate"),
            facts.scope,
            requested_action=action,
        )
        if not decision.allowed:
            raise AuthorizationError(f"workflow operation denied: {decision.code}")

    def define(
        self,
        workflow_id: str,
        initial_state: str,
        transitions: Mapping[str, Sequence[str]],
        *,
        execution_handle: ExecutionHandle,
    ) -> None:
        self._authorize(execution_handle, "workflow.define")
        self._definitions[workflow_id] = WorkflowDefinition(
            workflow_id,
            initial_state,
            transitions,
        )

    def start(
        self,
        workflow_id: str,
        entity_id: str,
        case_input: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str:
        self._authorize(execution_handle, "workflow.start")
        definition = self._definitions.get(workflow_id)
        if definition is None:
            msg = f"workflow {workflow_id!r} is not defined"
            raise NotFoundError(msg, kind="workflow", key=workflow_id)

        case_id = new_id("wf")
        started_at = datetime.now(UTC)
        self._cases[case_id] = WorkflowCase(
            case_id=case_id,
            workflow_id=workflow_id,
            entity_id=entity_id,
            state=definition.initial_state,
            started_at=started_at,
            input=dict(case_input or {}),
            updated_at=started_at,
        )
        return case_id

    def transition(
        self,
        case_id: str,
        to_state: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> None:
        self._authorize(execution_handle, "workflow.transition")
        case = self._cases.get(case_id)
        if case is None:
            msg = f"workflow case {case_id!r} does not exist"
            raise NotFoundError(msg, kind="workflow_case", key=case_id)
        definition = self._definitions[case.workflow_id]
        if not definition.allows(case.state, to_state):
            msg = (
                f"workflow {definition.workflow_id!r} does not allow {case.state!r} -> {to_state!r}"
            )
            raise ValueError(msg)
        self._cases[case_id] = WorkflowCase(
            case_id=case.case_id,
            workflow_id=case.workflow_id,
            entity_id=case.entity_id,
            state=to_state,
            started_at=case.started_at,
            input=case.input,
            updated_at=datetime.now(UTC),
        )

    def get_case(
        self,
        case_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> WorkflowCase | None:
        self._authorize(execution_handle, "workflow.case.read")
        return self._cases.get(case_id)


__all__ = ["WorkflowDefinition", "WorkflowService"]
