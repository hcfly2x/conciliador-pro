"""Autenticacao simples com dois perfis (admin / colaborador) e trilha de auditoria.

Tabelas: users, sessions, audit_log (criadas em init_auth_db).

- Senhas: PBKDF2-SHA256 com salt aleatorio (stdlib, sem dependencia extra).
- Sessoes: token aleatorio (Bearer), hash SHA-256 persistido e expiracao
  deslizante de 30 dias.
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
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS") or "5")
LOGIN_BLOCK_MINUTES = int(os.environ.get("LOGIN_BLOCK_MINUTES") or "15")

ROLE_ADMIN = "admin"
ROLE_COLLAB = "colaborador"
VALID_ROLES = {ROLE_ADMIN, ROLE_COLLAB}

_PBKDF2_ITERATIONS = 260_000


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _session_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_attempts(
              attempt_key TEXT PRIMARY KEY,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              blocked_until TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def _login_attempt_key(username: str, client_ip: str) -> str:
    raw = f"{(username or '').strip().lower()}|{(client_ip or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def login_allowed(username: str, client_ip: str) -> bool:
    key = _login_attempt_key(username, client_ip)
    with db_connect() as conn:
        row = conn.execute(
            "SELECT blocked_until FROM login_attempts WHERE attempt_key=?", (key,)
        ).fetchone()
    return not row or not row[0] or str(row[0]) <= _now()


def record_login_failure(username: str, client_ip: str) -> None:
    key = _login_attempt_key(username, client_ip)
    now = dt.datetime.now(dt.timezone.utc)
    with db_connect() as conn:
        row = conn.execute(
            "SELECT attempt_count,blocked_until FROM login_attempts WHERE attempt_key=?", (key,)
        ).fetchone()
        count = int((row or (0, ""))[0] or 0) + 1
        blocked_until = (row or (0, ""))[1] or ""
        if count >= LOGIN_MAX_ATTEMPTS:
            blocked_until = (now + dt.timedelta(minutes=LOGIN_BLOCK_MINUTES)).isoformat(timespec="seconds")
            count = 0
        conn.execute(
            """
            INSERT INTO login_attempts(attempt_key,attempt_count,blocked_until,updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(attempt_key) DO UPDATE SET
              attempt_count=excluded.attempt_count,
              blocked_until=excluded.blocked_until,
              updated_at=excluded.updated_at
            """,
            (key, count, blocked_until, now.isoformat(timespec="seconds")),
        )


def clear_login_failures(username: str, client_ip: str) -> None:
    key = _login_attempt_key(username, client_ip)
    with db_connect() as conn:
        conn.execute("DELETE FROM login_attempts WHERE attempt_key=?", (key,))


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
            (_session_token_digest(token), user_id, now.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")),
        )
    return token


def destroy_session(token: str) -> None:
    invalidate_token_cache(token)
    with db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token=? OR token=?", (token, _session_token_digest(token)))


_TOKEN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TOKEN_CACHE_TTL = 10.0  # reduz janela de revogacao entre multiplos workers
_TOKEN_CACHE_MAX = 500


def _cache_get(token: str) -> dict[str, Any] | None:
    item = _TOKEN_CACHE.get(token)
    if not item:
        return None
    ts, user = item
    import time
    if time.monotonic() - ts > _TOKEN_CACHE_TTL:
        _TOKEN_CACHE.pop(token, None)
        return None
    return user


def _cache_put(token: str, user: dict[str, Any]) -> None:
    import time
    if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[token] = (time.monotonic(), user)


def invalidate_token_cache(token: str | None = None) -> None:
    if token is None:
        _TOKEN_CACHE.clear()
    else:
        _TOKEN_CACHE.pop(token, None)


def user_for_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    cached = _cache_get(token)
    if cached is not None:
        return cached
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token=? OR s.token=?
            """,
            (_session_token_digest(token), token),
        ).fetchone()
        if not row:
            return None
        if int(row[3]) != 1:
            return None
        if str(row[4]) < _now():
            conn.execute("DELETE FROM sessions WHERE token=? OR token=?", (_session_token_digest(token), token))
            return None
        expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=SESSION_DAYS)
        conn.execute(
            "UPDATE sessions SET token=?, expires_at=? WHERE token=? OR token=?",
            (_session_token_digest(token), expires.isoformat(timespec="seconds"), _session_token_digest(token), token),
        )
    user = {"id": row[0], "username": row[1], "role": row[2]}
    _cache_put(token, user)
    return user


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
