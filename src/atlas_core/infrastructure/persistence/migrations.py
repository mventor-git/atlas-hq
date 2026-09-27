"""Versioned PostgreSQL migrations for security-critical schema changes."""

from __future__ import annotations

from sqlalchemy import Engine, text

_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(32) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_ADD_CAPABILITY_BINDING = """
ALTER TABLE execution_handle
    ADD COLUMN IF NOT EXISTS capability_id VARCHAR(255)
"""

_ADD_CAPABILITY_SET = """
ALTER TABLE execution_handle
    ADD COLUMN IF NOT EXISTS allowed_capability_ids JSONB NOT NULL DEFAULT '[]'::jsonb
"""

_EXECUTION_HANDLES = """
CREATE TABLE IF NOT EXISTS execution_handle (
    token_hash VARCHAR(64) PRIMARY KEY,
    principal_id VARCHAR(40) NOT NULL,
    identity_id VARCHAR(80),
    capability_id VARCHAR(255) NOT NULL,
    allowed_capability_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    action VARCHAR(255) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    resource_id VARCHAR(255),
    organization_id VARCHAR(40),
    workplace_id VARCHAR(40),
    principal_scope_id VARCHAR(40),
    policy_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
)
"""

#: Contract §38.15: a deployed database gets its principal metadata column from
#: a versioned migration, not from ``create_all``. A fresh schema has no
#: ``principal`` table yet when migrations run, so the statement is guarded and
#: the version is only recorded once the column really exists.
_ADD_PRINCIPAL_METADATA = """
ALTER TABLE principal
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb
"""


def apply_migrations(engine: Engine) -> None:
    """Apply pending migrations in order; never record work that did not happen."""
    with engine.begin() as connection:
        connection.execute(text(_MIGRATION_TABLE))
        applied = {
            str(row[0]) for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
        if "001_execution_handles" in applied:
            table = connection.execute(text("SELECT to_regclass('execution_handle')")).scalar()
            if table is None:
                raise RuntimeError(
                    "migration 001_execution_handles is recorded but execution_handle is missing"
                )
        else:
            connection.execute(text(_EXECUTION_HANDLES))
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('001_execution_handles')")
            )
        if "002_execution_capability_binding" not in applied:
            connection.execute(text(_ADD_CAPABILITY_BINDING))
            connection.execute(
                text(
                    "UPDATE execution_handle SET capability_id = 'legacy' "
                    "WHERE capability_id IS NULL"
                )
            )
            connection.execute(
                text("ALTER TABLE execution_handle ALTER COLUMN capability_id SET NOT NULL")
            )
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version) "
                    "VALUES ('002_execution_capability_binding')"
                )
            )
        if "003_execution_capability_set" not in applied:
            connection.execute(text(_ADD_CAPABILITY_SET))
            connection.execute(
                text(
                    "UPDATE execution_handle "
                    "SET allowed_capability_ids = to_jsonb(ARRAY[capability_id]) "
                    "WHERE allowed_capability_ids = '[]'::jsonb"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (version) "
                    "VALUES ('003_execution_capability_set')"
                )
            )
        if "004_principal_metadata" not in applied and (
            connection.execute(text("SELECT to_regclass('principal')")).scalar() is not None
        ):
            # A fresh schema has no ``principal`` table until ``create_all`` runs,
            # so leave the version unrecorded and let the next run finish the job.
            connection.execute(text(_ADD_PRINCIPAL_METADATA))
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES ('004_principal_metadata')")
            )


__all__ = ["apply_migrations"]
