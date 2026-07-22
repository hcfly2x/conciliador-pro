from __future__ import annotations

import sqlite3
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import auth


class LoginRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "auth.db"
        self.original_connect = auth.db_connect
        self.original_max = auth.LOGIN_MAX_ATTEMPTS
        self.original_cache_max = auth._TOKEN_CACHE_MAX
        self.sql_statements: list[str] = []

        @contextmanager
        def connect():
            conn = sqlite3.connect(self.db_path)
            conn.set_trace_callback(self.sql_statements.append)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

        auth.db_connect = connect  # type: ignore[assignment]
        auth.LOGIN_MAX_ATTEMPTS = 3
        auth.invalidate_token_cache()
        auth.init_auth_db()

    def tearDown(self) -> None:
        auth.db_connect = self.original_connect  # type: ignore[assignment]
        auth.LOGIN_MAX_ATTEMPTS = self.original_max
        auth._TOKEN_CACHE_MAX = self.original_cache_max
        auth.invalidate_token_cache()
        self.tmp.cleanup()

    def test_failed_attempts_temporarily_block_login(self) -> None:
        for _ in range(3):
            auth.record_login_failure("user", "127.0.0.1")

        self.assertFalse(auth.login_allowed("user", "127.0.0.1"))

    def test_success_clears_failed_attempts(self) -> None:
        auth.record_login_failure("user", "127.0.0.1")
        auth.clear_login_failures("user", "127.0.0.1")

        self.assertTrue(auth.login_allowed("user", "127.0.0.1"))

    def test_session_persists_only_token_digest_and_authenticates(self) -> None:
        user_id = str(uuid.uuid4())
        with auth.db_connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,is_active,created_at) VALUES (?,?,?,?,1,?)",
                (
                    user_id,
                    "session-user",
                    auth.hash_password("secret"),
                    auth.ROLE_ADMIN,
                    auth._now(),
                ),
            )

        token = auth.create_session(user_id)
        with auth.db_connect() as conn:
            stored = conn.execute(
                "SELECT token FROM sessions WHERE user_id=?", (user_id,)
            ).fetchone()[0]

        self.assertNotEqual(stored, token)
        self.assertEqual(stored, auth._session_token_digest(token))
        self.assertEqual(auth.user_for_token(token)["username"], "session-user")

        auth.destroy_session(token)
        with auth.db_connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(1) FROM sessions WHERE user_id=?", (user_id,)
                ).fetchone()[0],
                0,
            )

    def test_fresh_session_is_not_updated_on_consecutive_requests(self) -> None:
        user_id = str(uuid.uuid4())
        with auth.db_connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,is_active,created_at) VALUES (?,?,?,?,1,?)",
                (
                    user_id,
                    "cache-user",
                    auth.hash_password("secret"),
                    auth.ROLE_ADMIN,
                    auth._now(),
                ),
            )
        token = auth.create_session(user_id)
        auth.invalidate_token_cache()
        self.sql_statements.clear()

        self.assertIsNotNone(auth.user_for_token(token))
        self.assertIsNotNone(auth.user_for_token(token))

        updates = [
            sql
            for sql in self.sql_statements
            if sql.lstrip().upper().startswith("UPDATE SESSIONS")
        ]
        self.assertEqual(updates, [])

    def test_token_cache_evicts_least_recently_used_entry(self) -> None:
        auth._TOKEN_CACHE_MAX = 2
        auth._cache_put("a", {"id": "a"})
        auth._cache_put("b", {"id": "b"})
        self.assertEqual(auth._cache_get("a"), {"id": "a"})

        auth._cache_put("c", {"id": "c"})

        self.assertIsNone(auth._cache_get("b"))
        self.assertEqual(list(auth._TOKEN_CACHE), ["a", "c"])

    def test_init_removes_expired_sessions(self) -> None:
        with auth.db_connect() as conn:
            conn.execute(
                "INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                (
                    "expired",
                    "user",
                    "2020-01-01T00:00:00+00:00",
                    "2020-01-02T00:00:00+00:00",
                ),
            )

        auth.init_auth_db()

        with auth.db_connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE token='expired'"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
