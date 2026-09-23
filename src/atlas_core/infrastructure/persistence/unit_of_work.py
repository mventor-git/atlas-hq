"""The unit of work: one transaction spanning state and events (contract §21).

``SqlUnitOfWork`` is a context manager. Entering it opens a session and begins
a transaction; every repository write and every outbox append lands in that same
transaction. A clean exit commits both; an exception rolls back both — so an
event can never be delivered for work that did not happen.

The dispatcher reads committed envelopes in a *fresh* session (see
:mod:`atlas_core.infrastructure.events`), which is what makes the rollback
guarantee observable rather than merely asserted.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session

from ...application.unit_of_work import SessionFactoryPort, UnitOfWorkPort
from .orm import Base
from .repositories import (
    AssignmentRepository,
    AuditRepository,
    EmployeeRepository,
    JobRepository,
    OrganizationRepository,
    OutboxRepository,
    WorkplaceRepository,
)


class SqlUnitOfWork(UnitOfWorkPort):
    """One SQLAlchemy transaction exposing every repository the core needs."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.employees = EmployeeRepository(session)
        self.organizations = OrganizationRepository(session)
        self.workplaces = WorkplaceRepository(session)
        self.jobs = JobRepository(session)
        self.assignments = AssignmentRepository(session)
        self.audit = AuditRepository(session)
        self.outbox = OutboxRepository(session)
        #: Plugins that own tables share this transaction through this callable
        #: (contract section 22): one session, one commit, one rollback.
        self.sessions: SessionFactoryPort = _SharedSessionFactory(session)

    @property
    def session(self) -> Session:
        """The live session. Test helpers reach in here; production code does not."""
        return self._session

    def begin(self) -> None:
        if not self._session.in_transaction():
            self._session.begin()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> Self:
        self.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def create_schema(session: Session) -> None:
    """Create the core schema if it does not exist. Idempotent."""
    if session.bind is not None:
        Base.metadata.create_all(session.bind, checkfirst=True)


@dataclass(frozen=True)
class _SharedSessionFactory:
    """Returns the one session of the unit of work it belongs to.

    A plugin calls ``context.sessions()`` to reach the transaction the platform
    will commit for it; handing back the unit of work's own session is what
    keeps a plugin's writes from escaping that transaction.
    """

    session: Session

    def __call__(self) -> Session:
        return self.session


__all__ = ["SqlUnitOfWork", "create_schema"]
