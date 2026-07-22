from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from flask import Blueprint, jsonify, request

import auth as auth_mod
from auth import ROLE_ADMIN, record_audit
from ._shared import allow_collab_write

bp = Blueprint("auth", __name__)


def _application():
    from core import application

    return application


@bp.route("/api/v1/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(
            {"detail": "username e password obrigatorios", "code": "VALIDATION_ERROR"}
        ), 400
    client_ip = request.remote_addr or ""
    if not auth_mod.login_allowed(username, client_ip):
        return jsonify(
            {
                "detail": "Muitas tentativas. Aguarde antes de tentar novamente.",
                "code": "LOGIN_RATE_LIMITED",
            }
        ), 429
    user = auth_mod.authenticate(username, password)
    if not user:
        auth_mod.record_login_failure(username, client_ip)
        return jsonify(
            {"detail": "Usuario ou senha invalidos", "code": "INVALID_CREDENTIALS"}
        ), 401
    auth_mod.clear_login_failures(username, client_ip)
    token = auth_mod.create_session(user["id"])
    record_audit(user, "login", "auth", user["id"])
    return jsonify({"token": token, "user": user})


@bp.route("/api/v1/auth/logout", methods=["POST"])
@allow_collab_write
def auth_logout():
    token = (request.headers.get("Authorization") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if token:
        auth_mod.destroy_session(token)
    return jsonify({"ok": True})


@bp.route("/api/v1/auth/me")
def auth_me():
    return jsonify(_application().current_user())


@bp.route("/api/v1/auth/users", methods=["GET", "POST"])
def auth_users():
    application = _application()
    forbidden = application.require_admin()
    if forbidden:
        return forbidden
    if request.method == "GET":
        with application.db_connect() as conn:
            rows = conn.execute(
                "SELECT id, username, role, is_active, created_at FROM users ORDER BY created_at"
            ).fetchall()
        return jsonify(
            [
                {
                    "id": row[0],
                    "username": row[1],
                    "role": row[2],
                    "is_active": bool(row[3]),
                    "created_at": row[4],
                }
                for row in rows
            ]
        )
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or auth_mod.ROLE_COLLAB).strip()
    if not username or len(password) < 8:
        return jsonify(
            {
                "detail": "username obrigatorio e senha com pelo menos 8 caracteres",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    if role not in auth_mod.VALID_ROLES:
        return jsonify(
            {"detail": "role deve ser admin ou colaborador", "code": "VALIDATION_ERROR"}
        ), 400
    user_id = str(uuid.uuid4())
    with application.db_connect() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE lower(username)=lower(?)", (username,)
        ).fetchone()
        if exists:
            return jsonify({"detail": "Usuario ja existe", "code": "ALREADY_EXISTS"}), 409
        conn.execute(
            "INSERT INTO users(id, username, password_hash, role, is_active, created_at) VALUES (?,?,?,?,1,?)",
            (
                user_id,
                username,
                auth_mod.hash_password(password),
                role,
                dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        record_audit(
            application.current_user(),
            "create_user",
            "user",
            user_id,
            "username",
            "",
            username,
            f"role={role}",
            conn=conn,
        )
    return jsonify(
        {"id": user_id, "username": username, "role": role, "is_active": True}
    ), 201


@bp.route("/api/v1/auth/users/<user_id>", methods=["PATCH", "OPTIONS"])
def auth_user_update(user_id: str):
    application = _application()
    forbidden = application.require_admin()
    if forbidden:
        return forbidden
    data = request.get_json(force=True) or {}
    with application.db_connect() as conn:
        row = conn.execute(
            "SELECT id, username, role, is_active FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if not row:
            return jsonify({"detail": "Usuario nao encontrado", "code": "NOT_FOUND"}), 404
        if "password" in data:
            password = data.get("password") or ""
            if len(password) < 8:
                return jsonify(
                    {"detail": "Senha com pelo menos 8 caracteres", "code": "VALIDATION_ERROR"}
                ), 400
            conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (auth_mod.hash_password(password), user_id),
            )
            record_audit(application.current_user(), "reset_password", "user", user_id, conn=conn)
        if "role" in data:
            role = (data.get("role") or "").strip()
            if role not in auth_mod.VALID_ROLES:
                return jsonify({"detail": "role invalida", "code": "VALIDATION_ERROR"}), 400
            if row[2] == ROLE_ADMIN and role != ROLE_ADMIN and int(row[3] or 0) == 1:
                active_admins = int(
                    conn.execute(
                        "SELECT COUNT(1) FROM users WHERE role=? AND is_active=1",
                        (ROLE_ADMIN,),
                    ).fetchone()[0]
                    or 0
                )
                if active_admins <= 1:
                    return jsonify(
                        {
                            "detail": "Nao e permitido rebaixar o ultimo administrador ativo",
                            "code": "LAST_ADMIN_REQUIRED",
                        }
                    ), 409
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            record_audit(
                application.current_user(), "change_role", "user", user_id,
                "role", row[2], role, conn=conn,
            )
        if "is_active" in data:
            active = 1 if data.get("is_active") else 0
            if row[2] == ROLE_ADMIN and int(row[3] or 0) == 1 and active == 0:
                active_admins = int(
                    conn.execute(
                        "SELECT COUNT(1) FROM users WHERE role=? AND is_active=1",
                        (ROLE_ADMIN,),
                    ).fetchone()[0]
                    or 0
                )
                if active_admins <= 1:
                    return jsonify(
                        {
                            "detail": "Nao e permitido desativar o ultimo administrador ativo",
                            "code": "LAST_ADMIN_REQUIRED",
                        }
                    ), 409
            conn.execute("UPDATE users SET is_active=? WHERE id=?", (active, user_id))
            if not active:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                auth_mod.invalidate_token_cache()
            record_audit(
                application.current_user(), "set_active", "user", user_id,
                "is_active", row[3], active, conn=conn,
            )
    return jsonify({"ok": True})


@bp.route("/api/v1/audit")
def audit_list():
    application = _application()
    entity_id = (request.args.get("entity_id") or "").strip()
    entity = (request.args.get("entity") or "").strip()
    limit = min(500, max(1, int(request.args.get("limit", 100))))
    where = ["1=1"]
    params: list[Any] = []
    if entity_id:
        where.append("entity_id=?")
        params.append(entity_id)
    if entity:
        where.append("entity=?")
        params.append(entity)
    with application.db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, username, action, entity, entity_id, field, old_value, new_value, detail, created_at
            FROM audit_log WHERE {" AND ".join(where)}
            ORDER BY created_at DESC LIMIT ?
            """,
            params + [limit],
        ).fetchall()
    return jsonify(
        [
            {
                "id": row[0], "username": row[1], "action": row[2],
                "entity": row[3], "entity_id": row[4], "field": row[5],
                "old_value": row[6], "new_value": row[7], "detail": row[8],
                "created_at": row[9],
            }
            for row in rows
        ]
    )
