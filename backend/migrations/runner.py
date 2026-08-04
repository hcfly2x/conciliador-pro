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


def _restore_santander_august_2024_payment(conn: Any) -> None:
    """Restaura uma ocorrência real omitida pela deduplicação entre faturas."""
    july_hash = "2fc1d5a591e7e33239e3bf68588b1793490429fa"
    august_hash = "da8bf90ec7aa921216e152572912ef65a7aa2991"
    transaction_id = "9878e756-2da2-4b36-aec6-6bf623f233c7"

    try:
        august_file = conn.execute(
            """
            SELECT id,account_id FROM imported_files
            WHERE LOWER(file_hash)=?
            """,
            (august_hash,),
        ).fetchone()
    except Exception as exc:
        # O runner também é testado isoladamente antes da criação das tabelas
        # funcionais. Em produção, init_db cria as tabelas antes das migrations.
        if "imported_files" in str(exc).lower():
            return
        raise
    if not august_file:
        return

    already_restored = conn.execute(
        """
        SELECT COUNT(1) FROM transactions
        WHERE imported_file_id=?
          AND date='2024-07-05'
          AND ROUND(amount,2)=2500.00
          AND description_norm='pagamento de fatura'
          AND type='income'
        """,
        (august_file[0],),
    ).fetchone()[0]
    if int(already_restored or 0) > 0:
        return

    july_source = conn.execute(
        """
        SELECT t.description,t.description_norm,t.amount,t.type,t.flags,
               t.suggested_category_id,t.suggested_subcategory_id,
               t.match_probability,t.match_notes,t.history_match_id,t.identity_score,
               t.merchant_norm,t.transaction_method,t.counterparty_name,t.bank_reference
        FROM transactions t
        JOIN imported_files f ON f.id=t.imported_file_id
        WHERE LOWER(f.file_hash)=?
          AND t.date='2024-07-05'
          AND ROUND(t.amount,2)=2500.00
          AND t.description_norm='pagamento de fatura'
          AND t.type='income'
        LIMIT 1
        """,
        (july_hash,),
    ).fetchone()
    if not july_source:
        return

    tx_key = (
        f"{august_file[1]}|2024-07-05|2500.00|pagamento de fatura|"
        f"income|0|0|{august_hash[:12]}#1"
    )
    conn.execute(
        """
        INSERT INTO transactions(
          id,tx_key,date,competence_month,description,description_norm,
          merchant_norm,transaction_method,counterparty_name,bank_reference,
          amount,type,status,account_id,category_id,subcategory_id,notes,
          suggested_category_id,suggested_subcategory_id,match_probability,
          match_notes,history_match_id,identity_score,installment_current,
          installment_total,flags,imported_file_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            transaction_id,
            tx_key,
            "2024-07-05",
            "2024/08",
            july_source[0],
            july_source[1],
            july_source[11],
            july_source[12],
            july_source[13],
            july_source[14],
            july_source[2],
            july_source[3],
            "pending",
            august_file[1],
            None,
            None,
            "",
            july_source[5],
            july_source[6],
            july_source[7],
            july_source[8],
            july_source[9],
            july_source[10],
            None,
            None,
            july_source[4],
            august_file[0],
        ),
    )
    conn.execute(
        """
        UPDATE imported_files
        SET total_inserted=total_inserted+1,
            total_duplicates=CASE
              WHEN total_duplicates>0 THEN total_duplicates-1
              ELSE 0
            END
        WHERE id=?
        """,
        (august_file[0],),
    )


def _make_categories_hybrid(conn: Any) -> None:
    """Categorias deixam de ser exclusivas de receita ou despesa."""
    conn.execute("UPDATE categories SET type='hybrid' WHERE type<>'hybrid'")


MIGRATIONS = (
    Migration(1, "legacy_schema_baseline_20260722", "a8fb9da9", _baseline),
    Migration(2, "job_queue_status_indexes", "5ee2751d", _add_job_queue_indexes),
    Migration(
        3,
        "restore_santander_august_2024_payment",
        "f35ea46c",
        _restore_santander_august_2024_payment,
    ),
    Migration(4, "make_categories_hybrid", "6cb5bd2a", _make_categories_hybrid),
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
