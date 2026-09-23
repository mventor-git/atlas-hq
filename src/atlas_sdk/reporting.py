"""The published shape of the ``reporting.dataset`` contract (contract §13).

Composability needs a shared *vocabulary*, not shared implementations. Report
Studio and every dataset-providing plugin import these types from the SDK; no
plugin imports another plugin. That is what keeps Report Studio able to consume
datasets from plugins it has never heard of.

The vocabulary is intentionally tiny: a request scoped by organization and a
response that is just labelled columns and rows. Anything richer would start to
encode business meaning the consumer has no right to assume.
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
    "DatasetRequest",
    "DatasetResponse",
]
