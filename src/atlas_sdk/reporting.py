"""Published reporting contract vocabulary (contract §§12, 13 and 28).

Composability needs shared *shapes*, not shared implementations. Report Studio,
dataset providers, and fixed definition plugins import these types from the SDK;
no plugin imports another plugin. Dataset rows stay labelled columns and values,
while report definitions describe generic column filters, grouping, and details.
The shaping engine lives here too, so every report — whatever renders it — is
shaped by one deterministic, column-generic implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .capability import CapabilityId
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
                "use_case": {
                    "type": "object",
                    "description": (
                        "Optional use-case metadata (contract 38.1): use_case_id, title, "
                        "summary, owner, audience, scope, date_grain, required_capabilities, "
                        "surfaces, review_status, version."
                    ),
                },
            },
            "required": ["definition_id", "title", "dataset_ids"],
        },
    },
    description="A named, provider-owned declarative shape over logical datasets.",
)


@dataclass(frozen=True)
class UseCaseMetadata:
    """What a report *is for*, declared by the plugin that owns it (contract 38.1).

    Every field is mandatory: a definition that has no ``use_case`` is a plain
    dataset shape, and a definition that has one has described its use case
    completely. ``use_case_id`` is the stable identity across descriptive
    changes. Schedule metadata is deliberately absent — the first release of
    ``self.monthly.report`` is on-demand only (contract 38.6).
    """

    use_case_id: str
    title: str
    summary: str
    owner: str
    audience: str
    scope: str
    date_grain: str
    required_capabilities: tuple[CapabilityId, ...]
    surfaces: tuple[str, ...]
    review_status: str
    version: str


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
    """A named, generic tabular shape over one or more logical dataset ids.

    ``use_case`` is optional so a definition written before contract 38.1 keeps
    working unchanged; a definition that declares one carries the complete
    use-case metadata.
    """

    definition_id: str
    title: str
    dataset_ids: tuple[str, ...]
    filters: tuple[ColumnFilter, ...] = ()
    group_by: tuple[str, ...] = ()
    detail_columns: tuple[str, ...] = ()
    use_case: UseCaseMetadata | None = None


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


@dataclass(frozen=True)
class ReportGroup:
    """One group of a shaped report: its key values, its size, and its details."""

    key: tuple[str, ...]
    count: int
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class ShapedDataset:
    """The shaped view of one dataset a definition declared.

    ``installed`` is false and ``note`` explains why when no enabled provider
    supplies this dataset — the report degrades instead of crashing.
    """

    dataset_id: str
    title: str
    installed: bool = True
    note: str | None = None
    columns: tuple[str, ...] = ()
    groups: tuple[ReportGroup, ...] = ()


def shape_dataset(dataset: DatasetResponse, definition: ReportDefinition) -> ShapedDataset:
    """Apply a definition's shape to one dataset, by column name only.

    This is the whole of the "smart composition": deterministic, and driven by
    the dataset's own column metadata (contract section 14). No value is
    interpreted beyond the declared column equality.
    """
    columns = dataset.columns
    referenced = (
        [f.column for f in definition.filters]
        + list(definition.group_by)
        + list(definition.detail_columns)
    )
    if any(column not in columns for column in referenced):
        return ShapedDataset(
            dataset_id=dataset.dataset_id,
            title=definition.title,
            note=f"dataset {dataset.dataset_id} does not provide the columns this definition needs",
        )

    def positions(names: tuple[str, ...]) -> tuple[int, ...]:
        return tuple(columns.index(name) for name in names)

    filter_positions = [(columns.index(f.column), f.value) for f in definition.filters]
    group_positions = positions(definition.group_by)
    detail_positions = positions(definition.detail_columns)

    groups: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for row in dataset.rows:
        if any(row[position] != value for position, value in filter_positions):
            continue
        groups.setdefault(tuple(row[position] for position in group_positions), []).append(
            tuple(row[position] for position in detail_positions),
        )

    return ShapedDataset(
        dataset_id=dataset.dataset_id,
        title=definition.title,
        columns=definition.detail_columns,
        groups=tuple(
            ReportGroup(key=key, count=len(details), rows=tuple(details))
            for key, details in groups.items()
        ),
    )


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
    "ReportGroup",
    "ShapedDataset",
    "UseCaseMetadata",
    "shape_dataset",
]
