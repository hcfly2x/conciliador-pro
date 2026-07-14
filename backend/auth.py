"""Autenticacao simples com dois perfis (admin / colaborador) e trilha de auditoria.

Tabelas: users, sessions, audit_log (criadas em init_auth_db).

- Senhas: PBKDF2-SHA256 com salt aleatorio (stdlib, sem dependencia extra).
- Sessoes: token aleatorio (Bearer) com expiracao deslizante de 30 dias.
- Bootstrap: se nao existir nenhum usuario, cria o admin a partir das variaveis
  de ambiente ADMIN_USERNAME / ADMIN_PASSWORD (obrigatorias em producao).
- Dev local: exportar AUTH_DISABLED=1 para pular autenticacao.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import uuid
from typing import Any

from db import db_connect

AUTH_DISABLED = (os.environ.get("AUTH_DISABLED") or "").strip() in {"1", "true", "yes"}
SESSION_DAYS = int(os.environ.get("SESSION_DAYS") or "30")

ROLE_ADMIN = "admin"
ROLE_COLLAB = "colaborador"
VALID_ROLES = {ROLE_ADMIN, ROLE_COLLAB}

_PBKDF2_ITERATIONS = 260_000


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _scheme, iterations, salt, expected = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return secrets.compare_digest(digest.hex(), expected)
    except Exception:
        return False


def init_auth_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users(
              id TEXT PRIMARY KEY,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'colaborador',
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions(
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log(
              id TEXT PRIMARY KEY,
              user_id TEXT,
              username TEXT NOT NULL DEFAULT '',
              action TEXT NOT NULL,
              entity TEXT NOT NULL,
              entity_id TEXT NOT NULL DEFAULT '',
              field TEXT NOT NULL DEFAULT '',
              old_value TEXT NOT NULL DEFAULT '',
              new_value TEXT NOT NULL DEFAULT '',
              detail TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def bootstrap_admin() -> None:
    """Cria o primeiro admin a partir de ADMIN_USERNAME/ADMIN_PASSWORD se nao houver usuarios."""
    username = (os.environ.get("ADMIN_USERNAME") or "").strip()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    with db_connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if int(count) > 0:
            return
        if not username or not password:
            if AUTH_DISABLED:
                return
            print("[auth] AVISO: nenhum usuario existe e ADMIN_USERNAME/ADMIN_PASSWORD nao foram definidos. Login sera impossivel.")
            return
        conn.execute(
            "INSERT INTO users(id, username, password_hash, role, is_active, created_at) VALUES (?,?,?,?,1,?)",
            (str(uuid.uuid4()), username, hash_password(password), ROLE_ADMIN, _now()),
        )
        print(f"[auth] Usuario admin '{username}' criado via variaveis de ambiente.")


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(days=SESSION_DAYS)
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
        )
    return token


def destroy_session(token: str) -> None:
    with db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def user_for_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token=?
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if int(row[3]) != 1:
            return None
        if str(row[4]) < _now():
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
            return None
    return {"id": row[0], "username": row[1], "role": row[2]}


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, is_active FROM users WHERE lower(username)=lower(?)",
            (username,),
        ).fetchone()
    if not row or int(row[4]) != 1:
        return None
    if not verify_password(password, row[2]):
        return None
    return {"id": row[0], "username": row[1], "role": row[3]}


def record_audit(
    user: dict[str, Any] | None,
    action: str,
    entity: str,
    entity_id: str = "",
    field: str = "",
    old_value: Any = "",
    new_value: Any = "",
    detail: str = "",
    conn=None,
) -> None:
    values = (
        str(uuid.uuid4()),
        (user or {}).get("id"),
        (user or {}).get("username") or "sistema",
        action,
        entity,
        entity_id or "",
        field or "",
        "" if old_value is None else str(old_value),
        "" if new_value is None else str(new_value),
        detail or "",
        _now(),
    )
    sql = (
        "INSERT INTO audit_log(id, user_id, username, action, entity, entity_id, field, old_value, new_value, detail, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)"
    )
    if conn is not None:
        conn.execute(sql, values)
    else:
        with db_connect() as c:
            c.execute(sql, values)
