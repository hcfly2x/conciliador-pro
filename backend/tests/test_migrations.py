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
        self.assertEqual(run_migrations(conn), [1, 2])
        self.assertEqual(run_migrations(conn), [])
        rows = conn.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2])
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
