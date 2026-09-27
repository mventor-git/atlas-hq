"""``atlas-hq operator-init`` — the local operator bootstrap, and its refusals.

The web console's development login acts as whichever principal
``ATLAS_WEB_OPERATOR_PRINCIPAL`` names, and it answers 503 until that principal
exists and is active. This suite pins the one supported way to put one there, and
— more importantly — pins the ways it must *refuse* to act:

* no implicit principal, no implicit scope, and nothing granted that ``--grant``
  did not name;
* no implicit organization either: a ``--organization`` that does not exist is a
  refusal until ``--create-organization`` asks for that id out loud, and an
  organization that is already there is reused rather than rewritten;
* the audit actor is a constant, not something the caller can supply;
* an unrecognised capability, a non-loopback database, and a missing database
  configuration are all refusals with a message, never a traceback and never a
  partial write;
* migration ``004_principal_metadata`` is recorded through the existing runner,
  not assumed.

Everything runs against the real PostgreSQL fixture, so the grants, the audit
records, and the schema are the ones a deployed database would hold.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from tests.synthetic import refresh_metadata_cache

from atlas_hq.cli import (
    OPERATOR_INIT_ACTOR,
    OPERATOR_INIT_GRANTS,
    boot_kernel,
    build_parser,
    main,
)

PRINCIPAL = "atlas.local.operator.webtest"
ORG = "org-operator-init"
ORG_NAME = "Atlas Local"
OPERATOR_TEST_ENTRY_POINT_GROUP = "atlas.test.operator-init"


@pytest.fixture
def operator_plugins(isolated_plugins: Path) -> None:
    """Publish the real reporting pair behind a test-only entry-point group.

    ``report.render`` and ``self.monthly.report.view`` belong to plugins, so
    granting them means the plugins have to be discoverable and enabled. The
    other nine shipped plugins stay out of the registry, as in every other test.
    """
    dist_info = isolated_plugins / "atlas-hq-operator-init-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: atlas-hq-operator-init\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{OPERATOR_TEST_ENTRY_POINT_GROUP}]\n"
        "report_studio = atlas_plugins.report_studio:ReportStudioPlugin\n"
        "self_reporting = atlas_plugins.self_reporting:SelfReportingPlugin\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()


@pytest.fixture
def operator_env(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    test_schema: str,
) -> None:
    """Point the command at this test's isolated schema, exactly as an operator would."""
    monkeypatch.setenv("ATLAS_DATABASE_URL", database_url)
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", test_schema)


@pytest.fixture
def existing_organization(test_engine: Engine) -> None:
    """The scope the command needs, put there directly.

    A test about principals, grants or migrations is not a test about creating an
    organization, and one that asked for ``--create-organization`` would be
    asserting the creation path while claiming to assert something else.
    """
    _seed_organization(test_engine, ORG, "Existing Organization", ORG)


def _argv(*rest: str, group: str = OPERATOR_TEST_ENTRY_POINT_GROUP) -> list[str]:
    return ["--entry-point-group", group, "operator-init", *rest]


def _grants(engine: Engine, principal_id: str) -> list[tuple[str, str | None, str | None]]:
    with engine.begin() as connection:
        return [
            (str(row[0]), row[1], row[2])
            for row in connection.execute(
                text(
                    "SELECT capability_id, organization_id, principal_scope_id "
                    "FROM capability_grant "
                    "WHERE principal_id = :p "
                    "ORDER BY capability_id, organization_id NULLS FIRST"
                ),
                {"p": principal_id},
            )
        ]


def _audit_actors(engine: Engine, action: str) -> list[str]:
    with engine.begin() as connection:
        return [
            str(row[0])
            for row in connection.execute(
                text("SELECT actor FROM audit WHERE action = :a ORDER BY occurred_at"),
                {"a": action},
            )
        ]


def _principal_row(engine: Engine, principal_id: str) -> tuple[bool, str] | None:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT active, display_name FROM principal WHERE principal_id = :p"),
            {"p": principal_id},
        ).first()
    return None if row is None else (bool(row[0]), str(row[1]))


def _seed_principal(engine: Engine, principal_id: str, *, active: bool) -> None:
    """Put a principal in the store directly, so the command meets a pre-existing one."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO principal "
                "(principal_id, display_name, active, metadata, created_at, updated_at) "
                "VALUES (:p, '', :a, '{}'::jsonb, now(), now())"
            ),
            {"p": principal_id, "a": active},
        )


def _seed_organization(engine: Engine, organization_id: str, name: str, code: str) -> None:
    """Put an organization in the store directly, so the command meets a pre-existing one."""
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO organization (organization_id, name, code) VALUES (:o, :n, :c)"),
            {"o": organization_id, "n": name, "c": code},
        )


def _organization_row(engine: Engine, organization_id: str) -> tuple[str, str] | None:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT name, code FROM organization WHERE organization_id = :o"),
            {"o": organization_id},
        ).first()
    return None if row is None else (str(row[0]), str(row[1]))


def _organizations(engine: Engine) -> list[tuple[str, str, str]]:
    with engine.begin() as connection:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                text(
                    "SELECT organization_id, name, code FROM organization ORDER BY organization_id"
                )
            )
        ]


# --- what a successful run does --------------------------------------------


def test_it_creates_an_active_principal_and_grants_only_what_was_named(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        _argv("--principal", PRINCIPAL, "--organization", ORG, "--grant", "authorization.manage")
    )

    assert exit_code == 0
    assert _principal_row(test_engine, PRINCIPAL) is not None
    # Both scopes, because the console authorizes against both: management and the
    # self report decide in the operator's own scope, report render in the
    # organization. Nothing wider, and nothing that was not named.
    assert _grants(test_engine, PRINCIPAL) == [
        ("authorization.manage", None, PRINCIPAL),
        ("authorization.manage", ORG, None),
    ]
    output = capsys.readouterr().out
    assert PRINCIPAL in output
    assert ORG in output
    assert "authorization.manage" in output


def test_it_grants_nothing_when_no_capability_was_named(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    """The whole point of the flags: no flag, no authority."""
    exit_code = main(_argv("--principal", PRINCIPAL, "--organization", ORG))

    assert exit_code == 0
    assert _grants(test_engine, PRINCIPAL) == []


def test_every_documented_grant_is_accepted_by_name(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    argv = _argv("--principal", PRINCIPAL, "--organization", ORG)
    for name in OPERATOR_INIT_GRANTS:
        argv += ["--grant", name]

    exit_code = main(argv)

    assert exit_code == 0
    assert _grants(test_engine, PRINCIPAL) == [
        ("assistant.use", None, PRINCIPAL),
        ("assistant.use", ORG, None),
        ("authorization.manage", None, PRINCIPAL),
        ("authorization.manage", ORG, None),
        ("report.render", None, PRINCIPAL),
        ("report.render", ORG, None),
        ("self.monthly.report.view", None, PRINCIPAL),
        ("self.monthly.report.view", ORG, None),
    ]


def test_running_it_against_an_already_active_principal_changes_nothing(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    """The idempotence that matters: re-running over a live principal adds no records.

    Re-running ``main`` in one process is a different question — the kernel cannot
    re-declare a role it already declared in that process, which is a boot-level
    limitation rather than anything about this command — so the state after the
    first run is what this pins. A real second process is the subprocess case.
    """
    _seed_principal(test_engine, PRINCIPAL, active=True)

    assert (
        main(
            _argv(
                "--principal", PRINCIPAL, "--organization", ORG, "--grant", "authorization.manage"
            )
        )
        == 0
    )

    assert _grants(test_engine, PRINCIPAL) == [
        ("authorization.manage", None, PRINCIPAL),
        ("authorization.manage", ORG, None),
    ]
    # Not "reactivated" — an already-active principal is left exactly as it was.
    assert _audit_actors(test_engine, "authorization.principal.active_changed") == []
    assert _audit_actors(test_engine, "authorization.principal.created") == []
    # Exactly one grant audit per (capability, scope) pair, and no duplicates.
    assert _audit_actors(test_engine, "authorization.capability.granted") == [
        OPERATOR_INIT_ACTOR,
        OPERATOR_INIT_ACTOR,
    ]


def test_it_activates_an_existing_inactive_principal(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    _seed_principal(test_engine, PRINCIPAL, active=False)

    assert main(_argv("--principal", PRINCIPAL, "--organization", ORG)) == 0

    row = _principal_row(test_engine, PRINCIPAL)
    assert row is not None and row[0] is True
    assert _audit_actors(test_engine, "authorization.principal.active_changed") == [
        OPERATOR_INIT_ACTOR
    ]


def test_every_record_is_audited_under_the_fixed_cli_actor(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    main(_argv("--principal", PRINCIPAL, "--organization", ORG, "--grant", "authorization.manage"))

    with test_engine.begin() as connection:
        actors = {
            str(row[0])
            for row in connection.execute(
                text("SELECT DISTINCT actor FROM audit WHERE principal_id = :p"),
                {"p": PRINCIPAL},
            )
        }
    assert actors == {OPERATOR_INIT_ACTOR}


# --- the empty database -----------------------------------------------------


def test_it_creates_the_organization_the_scope_needs(
    operator_env: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reported failure: a reachable database with nothing in it.

    ``--organization`` is still the operator's to choose, ``--create-organization``
    is still them saying so out loud, and the row that lands carries exactly the
    three values the command line named. No plugin is needed: the organization
    table is Core's own.
    """
    assert _organizations(test_engine) == []

    exit_code = main(
        [
            "--entry-point-group",
            "atlas.test.no-such-group",
            "operator-init",
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--create-organization",
            "--organization-name",
            ORG_NAME,
        ]
    )

    assert exit_code == 0
    # id, name and code are all the operator's; the code is the id they typed.
    assert _organizations(test_engine) == [(ORG, ORG_NAME, ORG)]
    assert _principal_row(test_engine, PRINCIPAL) is not None
    assert _audit_actors(test_engine, "organization.created") == [OPERATOR_INIT_ACTOR]
    assert "created" in capsys.readouterr().out


def test_it_names_the_organization_when_no_name_was_given(
    operator_env: None,
    test_engine: Engine,
) -> None:
    """A display name is a label, not an identity: the id doubles as the default."""
    exit_code = main(
        [
            "--entry-point-group",
            "atlas.test.no-such-group",
            "operator-init",
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--create-organization",
        ]
    )

    assert exit_code == 0
    assert _organization_row(test_engine, ORG) == (ORG, ORG)


def test_it_reuses_an_existing_organization_and_never_overwrites_it(
    operator_env: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--create-organization`` is a licence to add a missing row, not to edit one.

    A different ``--organization-name`` against an organization that already exists
    is the dangerous case: a silent rename is how a populated database loses the
    name its people and reports are filed under.
    """
    _seed_organization(test_engine, ORG, "Real Name", "real-code")

    exit_code = main(
        [
            "--entry-point-group",
            "atlas.test.no-such-group",
            "operator-init",
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--create-organization",
            "--organization-name",
            ORG_NAME,
        ]
    )

    assert exit_code == 0
    assert _organizations(test_engine) == [(ORG, "Real Name", "real-code")]
    assert _audit_actors(test_engine, "organization.created") == []
    assert "reused" in capsys.readouterr().out


def test_a_created_organization_holds_only_the_named_grants_in_the_two_scopes(
    operator_plugins: None,
    operator_env: None,
    test_engine: Engine,
) -> None:
    """Creating the scope does not widen it, and does not grant by association.

    The two named capabilities land in the operator's own scope and in the
    organization that was just created — no more rows, no other organization, and
    nothing that ``--grant`` did not ask for.
    """
    exit_code = main(
        _argv(
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--create-organization",
            "--organization-name",
            ORG_NAME,
            "--grant",
            "authorization.manage",
            "--grant",
            "assistant.use",
        )
    )

    assert exit_code == 0
    assert _grants(test_engine, PRINCIPAL) == [
        ("assistant.use", None, PRINCIPAL),
        ("assistant.use", ORG, None),
        ("authorization.manage", None, PRINCIPAL),
        ("authorization.manage", ORG, None),
    ]
    assert _organizations(test_engine) == [(ORG, ORG_NAME, ORG)]


def test_running_the_whole_command_twice_is_idempotent(
    operator_env: None,
    test_engine: Engine,
) -> None:
    """A second process over the same database changes nothing.

    Idempotence is a claim about a *re-run*, so it is tested with a re-run: a
    separate interpreter, exactly what an operator does the next morning. The
    count of each audit record is the assertion — a duplicate principal, a
    duplicate organization, or a duplicated grant would each show up here.
    """
    argv = [
        "--entry-point-group",
        "atlas.test.no-such-group",
        "operator-init",
        "--principal",
        PRINCIPAL,
        "--organization",
        ORG,
        "--create-organization",
        "--organization-name",
        ORG_NAME,
        "--grant",
        "authorization.manage",
    ]
    env = os.environ.copy()

    for _attempt in range(2):
        completed = subprocess.run(
            [sys.executable, "-m", "atlas_hq.cli", *argv],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    assert _organizations(test_engine) == [(ORG, ORG_NAME, ORG)]
    assert _grants(test_engine, PRINCIPAL) == [
        ("authorization.manage", None, PRINCIPAL),
        ("authorization.manage", ORG, None),
    ]
    assert _audit_actors(test_engine, "organization.created") == [OPERATOR_INIT_ACTOR]
    assert _audit_actors(test_engine, "authorization.principal.created") == [OPERATOR_INIT_ACTOR]
    assert _audit_actors(test_engine, "authorization.capability.granted") == [
        OPERATOR_INIT_ACTOR,
        OPERATOR_INIT_ACTOR,
    ]


# --- refusals ---------------------------------------------------------------


def test_it_refuses_a_missing_organization_and_says_the_command_that_creates_it(
    operator_plugins: None,
    operator_env: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No flag, no organization — and the refusal has to be actionable.

    A message that only reported the absence would send the operator looking for an
    id that does not exist anywhere yet, so the exact command is in the message.
    Nothing is written: not the principal, not a grant, not the organization.
    """
    exit_code = main(_argv("--principal", PRINCIPAL, "--organization", ORG))

    assert exit_code == 2
    output = capsys.readouterr().out
    assert "operator-init refused" in output
    assert f"--organization {ORG} --create-organization" in output
    assert f"--principal {PRINCIPAL}" in output
    assert _organizations(test_engine) == []
    assert _principal_row(test_engine, PRINCIPAL) is None
    assert _grants(test_engine, PRINCIPAL) == []


def test_it_refuses_an_organization_name_that_would_rename_an_existing_organization(
    operator_plugins: None,
    operator_env: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--organization-name`` without ``--create-organization`` is a mistake.

    Silently ignoring it would leave the operator believing they had named the
    organization they just bootstrapped.
    """
    _seed_organization(test_engine, ORG, "Real Name", "real-code")

    exit_code = main(
        _argv("--principal", PRINCIPAL, "--organization", ORG, "--organization-name", ORG_NAME)
    )

    assert exit_code == 2
    assert "--organization-name" in capsys.readouterr().out
    assert _organizations(test_engine) == [(ORG, "Real Name", "real-code")]


def test_it_refuses_a_blank_organization_name(
    operator_plugins: None,
    operator_env: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        _argv(
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--create-organization",
            "--organization-name",
            "   ",
        )
    )

    assert exit_code == 2
    assert "must not be blank" in capsys.readouterr().out
    assert _organizations(test_engine) == []


def test_it_refuses_to_choose_the_principal_or_the_scope(
    operator_plugins: None,
    operator_env: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both are required. A default would be a default the operator never chose."""
    for argv in (_argv("--organization", ORG), _argv("--principal", PRINCIPAL)):
        with pytest.raises(SystemExit) as exit_info:
            main(argv)
        assert exit_info.value.code == 2

    for argv in (
        _argv("--principal", "   ", "--organization", ORG),
        _argv("--principal", PRINCIPAL, "--organization", "   "),
    ):
        assert main(argv) == 2
    assert "must not be blank" in capsys.readouterr().out


def test_it_refuses_a_capability_it_was_not_given(
    operator_plugins: None,
    operator_env: None,
    test_engine: Engine,
) -> None:
    """A typo must fail loudly; a silently skipped grant leaves a broken operator."""
    with pytest.raises(SystemExit) as exit_info:
        main(_argv("--principal", PRINCIPAL, "--organization", ORG, "--grant", "report.renred"))

    assert exit_info.value.code == 2
    assert _principal_row(test_engine, PRINCIPAL) is None


def test_it_refuses_a_capability_no_installed_plugin_provides(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty group registers no plugin capability, so the grant cannot be written."""
    exit_code = main(
        _argv(
            "--principal",
            PRINCIPAL,
            "--organization",
            ORG,
            "--grant",
            "report.render",
            group="atlas.test.no-such-group",
        )
    )

    assert exit_code == 2
    assert "operator-init refused" in capsys.readouterr().out
    assert _grants(test_engine, PRINCIPAL) == []


def test_it_refuses_a_database_that_is_not_loopback(
    operator_plugins: None,
    operator_env: None,
    monkeypatch: pytest.MonkeyPatch,
    test_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "ATLAS_DATABASE_URL", "postgresql+psycopg://atlas:secret@db.example.com:5432/atlas_hq"
    )

    exit_code = main(_argv("--principal", PRINCIPAL, "--organization", ORG))

    assert exit_code == 2
    assert "not loopback" in capsys.readouterr().out
    assert _principal_row(test_engine, PRINCIPAL) is None


def test_it_refuses_a_missing_database_configuration(
    operator_plugins: None,
    operator_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ATLAS_DATABASE_URL", raising=False)

    exit_code = main(_argv("--principal", PRINCIPAL, "--organization", ORG))

    assert exit_code == 2
    assert "ATLAS_DATABASE_URL" in capsys.readouterr().out


def test_the_caller_cannot_name_the_audit_actor() -> None:
    """``--actor`` must not exist: a command that writes its own actor is a forgery."""
    with pytest.raises(SystemExit) as exit_info:
        main(_argv("--principal", PRINCIPAL, "--organization", ORG, "--actor", "someone.else"))

    assert exit_info.value.code == 2


# --- the migration ----------------------------------------------------------


def test_it_records_migration_004_through_the_existing_runner(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    """§38.15: a deployed schema gets the column from a migration, not from create_all.

    ``create_sql_uow_factory`` migrates before ``create_all``, so a schema whose
    ``principal`` table has just been stripped is exactly the case the runner
    defers. This command must finish the job rather than leave it to the next
    process that happens to start.
    """
    with test_engine.begin() as connection:
        connection.execute(text("ALTER TABLE principal DROP COLUMN IF EXISTS metadata"))
        connection.execute(
            text("DELETE FROM schema_migrations WHERE version = '004_principal_metadata'")
        )

    assert main(_argv("--principal", PRINCIPAL, "--organization", ORG)) == 0

    with test_engine.begin() as connection:
        columns = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'principal'"
                )
            )
        }
        versions = {
            str(row[0]) for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
    assert "metadata" in columns
    assert "004_principal_metadata" in versions


def test_it_brings_up_a_schema_that_does_not_exist_yet(
    operator_plugins: None,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    test_engine: Engine,
) -> None:
    """The first run against an empty database is the one that has to work.

    Every other test in this file runs inside a schema the ``test_engine``
    fixture already created, which hides the ordering requirement: the migration
    runner has to be handed a schema that exists before it is handed a table to
    migrate. This one starts from nothing, which is what a real operator's first
    ``operator-init`` looks like — including the one thing there was no id for.
    """
    fresh_schema = f"atlas_test_{uuid.uuid4().hex}"
    monkeypatch.setenv("ATLAS_DATABASE_URL", database_url)
    monkeypatch.setenv("ATLAS_DATABASE_SCHEMA", fresh_schema)
    try:
        assert (
            main(
                _argv(
                    "--principal",
                    PRINCIPAL,
                    "--organization",
                    ORG,
                    "--create-organization",
                    "--organization-name",
                    ORG_NAME,
                )
            )
            == 0
        )

        with test_engine.begin() as connection:
            versions = {
                str(row[0])
                for row in connection.execute(
                    text(f"SELECT version FROM {fresh_schema}.schema_migrations")
                )
            }
            principal_id = connection.execute(
                text(f"SELECT principal_id FROM {fresh_schema}.principal")
            ).scalar()
            organization_id = connection.execute(
                text(f"SELECT organization_id FROM {fresh_schema}.organization")
            ).scalar()
        assert "004_principal_metadata" in versions
        assert principal_id == PRINCIPAL
        assert organization_id == ORG
    finally:
        with test_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {fresh_schema} CASCADE"))


def test_a_plugin_can_declare_the_same_role_twice_against_one_database(
    operator_plugins: None,
    operator_env: None,
    existing_organization: None,
    test_engine: Engine,
) -> None:
    """A role declared without ``capability_kinds`` must survive a second boot.

    ``RoleORM`` has no ``capability_kinds`` column: the repository rebuilds the
    mapping from the capability catalogue, so a role that declared none still
    reads back fully populated. Comparing that derived value against an empty
    declaration used to refuse every role on every boot after the first, which
    meant no plugin could start twice against one database — the second run came
    up half-failed and the console's plugin routes answered 503. This is the
    regression that broke, and it broke the documented setup, so it is pinned
    here rather than left to a manual second run.

    ``test_engine`` is requested for its teardown, not its data: the boot below
    creates the schema if it is absent, and only the fixture drops it again.
    """
    argv = _argv("--principal", PRINCIPAL, "--organization", ORG)
    assert main(argv) == 0
    assert test_engine is not None

    # A second kernel over the same schema is exactly what the next server start is.
    kernel, result = boot_kernel(
        build_parser().parse_args(["--entry-point-group", OPERATOR_TEST_ENTRY_POINT_GROUP]),
        with_persistence=True,
    )
    kernel.enable_all()

    assert result.failed == []
    assert sorted(getattr(kernel, "_instances", {})) == ["report_studio", "self_reporting"]


def test_the_parser_keeps_the_grant_choices_closed(
    operator_env: None,
) -> None:
    """The accepted set is data, so the help text and the parser cannot drift apart."""
    args = build_parser().parse_args(
        _argv("--principal", PRINCIPAL, "--organization", ORG, "--grant", "assistant.use")
    )

    assert args.command == "operator-init"
    assert args.grant == ["assistant.use"]
    assert args.allow_remote_database is False
    # Nothing is created unless it is asked for: the flags default to refusal.
    assert args.create_organization is False
    assert args.organization_name is None
    assert tuple(OPERATOR_INIT_GRANTS) == (
        "assistant.use",
        "authorization.manage",
        "report.render",
        "self.monthly.report.view",
    )
