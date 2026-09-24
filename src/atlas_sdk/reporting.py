"""Published reporting contract vocabulary (contract §§12, 13 and 28).

Composability needs shared *shapes*, not shared implementations. Report Studio,
dataset providers, and fixed definition plugins import these types from the SDK;
no plugin imports another plugin. Dataset rows stay labelled columns and values,
while report definitions describe generic column filters, grouping, and details.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contract import ContractDeclaration, ContractId

#: The one contract id Report Studio depends on. It is spelled here, in the SDK,
#: so consumers and providers agree without a shared plugin module.
REPORT_DATASET_CONTRACT = ContractId("reporting.dataset")

REPORT_DATASET_DECLARATION = ContractDeclaration(
    contract_id=REPORT_DATASET_CONTRACT,
    version="1.0",
    schema={
        "request": {
            "type": "object",
            "properties": {"organization_id": {"type": "string"}},
        },
        "response": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "title": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array"},
            },
        },
    },
    description="A labelled tabular dataset for one organization.",
)

REPORT_DEFINITION_CONTRACT = ContractId("report.definition")

REPORT_DEFINITION_DECLARATION = ContractDeclaration(
    contract_id=REPORT_DEFINITION_CONTRACT,
    version="1.0",
    schema={
        "request": {
            "type": "object",
            "properties": {"definition_id": {"type": "string"}},
            "required": ["definition_id"],
        },
        "response": {
            "type": "object",
            "properties": {
                "definition_id": {"type": "string"},
                "title": {"type": "string"},
                "dataset_ids": {"type": "array", "items": {"type": "string"}},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["column", "value"],
                    },
                },
                "group_by": {"type": "array", "items": {"type": "string"}},
                "detail_columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["definition_id", "title", "dataset_ids"],
        },
    },
    description="A named, provider-owned declarative shape over logical datasets.",
)


@dataclass(frozen=True)
class ReportDefinitionRequest:
    """Ask enabled fixed-report plugins for one logical report definition."""

    definition_id: str


@dataclass(frozen=True)
class ColumnFilter:
    """Keep only rows whose named column equals the supplied value."""

    column: str
    value: str


@dataclass(frozen=True)
class ReportDefinition:
    """A named, generic tabular shape over one or more logical dataset ids."""

    definition_id: str
    title: str
    dataset_ids: tuple[str, ...]
    filters: tuple[ColumnFilter, ...] = ()
    group_by: tuple[str, ...] = ()
    detail_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatasetRequest:
    """Ask every ``reporting.dataset`` provider for the data in one scope."""

    organization_id: str | None = None


@dataclass(frozen=True)
class DatasetResponse:
    """One provider's contribution to a report.

    Values are strings so heterogeneous providers stay comparable and printable;
    a provider that owns richer types maps them down at its boundary.
    """

    dataset_id: str
    title: str
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = field(default_factory=tuple)

    @property
    def row_count(self) -> int:
        return len(self.rows)


__all__ = [
    "REPORT_DATASET_CONTRACT",
    "REPORT_DATASET_DECLARATION",
    "REPORT_DEFINITION_CONTRACT",
    "REPORT_DEFINITION_DECLARATION",
    "ColumnFilter",
    "DatasetRequest",
    "DatasetResponse",
    "ReportDefinition",
    "ReportDefinitionRequest",
]
