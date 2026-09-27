"""PostgreSQL-only runtime and database isolation acceptance tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema
from tests.conftest import issue_uow_handle_for_test

from atlas_core.application.organization import OrganizationService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.identifiers import OrganizationId
from atlas_core.domain.role import ORGANIZATION_MANAGE
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.infrastructure.persistence.session import (
    ENV_VAR,
    SessionFactory,
    create_schema,
    create_session_factory_with_engine,
    drop_schema,
    ensure_schema,
    resolve_database_url,
)
from atlas_core.infrastructure.persistence.unit_of_work import (
    PluginPersistenceAdapter,
    SqlUnitOfWork,
)
from atlas_core.infrastructure.persistence.unit_of_work import (
    create_schema as create_uow_schema,
)
from atlas_hq.cli import main
from atlas_plugins.attendance_operations.persistence import AttendanceORM
from atlas_sdk import CapabilityId, DomainEvent, EventId, Scope


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    with pytest.raises(ValueError, match="ATLAS_DATABASE_URL"):
        resolve_database_url()


def test_database_url_must_use_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "mysql://atlas:atlas@localhost:3306/atlas_hq")

    with pytest.raises(ValueError, match="PostgreSQL"):
        resolve_database_url()


def test_postgres_schema_is_created_and_search_path_is_set(
    database_url: str,
    test_schema: str,
    session_factory: Callable[[], Session],
) -> None:
    session = session_factory()
    assert session.scalar(text("SELECT current_schema()")) == test_schema
    bind = session.get_bind()
    assert bind is not None
    assert "organization" in inspect(bind).get_table_names(schema=test_schema)
    session.close()


def test_pooled_checkout_restores_bound_schema_before_marking_outbox(
    database_url: str,
    test_schema: str,
) -> None:
    other_schema = f"{test_schema}_other"
    factory, engine = create_session_factory_with_engine(database_url, schema=test_schema)
    admin_engine = create_engine(resolve_database_url(database_url), future=True)
    sessions: list[Session] = []

    def new_session() -> Session:
        session = factory()
        sessions.append(session)
        return session

    try:
        create_schema(engine, test_schema)
        with engine.begin() as connection:
            connection.execute(CreateSchema(other_schema, if_not_exists=True))

        commit_session = new_session()
        handle = issue_uow_handle_for_test(
            lambda: SqlUnitOfWork(factory()),
            CapabilityId("test.event"),
            "test.event",
            Scope(principal_id="pooled"),
            principal_id="pooled",
        )
        with SqlUnitOfWork(commit_session) as uow:
            commit_backend = commit_session.scalar(text("SELECT pg_backend_pid()"))
            OutboxEventPublisher(uow).publish(
                DomainEvent(event_id=EventId("test.pooled_schema"), payload={}),
                execution_handle=handle,
            )
        commit_session.close()

        read_session = new_session()
        read_uow = SqlUnitOfWork(read_session)
        try:
            read_backend = read_session.scalar(text("SELECT pg_backend_pid()"))
            pending = read_uow.outbox.pending()
            read_uow.rollback()
        finally:
            read_session.close()
        assert len(pending) == 1

        quoted_other_schema = engine.dialect.identifier_preparer.quote_identifier(other_schema)
        with engine.connect() as connection:
            contaminated_backend = connection.scalar(text("SELECT pg_backend_pid()"))
            connection.execute(text(f"SET SESSION search_path TO {quoted_other_schema}"))
            connection.commit()
            assert connection.scalar(text("SELECT current_schema()")) == other_schema

        assert read_backend == commit_backend
        assert contaminated_backend == commit_backend

        mark_session = new_session()
        mark_uow = SqlUnitOfWork(mark_session)
        try:
            with mark_uow:
                mark_backend = mark_session.scalar(text("SELECT pg_backend_pid()"))
                mark_schema = mark_session.scalar(text("SELECT current_schema()"))
                mark_uow.outbox.mark_dispatched(pending[0].envelope_id)
        finally:
            mark_session.close()
        assert mark_backend == commit_backend
        assert mark_schema == test_schema

        verify_session = new_session()
        verify_uow = SqlUnitOfWork(verify_session)
        try:
            verify_backend = verify_session.scalar(text("SELECT pg_backend_pid()"))
            assert verify_uow.outbox.pending() == []
            verify_uow.rollback()
        finally:
            verify_session.close()
        assert verify_backend == commit_backend
    finally:
        for session in sessions:
            session.close()
        engine.dispose()
        try:
            drop_schema(admin_engine, test_schema)
        finally:
            try:
                drop_schema(admin_engine, other_schema)
            finally:
                admin_engine.dispose()


def test_commit_and_rollback_are_real_postgres_transactions(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        committed = OrganizationService(uow).create_organization(
            name="Committed",
            code="COMMIT",
            execution_handle=issue_uow_handle_for_test(
                uow_factory,
                ORGANIZATION_MANAGE,
                "organization.create",
                Scope(principal_id="runtime"),
                principal_id="runtime",
            ),
        )

    with pytest.raises(RuntimeError), uow_factory() as rolled_back:
        OrganizationService(rolled_back).create_organization(
            name="Rolled back",
            code="ROLLBACK",
            execution_handle=issue_uow_handle_for_test(
                uow_factory,
                ORGANIZATION_MANAGE,
                "organization.create",
                Scope(principal_id="runtime.rollback"),
                principal_id="runtime.rollback",
            ),
        )
        raise RuntimeError("force rollback")

    with uow_factory() as check:
        assert check.organizations.get(OrganizationId(committed.organization_id)) is not None
        assert check.organizations.get_by_code("ROLLBACK") is None


def test_state_and_outbox_roll_back_atomically(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with pytest.raises(RuntimeError), uow_factory() as uow:
        handle = issue_uow_handle_for_test(
            uow_factory,
            ORGANIZATION_MANAGE,
            "organization.create",
            Scope(principal_id="runtime.atomic"),
            principal_id="runtime.atomic",
        )
        OrganizationService(uow).create_organization(
            name="Atomic", code="ATOMIC", execution_handle=handle
        )
        OutboxEventPublisher(uow).publish(
            DomainEvent(event_id=EventId("test.atomic"), payload={}),
            execution_handle=handle,
        )
        raise RuntimeError("force rollback")

    with uow_factory() as check:
        assert check.organizations.get_by_code("ATOMIC") is None
        assert check.outbox.pending() == []


def test_schema_argument_cannot_override_the_bound_search_path(
    database_url: str,
    test_schema: str,
) -> None:
    _factory, engine = create_session_factory_with_engine(database_url, schema=test_schema)
    mismatch = f"{test_schema}_mismatch"
    try:
        with pytest.raises(ValueError, match="bound schema"):
            create_schema(engine, mismatch)
        assert mismatch not in inspect(engine).get_schema_names()
    finally:
        drop_schema(engine, mismatch)
        engine.dispose()


def test_raw_engine_cannot_create_schema_or_session_factory_without_binding(
    database_url: str,
    test_schema: str,
) -> None:
    raw_engine = create_engine(
        resolve_database_url(database_url),
        connect_args={"options": "-c default_transaction_read_only=on"},
        future=True,
    )
    try:
        with pytest.raises(ValueError, match="not bound"):
            SessionFactory(raw_engine)
        with pytest.raises(ValueError, match="not bound"):
            create_schema(raw_engine, test_schema)
    finally:
        raw_engine.dispose()


def test_engine_helpers_reject_non_psycopg_driver(
    database_url: str,
    test_schema: str,
) -> None:
    engine = create_engine(resolve_database_url(database_url), future=True)
    engine.url = engine.url.set(drivername="postgresql+psycopg2")
    try:
        with pytest.raises(ValueError, match="postgresql\\+psycopg"):
            SessionFactory(engine)
        with pytest.raises(ValueError, match="postgresql\\+psycopg"):
            ensure_schema(engine, test_schema)
    finally:
        engine.dispose()


def test_schema_setup_rejects_an_unbound_session() -> None:
    with pytest.raises(RuntimeError, match="bound"):
        create_uow_schema(Session())

    adapter = PluginPersistenceAdapter(
        Session(),
        plugin_id="test.plugin",
        owned_tables=("att_attendance",),
    )
    with pytest.raises(RuntimeError, match="bound"):
        adapter.create_tables(AttendanceORM)

    with pytest.raises(PermissionError, match="Core tables"):
        PluginPersistenceAdapter(
            Session(),
            plugin_id="test.plugin",
            owned_tables=("organization",),
        )


def test_drop_schema_rejects_non_test_namespaces(database_url: str) -> None:
    engine = create_engine(
        resolve_database_url(database_url),
        connect_args={"options": "-c default_transaction_read_only=on"},
        future=True,
    )
    try:
        for schema in ("atlas", "public"):
            with pytest.raises(ValueError, match="atlas_test_"):
                drop_schema(engine, schema)
    finally:
        engine.dispose()


def test_two_postgres_schemas_do_not_share_rows(
    database_url: str,
    test_schema: str,
) -> None:
    other_schema = f"{test_schema}_other"
    first_factory, first_engine = create_session_factory_with_engine(
        database_url, schema=test_schema
    )
    second_factory, second_engine = create_session_factory_with_engine(
        database_url, schema=other_schema
    )
    try:
        create_schema(first_engine, test_schema)
        create_schema(second_engine, other_schema)
        with SqlUnitOfWork(first_factory()) as first:
            organization = OrganizationService(first).create_organization(
                name="Isolated",
                code="ISOLATED",
                execution_handle=issue_uow_handle_for_test(
                    lambda: SqlUnitOfWork(first_factory()),
                    ORGANIZATION_MANAGE,
                    "organization.create",
                    Scope(principal_id="runtime.isolated"),
                    principal_id="runtime.isolated",
                ),
            )
        with SqlUnitOfWork(second_factory()) as second:
            assert second.organizations.get(OrganizationId(organization.organization_id)) is None
            assert second.organizations.get_by_code("ISOLATED") is None
    finally:
        drop_schema(first_engine, test_schema)
        drop_schema(second_engine, other_schema)
        first_engine.dispose()
        second_engine.dispose()


def test_cli_report_uses_real_postgres_and_enables_plugins(
    database_url: str,
    test_schema: str,
    uow_factory: Callable[[], UnitOfWorkPort],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with uow_factory() as uow:
        organization = OrganizationService(uow).create_organization(
            name="CLI Organization",
            code="CLI",
            execution_handle=issue_uow_handle_for_test(
                uow_factory,
                ORGANIZATION_MANAGE,
                "organization.create",
                Scope(principal_id="runtime.cli"),
                principal_id="runtime.cli",
            ),
        )
    from atlas_core.kernel import Kernel
    from atlas_hq.cli import LOCAL_OPERATOR_ID
    from atlas_plugins.report_studio import REPORT_RENDER
    from atlas_sdk import CapabilityId

    seed_kernel = Kernel(uow_factory=uow_factory)
    seed_kernel.boot()
    management = seed_kernel.authorization_management
    management.create_principal(LOCAL_OPERATOR_ID)
    for capability, provider in (
        (REPORT_RENDER, "report_studio"),
        (CapabilityId("people.employee.read"), "core"),
        (CapabilityId("workplace.view"), "workplace_operations"),
        (CapabilityId("attendance.view"), "attendance_operations"),
        (CapabilityId("audit.read"), "core"),
    ):
        management.register_capability(capability, provider_id=provider)
        management.grant_capability(
            LOCAL_OPERATOR_ID, capability, Scope(organization_id=organization.organization_id)
        )
    monkeypatch.setenv(ENV_VAR, database_url)
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", test_schema)

    exit_code = main(["report", organization.organization_id])
    output = capsys.readouterr().out

    assert exit_code == 0, output
    assert f"Report for organization {organization.organization_id}" in output
