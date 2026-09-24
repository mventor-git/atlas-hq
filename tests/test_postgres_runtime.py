"""PostgreSQL-only runtime and database isolation acceptance tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from atlas_core.application.organization import OrganizationService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.identifiers import OrganizationId
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.infrastructure.persistence.orm import Base
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
from atlas_sdk import DomainEvent, EventId


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


def test_commit_and_rollback_are_real_postgres_transactions(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        committed = OrganizationService(uow).create_organization(name="Committed", code="COMMIT")

    with pytest.raises(RuntimeError), uow_factory() as rolled_back:
        OrganizationService(rolled_back).create_organization(name="Rolled back", code="ROLLBACK")
        raise RuntimeError("force rollback")

    with uow_factory() as check:
        assert check.organizations.get(OrganizationId(committed.organization_id)) is not None
        assert check.organizations.get_by_code("ROLLBACK") is None


def test_state_and_outbox_roll_back_atomically(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with pytest.raises(RuntimeError), uow_factory() as uow:
        OrganizationService(uow).create_organization(name="Atomic", code="ATOMIC")
        OutboxEventPublisher(uow).publish(DomainEvent(event_id=EventId("test.atomic"), payload={}))
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

    adapter = PluginPersistenceAdapter(Session())
    with pytest.raises(RuntimeError, match="bound"):
        adapter.create_schema(Base.metadata)


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
                name="Isolated", code="ISOLATED"
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
            name="CLI Organization", code="CLI"
        )
    monkeypatch.setenv(ENV_VAR, database_url)
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", test_schema)

    exit_code = main(["report", organization.organization_id])
    output = capsys.readouterr().out

    assert exit_code == 0, output
    assert f"Report for organization {organization.organization_id}" in output
