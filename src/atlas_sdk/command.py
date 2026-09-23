"""Command marker.

A command expresses an *intent to change state* (contract section 20). Command
objects carry the request; a :class:`CommandHandler` executes it. Commands are
not queries: never return business state from a command beyond an identifier.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

CommandT = TypeVar("CommandT", bound="Command")
ResultT = TypeVar("ResultT")


class Command:
    """Marker base class for every Atlas command."""

    #: The result type a handler returns for this command.
    result_type: type


class CommandHandler(Protocol[CommandT, ResultT]):
    """Executes a command and returns its result."""

    def handle(self, command: CommandT) -> ResultT: ...


__all__ = ["Command", "CommandHandler"]
