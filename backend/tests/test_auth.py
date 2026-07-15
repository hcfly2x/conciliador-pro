from __future__ import annotations

import sqlite3
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
