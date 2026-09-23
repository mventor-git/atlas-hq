"""Query marker.

A query requests *current information now* (contract section 20) without
mutating state. Plugins query core services instead of reading core tables.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

QueryT = TypeVar("QueryT", bound="Query")
ResultT = TypeVar("ResultT")


class Query:
    """Marker base class for every Atlas query."""

    #: The result type a handler returns for this query.
    result_type: type


class QueryHandler(Protocol[QueryT, ResultT]):
    """Executes a query and returns its result."""

    def handle(self, query: QueryT) -> ResultT: ...


__all__ = ["Query", "QueryHandler"]
