from __future__ import annotations

import os
import unittest
from unittest import mock

import db


class SqlTranslationTests(unittest.TestCase):
    def test_sql_patterns_used_by_application(self) -> None:
        cases = [
            (
                "SELECT IFNULL(name, '') FROM x",
                False,
                "SELECT COALESCE(name, '') FROM x",
            ),
            (
                "SELECT IFNULL(IFNULL(a,b),c) FROM x",
                False,
                "SELECT COALESCE(COALESCE(a,b),c) FROM x",
            ),
            ("SELECT name COLLATE NOCASE FROM x", False, "SELECT name  FROM x"),
            (
                "CREATE TABLE x(amount REAL)",
                False,
                "CREATE TABLE x(amount DOUBLE PRECISION)",
            ),
            (
                "ALTER TABLE x ADD amount REAL",
                False,
                "ALTER TABLE x ADD amount DOUBLE PRECISION",
            ),
            ("SELECT REAL FROM x", False, "SELECT REAL FROM x"),
            (
                "SELECT ROUND(amount, 2) FROM x",
                False,
                "SELECT ROUND(CAST(amount AS NUMERIC), 2) FROM x",
            ),
            (
                "SELECT ROUND(SUM(amount), 2) FROM x",
                False,
                "SELECT ROUND(CAST(SUM(amount) AS NUMERIC), 2) FROM x",
            ),
            (
                "SELECT ROUND(IFNULL(SUM(amount), 0), 2) FROM x",
                False,
                "SELECT ROUND(CAST(COALESCE(SUM(amount), 0) AS NUMERIC), 2) FROM x",
            ),
            (
                "SELECT ROUND((a + b) / IFNULL(c,1), 2) FROM x",
                False,
                "SELECT ROUND(CAST((a + b) / COALESCE(c,1) AS NUMERIC), 2) FROM x",
            ),
            (
                "SELECT ROUND(CAST(amount AS NUMERIC), 2) FROM x",
                False,
                "SELECT ROUND(CAST(amount AS NUMERIC), 2) FROM x",
            ),
            ("SELECT * FROM x WHERE id=?", True, "SELECT * FROM x WHERE id=%s"),
            (
                "SELECT * FROM x WHERE label LIKE '%fixo%' AND id=?",
                True,
                "SELECT * FROM x WHERE label LIKE '%%fixo%%' AND id=%s",
            ),
            (
                "SELECT * FROM x WHERE label LIKE ? ESCAPE '\\'",
                True,
                "SELECT * FROM x WHERE label LIKE %s ESCAPE '\\'",
            ),
            (
                "UPDATE x SET value=? WHERE id=?",
                True,
                "UPDATE x SET value=%s WHERE id=%s",
            ),
        ]
        for source, has_params, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(db._translate_pg(source, has_params), expected)

    def test_pragma_table_info_translation(self) -> None:
        translated = db._translate_pg("PRAGMA table_info(Transactions)", False)
        self.assertIn("information_schema.columns", translated)
        self.assertIn("table_name = 'transactions'", translated)
        self.assertIn("ORDER BY ordinal_position", translated)

    def test_malformed_round_is_left_unchanged(self) -> None:
        self.assertEqual(
            db._translate_pg("SELECT ROUND(value FROM x", False),
            "SELECT ROUND(value FROM x",
        )

    def test_executemany_translates_placeholders(self) -> None:
        raw_cursor = mock.Mock()
        raw_cursor.rowcount = 2
        raw_connection = mock.Mock()
        raw_connection.cursor.return_value = raw_cursor
        connection = db._PgConnection(raw_connection)

        connection.executemany("INSERT INTO x(a,b) VALUES (?,?)", [(1, 2), (3, 4)])

        raw_cursor.executemany.assert_called_once_with(
            "INSERT INTO x(a,b) VALUES (%s,%s)", [(1, 2), (3, 4)]
        )

    def test_postgres_cursor_exposes_dbapi_description(self) -> None:
        raw_cursor = mock.Mock()
        raw_cursor.rowcount = 1
        raw_cursor.description = [("transaction_id", None, None, None, None, None, None)]

        cursor = db._PgCursor(raw_cursor)

        self.assertIs(cursor.description, raw_cursor.description)
        self.assertEqual([item[0] for item in cursor.description], ["transaction_id"])


class PoolFallbackTests(unittest.TestCase):
    def tearDown(self) -> None:
        db.reset_pool_fallback_counter()

    def test_repeated_pool_failure_stops_opening_direct_connections(self) -> None:
        fake_psycopg = mock.Mock()
        fake_psycopg.connect.return_value = mock.Mock()
        db.reset_pool_fallback_counter()
        with (
            mock.patch.object(db, "IS_POSTGRES", True),
            mock.patch.object(
                db, "_get_pool", side_effect=RuntimeError("pool full"), create=True
            ),
            mock.patch.object(db, "psycopg", fake_psycopg, create=True),
            mock.patch.dict(os.environ, {"DB_POOL_FALLBACKS_PER_MINUTE": "1"}),
        ):
            direct = db.db_connect()
            self.assertIsInstance(direct, db._PgConnection)
            with self.assertRaises(db.PoolOverloadError):
                db.db_connect()

        fake_psycopg.connect.assert_called_once()

    def test_connection_returns_to_the_pool_that_provided_it(self) -> None:
        raw_connection = mock.Mock()
        owner_pool = mock.Mock()
        owner_pool.getconn.return_value = raw_connection
        replacement_pool = mock.Mock()

        with (
            mock.patch.object(db, "IS_POSTGRES", True),
            mock.patch.object(
                db,
                "_get_pool",
                side_effect=[owner_pool, replacement_pool],
                create=True,
            ) as get_pool,
        ):
            with db.db_connect():
                pass

        owner_pool.putconn.assert_called_once_with(raw_connection)
        replacement_pool.putconn.assert_not_called()
        get_pool.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
