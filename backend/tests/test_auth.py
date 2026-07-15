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
        @contextmanager
        def connect():
            conn = sqlite3.connect(self.db_path)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

        auth.db_connect = connect  # type: ignore[assignment]
        auth.LOGIN_MAX_ATTEMPTS = 3
        auth.init_auth_db()

    def tearDown(self) -> None:
        auth.db_connect = self.original_connect  # type: ignore[assignment]
        auth.LOGIN_MAX_ATTEMPTS = self.original_max
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
                (user_id, "session-user", auth.hash_password("secret"), auth.ROLE_ADMIN, auth._now()),
            )

        token = auth.create_session(user_id)
        with auth.db_connect() as conn:
            stored = conn.execute("SELECT token FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0]

        self.assertNotEqual(stored, token)
        self.assertEqual(stored, auth._session_token_digest(token))
        self.assertEqual(auth.user_for_token(token)["username"], "session-user")

        auth.destroy_session(token)
        with auth.db_connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(1) FROM sessions WHERE user_id=?", (user_id,)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
