from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from werkzeug.middleware.proxy_fix import ProxyFix

import app as app_module


class SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        app_module.app.config.update(TESTING=True)

    def test_forged_leftmost_forwarded_ip_does_not_change_rate_limit_key(self) -> None:
        observed: list[str] = []

        def deny_login(_username: str, client_ip: str) -> bool:
            observed.append(client_ip)
            return False

        original_wsgi_app = app_module.app.wsgi_app
        app_module.app.wsgi_app = ProxyFix(original_wsgi_app, x_for=1)
        try:
            with mock.patch.object(
                app_module.auth_mod, "login_allowed", side_effect=deny_login
            ):
                client = app_module.app.test_client()
                for forged in ("198.51.100.10", "203.0.113.99"):
                    response = client.post(
                        "/api/v1/auth/login",
                        json={"username": "user", "password": "invalid"},
                        headers={"X-Forwarded-For": f"{forged}, 192.0.2.25"},
                        environ_base={"REMOTE_ADDR": "10.0.0.8"},
                    )
                    self.assertEqual(response.status_code, 429)
        finally:
            app_module.app.wsgi_app = original_wsgi_app

        self.assertEqual(observed, ["192.0.2.25", "192.0.2.25"])

    def test_admin_and_collaborator_write_permissions(self) -> None:
        users = {
            "admin-token": {
                "id": "1",
                "username": "admin",
                "role": app_module.ROLE_ADMIN,
            },
            "collab-token": {
                "id": "2",
                "username": "collab",
                "role": app_module.auth_mod.ROLE_COLLAB,
            },
        }
        client = app_module.app.test_client()
        with (
            mock.patch.object(app_module.auth_mod, "AUTH_DISABLED", False),
            mock.patch.object(
                app_module.auth_mod, "user_for_token", side_effect=users.get
            ),
            mock.patch.object(app_module.auth_mod, "destroy_session"),
        ):
            collab_allowed = client.post(
                "/api/v1/auth/logout", headers={"Authorization": "Bearer collab-token"}
            )
            collab_denied = client.post(
                "/api/v1/import/scan-folder",
                headers={"Authorization": "Bearer collab-token"},
            )
            admin_allowed_route = client.post(
                "/api/v1/auth/logout", headers={"Authorization": "Bearer admin-token"}
            )
            admin_restricted_route = client.post(
                "/api/v1/import/scan-folder",
                headers={"Authorization": "Bearer admin-token"},
            )

        self.assertEqual(collab_allowed.status_code, 200)
        self.assertEqual(collab_denied.status_code, 403)
        self.assertEqual(admin_allowed_route.status_code, 200)
        self.assertNotEqual(admin_restricted_route.status_code, 403)

    def test_escape_like_matches_percent_and_underscore_literally(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE samples(value TEXT)")
        conn.executemany(
            "INSERT INTO samples(value) VALUES (?)",
            [("taxa 100%",), ("taxa 1000",), ("codigo_a",), ("codigoXa",)],
        )

        def search(term: str) -> list[str]:
            pattern = f"%{app_module.escape_like(term)}%"
            rows = conn.execute(
                "SELECT value FROM samples WHERE value LIKE ? ESCAPE '\\' ORDER BY value",
                (pattern,),
            ).fetchall()
            return [row[0] for row in rows]

        self.assertEqual(search("100%"), ["taxa 100%"])
        self.assertEqual(search("_"), ["codigo_a"])

    def test_request_log_contains_method_path_status_duration_and_user(self) -> None:
        client = app_module.app.test_client()
        with (
            mock.patch.object(app_module.auth_mod, "AUTH_DISABLED", True),
            self.assertLogs(app_module.logger, level="INFO") as captured,
        ):
            response = client.get("/api/v1/auth/me")

        self.assertEqual(response.status_code, 200)
        message = "\n".join(captured.output)
        for expected in ("GET", "/api/v1/auth/me", "200", "local"):
            self.assertIn(expected, message)


if __name__ == "__main__":
    unittest.main()
