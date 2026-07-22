from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable


MigrationApply = Callable[[Any], None]


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    apply: MigrationApply


class MigrationError(RuntimeError):
    pass


def _baseline(_conn: Any) -> None:
    """Marca o schema idempotente legado como baseline versionada."""


def _add_job_queue_indexes(conn: Any) -> None:
    for table in (
        "import_jobs",
        "seed_import_jobs",
        "suggestion_jobs",
        "recalculation_jobs",
    ):
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_queue "
            f"ON {table}(status, created_at)"
        )


MIGRATIONS = (
    Migration(1, "legacy_schema_baseline_20260722", "a8fb9da9", _baseline),
    Migration(2, "job_queue_status_indexes", "5ee2751d", _add_job_queue_indexes),
)


def run_migrations(conn: Any) -> list[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations(
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """
    )
    applied_rows = conn.execute(
        "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): (row[1], row[2]) for row in applied_rows}
    known_versions = {migration.version for migration in MIGRATIONS}
    unknown = sorted(set(applied) - known_versions)
    if unknown:
        raise MigrationError(f"Banco possui migrations desconhecidas: {unknown}")

    executed: list[int] = []
    for migration in MIGRATIONS:
        previous = applied.get(migration.version)
        if previous:
            if previous != (migration.name, migration.checksum):
                raise MigrationError(
                    f"Migration {migration.version} foi alterada depois de aplicada"
                )
            continue
        migration.apply(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)",
            (
                migration.version,
                migration.name,
                migration.checksum,
                dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        executed.append(migration.version)
    return executed
