"""Capability identifiers.

A :data:`CapabilityId` names *who may perform an action* (contract section 35).
Ids are dotted strings such as ``people.employee.create``. The wrapper is a
``NewType`` so capability ids stay distinct from plain strings in signatures.
"""

from typing import NewType

CapabilityId = NewType("CapabilityId", str)

__all__ = ["CapabilityId"]
