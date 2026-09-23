"""Typed identifiers for core aggregates.

Each aggregate owns a distinct id type so a ``JobId`` can never be silently
passed where an ``EmployeeId`` is expected. All ids are strings under the hood
(the SDK's published language uses plain strings), and every id carries a
recognisable prefix for greppability in logs and databases.
"""

from __future__ import annotations

import uuid
from typing import NewType

EmployeeId = NewType("EmployeeId", str)
OrganizationId = NewType("OrganizationId", str)
WorkplaceId = NewType("WorkplaceId", str)
JobId = NewType("JobId", str)
AssignmentId = NewType("AssignmentId", str)


def new_id(prefix: str) -> str:
    """Generate a new prefixed identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


__all__ = [
    "AssignmentId",
    "EmployeeId",
    "JobId",
    "OrganizationId",
    "WorkplaceId",
    "new_id",
]
