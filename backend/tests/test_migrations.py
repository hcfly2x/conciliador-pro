from __future__ import annotations

import sqlite3
import unittest

from migrations import MigrationError, run_migrations


class MigrationRunnerTests(unittest.TestCase):
    def make_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        for table in (
            "import_jobs",
            "seed_import_jobs",
            "suggestion_jobs",
            "recalculation_jobs",
        ):
            conn.execute(
                f"CREATE TABLE {table}(id TEXT PRIMARY KEY,status TEXT,created_at TEXT)"
            )
        return conn

    def test_applies_each_version_once_and_creates_queue_indexes(self) -> None:
        conn = self.make_connection()
        self.assertEqual(run_migrations(conn), [1, 2, 3])
        self.assertEqual(run_migrations(conn), [])
        rows = conn.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2, 3])
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        self.assertIn("idx_import_jobs_queue", indexes)
        self.assertIn("idx_recalculation_jobs_queue", indexes)

    def test_rejects_checksum_changed_after_application(self) -> None:
        conn = self.make_connection()
        run_migrations(conn)
        conn.execute(
            "UPDATE schema_migrations SET checksum='alterada' WHERE version=2"
        )
        with self.assertRaises(MigrationError):
            run_migrations(conn)

    def test_restores_the_real_august_payment_once(self) -> None:
        conn = self.make_connection()
        self.addCleanup(conn.close)
        conn.execute(
            """
            CREATE TABLE imported_files(
              id TEXT PRIMARY KEY,file_hash TEXT,account_id TEXT,
              total_inserted INTEGER,total_duplicates INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY,tx_key TEXT UNIQUE,date TEXT,
              competence_month TEXT,description TEXT,description_norm TEXT,
              merchant_norm TEXT,transaction_method TEXT,counterparty_name TEXT,
              bank_reference TEXT,amount REAL,type TEXT,status TEXT,account_id TEXT,
              category_id TEXT,subcategory_id TEXT,notes TEXT,
              suggested_category_id TEXT,suggested_subcategory_id TEXT,
              match_probability REAL,match_notes TEXT,history_match_id TEXT,
              identity_score REAL,installment_current INTEGER,
              installment_total INTEGER,flags TEXT,imported_file_id TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO imported_files VALUES (?,?,?,?,?)",
            (
                "july",
                "2fc1d5a591e7e33239e3bf68588b1793490429fa",
                "card",
                245,
                0,
            ),
        )
        conn.execute(
            "INSERT INTO imported_files VALUES (?,?,?,?,?)",
            (
                "august",
                "da8bf90ec7aa921216e152572912ef65a7aa2991",
                "card",
                154,
                1,
            ),
        )
        conn.execute(
            """
            INSERT INTO transactions VALUES(
              'july-payment','july-key','2024-07-05','2024/07',
              'PAGAMENTO DE FATURA','pagamento de fatura','de fatura',
              'credit_card','de fatura','',2500.00,'income','pending','card',
              NULL,NULL,'',NULL,NULL,0,'',NULL,0,NULL,NULL,
              'INTER_ACCOUNT,fatura','july'
            )
            """
        )

        self.assertEqual(run_migrations(conn), [1, 2, 3])
        self.assertEqual(run_migrations(conn), [])
        restored = conn.execute(
            """
            SELECT competence_month,amount,imported_file_id
            FROM transactions WHERE imported_file_id='august'
            """
        ).fetchone()
        self.assertEqual(restored, ("2024/08", 2500.0, "august"))
        counters = conn.execute(
            "SELECT total_inserted,total_duplicates FROM imported_files WHERE id='august'"
        ).fetchone()
        self.assertEqual(counters, (155, 0))
