"""Capability identifiers and the small Core capability vocabulary."""

from enum import StrEnum
from typing import NewType

CapabilityId = NewType("CapabilityId", str)


class CapabilityKind(StrEnum):
    """The non-interchangeable permission kinds required by Core."""

    VIEW = "view"
    SCHEDULE = "schedule"
    MANAGE = "manage"


__all__ = ["CapabilityId", "CapabilityKind"]
