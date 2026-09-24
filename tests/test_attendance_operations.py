"""Attendance Operations — attendance as a first-class domain plugin.

Every test here drives the real entry-point-registered plugin through the real
kernel alongside Workplace Operations and Report Studio: persistence, outbox,
authorization, scope, audit, contracts and datasets. No plugin-internal module
is imported except this plugin's own public package, and another plugin is
reached only through its public package or through a contract.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import cast

import pytest
from sqlalchemy import text

from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from atlas_core.kernel import Kernel
from atlas_plugins.attendance_operations import (
    ATTENDANCE_DAILY_SUMMARY_CONTRACT,
    ATTENDANCE_DATASET_ID,
    ATTENDANCE_MANAGE,
    ATTENDANCE_RECORDED,
    ATTENDANCE_VIEW,
    AttendanceOperationsPlugin,
    AttendanceRecord,
    AttendanceRecordRequest,
    DailySummary,
    DailySummaryRequest,
)
from atlas_plugins.report_studio import RenderedReport, ReportRequest, ReportStudioPlugin
from atlas_plugins.workplace_operations import (
    WorkforceMembershipRequest,
    WorkplaceOperationsPlugin,
    WorkplaceRequest,
)
from atlas_sdk import (
    AttendanceStatus,
    AuthorizationError,
    DomainEvent,
    NotFoundError,
    WorkplaceType,
)
from atlas_sdk.reporting import REPORT_DATASET_CONTRACT

ACTOR = "user.attendance_admin"
WORKPLACE_ADMIN = "user.workplace_admin"
ATTENDANCE_MANAGER_ROLE = "role.attendance_manager"
WORKPLACE_MANAGER_ROLE = "role.workplace_manager"
WORKPLACE_VIEWER_ROLE = "role.workplace_viewer"
REPORT_RENDERER_ROLE = "role.report_renderer"

#: The day every record targets; tests stay on one date so idempotency is exact.
DAY = date(2026, 9, 24)


@dataclass(frozen=True)
class World:
    """One seeded world: two orgs, two workplaces, one roster member, one outsider."""

    org_id: str
    other_org_id: str
    workplace_id: str
    other_workplace_id: str
    #: A real employee who is a member of the workplace's workforce.
    member_id: str
    #: A real employee who is *not* a member — the Gate K negative case.
    outsider_id: str


@pytest.fixture
def attendance_kernel(real_kernel: Kernel) -> Kernel:
    """Workplace Operations (the workforce provider) + Attendance + Report Studio."""
    real_kernel.boot()
    for plugin_id in ("workplace_operations", "attendance_operations", "report_studio"):
        real_kernel.enable(plugin_id)
    return real_kernel


@pytest.fixture
def world(
    attendance_kernel: Kernel,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> World:
    workplace = _workplace_plugin(attendance_kernel)
    workplace_context = attendance_kernel.context_for("workplace_operations")
    attendance_context = attendance_kernel.context_for("attendance_operations")
    report_context = attendance_kernel.context_for("report_studio")

    with uow_factory() as uow:
        org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
        other = OrganizationService(uow).create_organization(name="Northwind", code="NW")
        people = PeopleService(uow, OutboxEventPublisher(uow, publisher="seed"))
        ada = people.create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
        )
        grace = people.create_employee(
            full_name="Grace Hopper",
            employee_number="EMP-2",
            organization_id=org.organization_id,
        )

    scope = workplace_context.scope.resolve(org.organization_id)
    other_scope = workplace_context.scope.resolve(other.organization_id)
    # The workplace admin builds the rosters in both organizations.
    workplace_context.authorization.grant(WORKPLACE_ADMIN, WORKPLACE_MANAGER_ROLE, scope)
    workplace_context.authorization.grant(WORKPLACE_ADMIN, WORKPLACE_MANAGER_ROLE, other_scope)
    # The attendance actor may record and view attendance in Acme, and must also
    # be able to read Acme's roster: the workforce contract authorizes its caller
    # with ``workplace.view`` (Gate K authorizes the caller, not the plugin).
    attendance_context.authorization.grant(ACTOR, ATTENDANCE_MANAGER_ROLE, scope)
    workplace_context.authorization.grant(ACTOR, WORKPLACE_VIEWER_ROLE, scope)
    report_context.authorization.grant(ACTOR, REPORT_RENDERER_ROLE, scope)

    site = workplace.create_workplace(
        WorkplaceRequest(
            organization_id=org.organization_id,
            name="Riverside Tower",
            code="RT-01",
            kind=WorkplaceType.SITE,
            actor_id=WORKPLACE_ADMIN,
        ),
    )
    workplace.add_workforce_member(
        WorkforceMembershipRequest(
            workplace_id=site.workplace_id, employee_id=ada.employee_id, actor_id=WORKPLACE_ADMIN
        ),
    )
    hq = workplace.create_workplace(
        WorkplaceRequest(
            organization_id=other.organization_id,
            name="Northwind Office",
            code="NW-01",
            kind=WorkplaceType.OFFICE,
            actor_id=WORKPLACE_ADMIN,
        ),
    )
    return World(
        org_id=org.organization_id,
        other_org_id=other.organization_id,
        workplace_id=site.workplace_id,
        other_workplace_id=hq.workplace_id,
        member_id=ada.employee_id,
        outsider_id=grace.employee_id,
    )


def _plugin(kernel: Kernel) -> AttendanceOperationsPlugin:
    instance = kernel._instances["attendance_operations"]
    assert isinstance(instance, AttendanceOperationsPlugin)
    return instance


def _workplace_plugin(kernel: Kernel) -> WorkplaceOperationsPlugin:
    instance = kernel._instances["workplace_operations"]
    assert isinstance(instance, WorkplaceOperationsPlugin)
    return instance


def _record(
    kernel: Kernel,
    employee_id: str,
    workplace_id: str,
    status: AttendanceStatus = AttendanceStatus.PRESENT,
    day: date = DAY,
    actor: str = ACTOR,
) -> AttendanceRecord:
    """Record attendance through the plugin's own service surface."""
    return _plugin(kernel).record_attendance(
        AttendanceRecordRequest(
            employee_id=employee_id,
            workplace_id=workplace_id,
            date=day,
            status=status,
            actor_id=actor,
        ),
    )


def _render(kernel: Kernel, org_id: str) -> RenderedReport:
    """Render through the live Report Studio instance — never naming a provider."""
    instance = kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)
    return instance.render(ReportRequest(organization_id=org_id, actor_id=ACTOR))


# --- registration (Gates C, D, E, F, G, H) ---------------------------------


def test_plugin_registers_under_the_workforce_and_time_cluster(
    attendance_kernel: Kernel,
) -> None:
    manifest = attendance_kernel.registries.plugins.get("attendance_operations")
    assert manifest.cluster_id == "cluster.workforce_and_time"
    assert (
        attendance_kernel.registries.plugins.lifecycle_state("attendance_operations").name
        == "ENABLED"
    )


def test_plugin_registers_its_module_capabilities_contracts_events(
    attendance_kernel: Kernel,
) -> None:
    plugins = attendance_kernel.registries.plugins
    capabilities = attendance_kernel.registries.capabilities
    contracts = attendance_kernel.registries.contracts

    assert {"attendance.daily"} <= set(plugins.get("attendance_operations").module_ids())
    assert capabilities.exists(ATTENDANCE_MANAGE)
    assert capabilities.exists(ATTENDANCE_VIEW)
    assert contracts.exists(ATTENDANCE_DAILY_SUMMARY_CONTRACT)
    # The same summary is also declared as a composable reporting dataset (Gate O).
    assert {impl.plugin_id for impl in contracts.implementations_of(REPORT_DATASET_CONTRACT)} >= {
        "attendance_operations"
    }
    assert attendance_kernel.registries.events.publishers_of(ATTENDANCE_RECORDED) == [
        "attendance_operations"
    ]


# --- real business services and core consumption (Gate J) -------------------


def test_records_attendance_for_a_workforce_member(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    record = _record(attendance_kernel, world.member_id, world.workplace_id)

    assert record.status == AttendanceStatus.PRESENT
    assert record.full_name == "Ada Lovelace"
    assert record.employee_number == "EMP-1"
    assert record.organization_id == world.org_id

    # Persistence is real: the plugin's own query reads the row back.
    summary = _plugin(attendance_kernel).daily_summary(world.workplace_id, DAY)
    assert summary.recorded_count == 1
    assert summary.entries[0].employee_id == world.member_id
    assert summary.entries[0].status == AttendanceStatus.PRESENT


def test_recording_an_unknown_employee_is_rejected(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate J: the employee must exist, verified through the core's people port."""
    with pytest.raises(NotFoundError) as exc:
        _record(attendance_kernel, "emp_no_such_person", world.workplace_id)
    assert exc.value.kind == "employee"


# --- cross-plugin contract consumption (Gate K) ------------------------------


def test_an_employee_who_is_not_a_workforce_member_is_rejected(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate K: membership comes from the ``workplace.workforce`` contract.

    The outsider is a real employee of the same organization — core people alone
    would accept them. Only the workforce contract knows they are not on this
    workplace's roster, so this proves the roster was consumed, not assumed.
    """
    with pytest.raises(NotFoundError) as exc:
        _record(attendance_kernel, world.outsider_id, world.workplace_id)
    assert exc.value.kind == "workforce_membership"


def test_recording_requires_the_workplaces_view_right(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """The workforce contract authorizes its caller, not the calling plugin.

    An actor who may manage attendance but cannot view the workplace's roster is
    denied by the contract itself — Gate M applies across the plugin boundary.
    """
    context = attendance_kernel.context_for("attendance_operations")
    scope = context.scope.resolve(world.org_id)
    context.authorization.grant("user.no_roster_view", ATTENDANCE_MANAGER_ROLE, scope)

    with pytest.raises(AuthorizationError):
        _record(
            attendance_kernel,
            world.member_id,
            world.workplace_id,
            actor="user.no_roster_view",
        )


def test_recording_at_an_unknown_workplace_is_rejected(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """The workforce contract answers for a workplace that does not exist."""
    with pytest.raises(NotFoundError) as exc:
        _record(attendance_kernel, world.member_id, "wpl_no_such_workplace")
    assert exc.value.kind == "workplace"


# --- audit (Gate L) ---------------------------------------------------------


def test_recording_writes_an_audit_record(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    _record(attendance_kernel, world.member_id, world.workplace_id)

    context = attendance_kernel.context_for("attendance_operations")
    records = context.audit.list_records(organization_id=world.org_id, limit=20)
    assert any(r.action == "attendance.recorded" for r in records)


# --- authorization and scope (Gates M, N) -----------------------------------


def test_recording_requires_the_capability(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate M: without any grant the record is denied."""
    with pytest.raises(AuthorizationError):
        _record(
            attendance_kernel,
            world.member_id,
            world.workplace_id,
            actor="user.unauthorized",
        )


def test_an_actor_scoped_elsewhere_cannot_record(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate N: an actor granted only in Northwind cannot record in Acme."""
    attendance_context = attendance_kernel.context_for("attendance_operations")
    workplace_context = attendance_kernel.context_for("workplace_operations")
    foreign = workplace_context.scope.resolve(world.other_org_id)
    attendance_context.authorization.grant("user.northwind_only", ATTENDANCE_MANAGER_ROLE, foreign)
    workplace_context.authorization.grant("user.northwind_only", WORKPLACE_VIEWER_ROLE, foreign)

    with pytest.raises(AuthorizationError):
        _record(
            attendance_kernel,
            world.member_id,
            world.workplace_id,
            actor="user.northwind_only",
        )


def test_the_summary_is_scoped_to_its_organization(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate N on the query: Acme's actor cannot read Northwind's summary."""
    with pytest.raises(AuthorizationError):
        attendance_kernel.registries.contracts.invoke(
            ATTENDANCE_DAILY_SUMMARY_CONTRACT,
            DailySummaryRequest(
                workplace_id=world.other_workplace_id,
                date=DAY,
                actor_id=ACTOR,
            ),
        )


# --- contracts and the composable dataset (Gate G, Gate O) ------------------


def test_daily_summary_contract_answers_through_the_registry(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    _record(
        attendance_kernel,
        world.member_id,
        world.workplace_id,
        AttendanceStatus.REMOTE,
    )

    summary = attendance_kernel.registries.contracts.invoke(
        ATTENDANCE_DAILY_SUMMARY_CONTRACT,
        DailySummaryRequest(workplace_id=world.workplace_id, date=DAY, actor_id=ACTOR),
    )
    summary = cast("DailySummary", summary)

    assert summary.workplace_id == world.workplace_id
    assert summary.recorded_count == 1
    entry = summary.entries[0]
    assert entry.employee_id == world.member_id
    assert entry.status == AttendanceStatus.REMOTE
    assert entry.full_name == "Ada Lovelace"


def test_the_daily_summary_dataset_is_discoverable_by_report_studio(
    attendance_kernel: Kernel,
    world: World,
) -> None:
    """Gate O: Report Studio composes this dataset without naming this plugin."""
    _record(attendance_kernel, world.member_id, world.workplace_id)

    datasets = {d.dataset_id: d for d in _render(attendance_kernel, world.org_id).datasets}
    assert ATTENDANCE_DATASET_ID in datasets
    dataset = datasets[ATTENDANCE_DATASET_ID]
    assert dataset.columns == (
        "employee_number",
        "full_name",
        "attendance_date",
        "attendance_status",
    )
    assert dataset.rows == (
        ("EMP-1", "Ada Lovelace", DAY.isoformat(), AttendanceStatus.PRESENT.value),
    )

    # Disable the plugin and the dataset is gone — discovery, not hardcoding.
    attendance_kernel.disable("attendance_operations")
    remaining = {d.dataset_id for d in _render(attendance_kernel, world.org_id).datasets}
    assert ATTENDANCE_DATASET_ID not in remaining


# --- events (Gate H) --------------------------------------------------------


def test_recording_publishes_a_transactional_event(
    attendance_kernel: Kernel,
    world: World,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    record = _record(attendance_kernel, world.member_id, world.workplace_id)

    # The event is registered (Gate H) and committed to the outbox (section 21):
    # a fresh transaction sees the envelope the write produced.
    with uow_factory() as uow:
        pending = uow.outbox.pending(limit=50)
    assert attendance_kernel.registries.events.publishers_of(ATTENDANCE_RECORDED) == [
        "attendance_operations"
    ]
    assert any(
        e.event_id == ATTENDANCE_RECORDED
        and e.event.payload.get("attendance_id") == record.attendance_id
        for e in pending
    )


# --- idempotency and recording semantics ------------------------------------


def test_recording_the_same_employee_workplace_and_date_twice_upserts(
    attendance_kernel: Kernel,
    world: World,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """The (workplace, employee, date) triple is the identity: a retry updates.

    A retry can never add a second row for one person on one day, so a day's
    headcount can never double-count.
    """
    _record(attendance_kernel, world.member_id, world.workplace_id, AttendanceStatus.PRESENT)
    updated = _record(
        attendance_kernel,
        world.member_id,
        world.workplace_id,
        AttendanceStatus.ON_LEAVE,
    )

    assert updated.status == AttendanceStatus.ON_LEAVE
    summary = _plugin(attendance_kernel).daily_summary(world.workplace_id, DAY)
    assert summary.recorded_count == 1
    assert summary.entries[0].status == AttendanceStatus.ON_LEAVE

    # Both passes are audited, with distinct actions.
    context = attendance_kernel.context_for("attendance_operations")
    actions = [r.action for r in context.audit.list_records(organization_id=world.org_id, limit=50)]
    assert "attendance.recorded" in actions
    assert "attendance.updated" in actions

    # Both events were published, flagged created vs updated.
    with uow_factory() as uow:
        envelopes = [e for e in uow.outbox.pending(limit=50) if e.event_id == ATTENDANCE_RECORDED]
    flags = [e.event.payload.get("updated") for e in envelopes]
    assert flags.count(False) == 1
    assert flags.count(True) == 1


# --- the production commit path --------------------------------------------


def test_a_direct_record_commits_without_a_manual_commit(
    attendance_kernel: Kernel,
    world: World,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """The compatibility wrapper commits through the platform runner (§21).

    A caller driving the plugin's service surface directly never commits; the
    wrapper's runner must persist the row and outbox event before it returns.
    """
    record = _record(attendance_kernel, world.member_id, world.workplace_id)

    with uow_factory() as uow:
        assert isinstance(uow, SqlUnitOfWork)
        rows = list(uow.session.execute(text("SELECT employee_id, status FROM att_attendance")))
        pending = uow.outbox.pending(limit=50)

    assert [(row[0], row[1]) for row in rows] == [(world.member_id, AttendanceStatus.PRESENT.value)]
    assert any(
        e.event_id == ATTENDANCE_RECORDED
        and e.event.payload.get("attendance_id") == record.attendance_id
        for e in pending
    )


def test_direct_attendance_reads_run_through_the_platform_runner(
    attendance_kernel: Kernel,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = attendance_kernel.context_for("attendance_operations")
    calls = 0
    original_run = context.transactions.run

    def tracked_run(operation: Callable[[], object]) -> object:
        nonlocal calls
        calls += 1
        return original_run(operation)

    monkeypatch.setattr(context.transactions, "run", tracked_run)

    _plugin(attendance_kernel).daily_summary(world.workplace_id, DAY)

    assert calls == 1


def test_publication_failure_rolls_back_the_whole_direct_record(
    attendance_kernel: Kernel,
    world: World,
    uow_factory: Callable[[], UnitOfWorkPort],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed publication leaves no partial record for a later commit."""
    context = attendance_kernel.context_for("attendance_operations")
    original_publish = context.events.publish
    failed_once = False

    def publish_then_fail(event: DomainEvent) -> None:
        nonlocal failed_once
        original_publish(event)
        if not failed_once:
            failed_once = True
            raise RuntimeError("publication failed")

    monkeypatch.setattr(context.events, "publish", publish_then_fail)

    with pytest.raises(RuntimeError, match="publication failed"):
        _record(attendance_kernel, world.member_id, world.workplace_id)

    with uow_factory() as uow:
        assert isinstance(uow, SqlUnitOfWork)
        rows = list(uow.session.execute(text("SELECT employee_id FROM att_attendance")))
        audits = list(uow.audit.all(organization_id=world.org_id, limit=50))
        envelopes = list(uow.outbox.pending(limit=50))

    assert rows == []
    assert not any(
        record.action in {"attendance.recorded", "attendance.updated"} for record in audits
    )
    assert not any(envelope.event_id == ATTENDANCE_RECORDED for envelope in envelopes)

    record = _record(attendance_kernel, world.member_id, world.workplace_id)

    with uow_factory() as uow:
        assert isinstance(uow, SqlUnitOfWork)
        rows = list(uow.session.execute(text("SELECT employee_id FROM att_attendance")))
        audits = list(uow.audit.all(organization_id=world.org_id, limit=50))
        envelopes = list(uow.outbox.pending(limit=50))

    assert [(row[0],) for row in rows] == [(world.member_id,)]
    assert any(record_audit.action == "attendance.recorded" for record_audit in audits)
    assert any(
        envelope.event_id == ATTENDANCE_RECORDED
        and envelope.event.payload.get("attendance_id") == record.attendance_id
        for envelope in envelopes
    )


def test_contract_invocation_does_not_nest_the_direct_runner(
    attendance_kernel: Kernel,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registry, not a bound handler, owns contract transactions."""
    context = attendance_kernel.context_for("attendance_operations")

    def forbidden(operation: Callable[[], object]) -> object:
        raise AssertionError("bound contract handler entered direct runner")

    monkeypatch.setattr(context.transactions, "run", forbidden)

    summary = attendance_kernel.registries.contracts.invoke(
        ATTENDANCE_DAILY_SUMMARY_CONTRACT,
        DailySummaryRequest(workplace_id=world.workplace_id, date=DAY, actor_id=ACTOR),
    )

    assert cast("DailySummary", summary).workplace_id == world.workplace_id
