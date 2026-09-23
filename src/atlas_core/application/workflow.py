"""Workflow engine (skeleton, callable).

D1 ships an in-memory state machine good enough to start, transition and inspect
a case. Persistence and compensation come later; the port is stable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from atlas_sdk import NotFoundError, WorkflowCase
from atlas_sdk.context import WorkflowPort

from ..domain.identifiers import new_id


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
    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._cases: dict[str, WorkflowCase] = {}

    def define(
        self,
        workflow_id: str,
        initial_state: str,
        transitions: Mapping[str, Sequence[str]],
    ) -> None:
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
    ) -> str:
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

    def transition(self, case_id: str, to_state: str) -> None:
        case = self._cases.get(case_id)
        if case is None:
            msg = f"workflow case {case_id!r} does not exist"
            raise NotFoundError(msg, kind="workflow_case", key=case_id)
        definition = self._definitions[case.workflow_id]
        if not definition.allows(case.state, to_state):
            msg = f"workflow {case.workflow_id!r} does not allow {case.state!r} -> {to_state!r}"
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

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._cases.get(case_id)


__all__ = ["WorkflowDefinition", "WorkflowService"]
