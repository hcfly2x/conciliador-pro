from __future__ import annotations

import datetime as dt
import sqlite3
import uuid

from flask import Blueprint, jsonify, request

from auth import record_audit

bp = Blueprint("accounts", __name__)


def _application():
    from core import application

    return application


def db_connect(*args, **kwargs):
    return _application().db_connect(*args, **kwargs)


def current_user():
    return _application().current_user()


def is_unknown_historical_account_label(value):
    return _application().is_unknown_historical_account_label(value)


@bp.route("/api/v1/accounts", methods=["GET", "POST"])
def accounts():
    if request.method == "GET":
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT id,name,type,color,is_active,created_at FROM accounts ORDER BY name"
            ).fetchall()
        rows = [row for row in rows if not is_unknown_historical_account_label(row[1])]
        return jsonify(
            [
                {
                    "id": r[0],
                    "name": r[1],
                    "type": r[2],
                    "color": r[3],
                    "is_active": bool(r[4]),
                    "created_at": r[5],
                }
                for r in rows
            ]
        )
    data = request.get_json(force=True)
    now = dt.datetime.now().isoformat(timespec="seconds")
    name = data.get("name", "").strip()
    account_type = data.get("type", "checking")
    if not name or account_type not in ("checking", "credit_card", "savings"):
        return jsonify(
            {
                "detail": "Nome e tipo de conta validos sao obrigatorios",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    item = (str(uuid.uuid4()), name, account_type, data.get("color", "#2563eb"), 1, now)
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES (?,?,?,?,?,?)",
            item,
        )
    return jsonify(
        {
            "id": item[0],
            "name": item[1],
            "type": item[2],
            "color": item[3],
            "is_active": True,
            "created_at": now,
        }
    ), 201


@bp.route(
    "/api/v1/accounts/<account_id>", methods=["PUT", "DELETE", "OPTIONS"]
)
def account_detail(account_id: str):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    with db_connect() as conn:
        if request.method == "DELETE":
            references = {
                "lancamentos": conn.execute(
                    "SELECT COUNT(1) FROM transactions WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
                "historico": conn.execute(
                    "SELECT COUNT(1) FROM classification_history WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
                "parcelamentos": conn.execute(
                    "SELECT COUNT(1) FROM installment_plans WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
                "arquivos importados": conn.execute(
                    "SELECT COUNT(1) FROM imported_files WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
                "previews": conn.execute(
                    "SELECT COUNT(1) FROM import_previews WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
                "coberturas": conn.execute(
                    "SELECT COUNT(1) FROM account_file_coverage WHERE account_id=?",
                    (account_id,),
                ).fetchone()[0],
            }
            used = {
                name: int(total or 0)
                for name, total in references.items()
                if int(total or 0) > 0
            }
            if used:
                detail = ", ".join(f"{name}: {total}" for name, total in used.items())
                return jsonify(
                    {
                        "detail": f"Conta ainda possui referencias ({detail}). Remova ou migre os dados primeiro.",
                        "code": "ACCOUNT_IN_USE",
                        "references": used,
                    }
                ), 400
            conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            return jsonify({"ok": True})
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        account_type = data.get("type", "checking")
        if not name or account_type not in ("checking", "credit_card", "savings"):
            return jsonify(
                {
                    "detail": "Nome e tipo de conta validos sao obrigatorios",
                    "code": "VALIDATION_ERROR",
                }
            ), 400
        conn.execute(
            "UPDATE accounts SET name=?, type=?, color=?, is_active=? WHERE id=?",
            (
                name,
                account_type,
                data.get("color", "#2563eb"),
                int(bool(data.get("is_active", True))),
                account_id,
            ),
        )
        row = conn.execute(
            "SELECT id,name,type,color,is_active,created_at FROM accounts WHERE id=?",
            (account_id,),
        ).fetchone()
    if not row:
        return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
    return jsonify(
        {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "color": row[3],
            "is_active": bool(row[4]),
            "created_at": row[5],
        }
    )


@bp.route("/api/v1/ledgers", methods=["GET", "POST"])
def ledgers():
    if request.method == "GET":
        with db_connect() as conn:
            rows = conn.execute(
                """
                SELECT l.id,l.name,l.description,l.color,l.is_active,l.created_at,
                       COUNT(t.id),
                       SUM(CASE WHEN t.status='pending' THEN 1 ELSE 0 END),
                       IFNULL(SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END),0),
                       IFNULL(SUM(CASE WHEN t.type='expense' THEN t.amount ELSE 0 END),0)
                FROM ledgers l
                LEFT JOIN transactions t ON t.ledger_id=l.id AND t.status NOT IN ('duplicate','ignored')
                  AND NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                                  WHERE r.expense_transaction_id=t.id OR r.income_transaction_id=t.id)
                WHERE l.is_active=1
                GROUP BY l.id
                ORDER BY l.name
                """
            ).fetchall()
        return jsonify(
            [
                {
                    "id": r[0],
                    "name": r[1],
                    "description": r[2] or "",
                    "color": r[3],
                    "is_active": bool(r[4]),
                    "created_at": r[5],
                    "transaction_count": int(r[6] or 0),
                    "pending_count": int(r[7] or 0),
                    "total_income": float(r[8] or 0),
                    "total_expense": float(r[9] or 0),
                    "balance": float(r[8] or 0) + float(r[9] or 0),
                }
                for r in rows
            ]
        )
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip().upper()
    if not name:
        return jsonify({"detail": "Nome obrigatorio", "code": "VALIDATION_ERROR"}), 400
    now = dt.datetime.now().isoformat(timespec="seconds")
    item = (
        str(uuid.uuid4()),
        name,
        (data.get("description") or "").strip(),
        data.get("color") or "#c9a84c",
        1,
        now,
    )
    with db_connect() as conn:
        try:
            conn.execute(
                "INSERT INTO ledgers(id,name,description,color,is_active,created_at) VALUES (?,?,?,?,?,?)",
                item,
            )
        except sqlite3.IntegrityError:
            return jsonify(
                {"detail": "Razao ja existe", "code": "DUPLICATE_LEDGER"}
            ), 409
    return jsonify(
        {
            "id": item[0],
            "name": item[1],
            "description": item[2],
            "color": item[3],
            "is_active": True,
            "created_at": now,
            "transaction_count": 0,
            "pending_count": 0,
            "total_income": 0,
            "total_expense": 0,
            "balance": 0,
        }
    ), 201


@bp.route(
    "/api/v1/ledgers/<ledger_id>", methods=["PATCH", "DELETE", "OPTIONS"]
)
def ledger_detail(ledger_id: str):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id FROM ledgers WHERE id=?", (ledger_id,)
        ).fetchone()
        if not exists:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        if request.method == "DELETE":
            moved = (
                conn.execute(
                    "UPDATE transactions SET ledger_id=NULL WHERE ledger_id=?",
                    (ledger_id,),
                ).rowcount
                or 0
            )
            conn.execute(
                "UPDATE classification_history SET ledger_id=NULL WHERE ledger_id=?",
                (ledger_id,),
            )
            conn.execute("UPDATE ledgers SET is_active=0 WHERE id=?", (ledger_id,))
            return jsonify({"ok": True, "moved_back": moved})
        data = request.get_json(force=True) or {}
        conn.execute(
            """
            UPDATE ledgers
            SET name=?, description=?, color=?, is_active=?
            WHERE id=?
            """,
            (
                (data.get("name") or "").strip().upper(),
                (data.get("description") or "").strip(),
                data.get("color") or "#c9a84c",
                int(bool(data.get("is_active", True))),
                ledger_id,
            ),
        )
        row = conn.execute(
            "SELECT id,name,description,color,is_active,created_at FROM ledgers WHERE id=?",
            (ledger_id,),
        ).fetchone()
    return jsonify(
        {
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "color": row[3],
            "is_active": bool(row[4]),
            "created_at": row[5],
        }
    )


@bp.route("/api/v1/ledgers/<ledger_id>/include", methods=["POST"])
def ledger_include(ledger_id: str):
    data = request.get_json(force=True) or {}
    tx_ids = [str(item) for item in (data.get("tx_ids") or []) if str(item).strip()]
    if not tx_ids:
        return jsonify({"updated": 0})
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id FROM ledgers WHERE id=? AND is_active=1", (ledger_id,)
        ).fetchone()
        if not exists:
            return jsonify({"detail": "Razao nao encontrada", "code": "NOT_FOUND"}), 404
        placeholders = ",".join("?" for _ in tx_ids)
        cur = conn.execute(
            f"UPDATE transactions SET ledger_id=? WHERE id IN ({placeholders}) AND status NOT IN ('duplicate','ignored')",
            [ledger_id] + tx_ids,
        )
    return jsonify({"updated": cur.rowcount or 0})


@bp.route("/api/v1/ledgers/<ledger_id>/exclude", methods=["POST"])
def ledger_exclude(ledger_id: str):
    data = request.get_json(force=True) or {}
    tx_ids = [str(item) for item in (data.get("tx_ids") or []) if str(item).strip()]
    if not tx_ids:
        return jsonify({"updated": 0})
    with db_connect() as conn:
        placeholders = ",".join("?" for _ in tx_ids)
        cur = conn.execute(
            f"UPDATE transactions SET ledger_id=NULL WHERE ledger_id=? AND id IN ({placeholders})",
            [ledger_id] + tx_ids,
        )
    return jsonify({"updated": cur.rowcount or 0})


@bp.route("/api/v1/categories", methods=["GET", "POST"])
def categories():
    if request.method == "GET":
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT id,name,color,text_color,type FROM categories ORDER BY name"
            ).fetchall()
        return jsonify(
            [
                {
                    "id": r[0],
                    "name": r[1],
                    "color": r[2],
                    "text_color": r[3],
                    "type": "hybrid",
                }
                for r in rows
            ]
        )
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify(
            {
                "detail": "Nome de categoria obrigatorio",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    item = (
        str(uuid.uuid4()),
        name,
        data.get("color", "#334155"),
        data.get("text_color", "#ffffff"),
        "hybrid",
    )
    with db_connect() as conn:
        duplicate = conn.execute(
            "SELECT id FROM categories WHERE UPPER(name)=UPPER(?)",
            (name,),
        ).fetchone()
        if duplicate:
            return jsonify(
                {"detail": "Categoria ja existe", "code": "DUPLICATE_CATEGORY"}
            ), 409
        conn.execute(
            "INSERT INTO categories(id,name,color,text_color,type) VALUES (?,?,?,?,?)",
            item,
        )
    return jsonify(
        {
            "id": item[0],
            "name": item[1],
            "color": item[2],
            "text_color": item[3],
            "type": "hybrid",
        }
    ), 201


@bp.route("/api/v1/categories/<cat_id>", methods=["PUT", "DELETE", "OPTIONS"])
def category_detail(cat_id: str):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    with db_connect() as conn:
        if request.method == "DELETE":
            references = {
                "lancamentos": conn.execute(
                    "SELECT COUNT(1) FROM transactions WHERE category_id=?", (cat_id,)
                ).fetchone()[0],
                "historico": conn.execute(
                    "SELECT COUNT(1) FROM classification_history WHERE category_id=?",
                    (cat_id,),
                ).fetchone()[0],
                "parcelamentos": conn.execute(
                    "SELECT COUNT(1) FROM installment_plans WHERE category_id=?",
                    (cat_id,),
                ).fetchone()[0],
            }
            used = {
                name: int(total or 0)
                for name, total in references.items()
                if int(total or 0) > 0
            }
            if used:
                detail = ", ".join(f"{name}: {total}" for name, total in used.items())
                return jsonify(
                    {
                        "detail": f"Categoria ainda possui referencias ({detail}). Reclassifique os dados primeiro.",
                        "code": "CATEGORY_IN_USE",
                        "references": used,
                    }
                ), 400
            conn.execute(
                "UPDATE transactions SET suggested_category_id=NULL,suggested_subcategory_id=NULL WHERE suggested_category_id=?",
                (cat_id,),
            )
            conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
            return jsonify({"ok": True})
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify(
                {
                    "detail": "Nome da categoria e obrigatorio",
                    "code": "VALIDATION_ERROR",
                }
            ), 400
        conn.execute(
            "UPDATE categories SET name=?, color=?, text_color=?, type=? WHERE id=?",
            (
                name,
                data.get("color", "#334155"),
                data.get("text_color", "#ffffff"),
                "hybrid",
                cat_id,
            ),
        )
        row = conn.execute(
            "SELECT id,name,color,text_color,type FROM categories WHERE id=?", (cat_id,)
        ).fetchone()
    if not row:
        return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
    return jsonify(
        {
            "id": row[0],
            "name": row[1],
            "color": row[2],
            "text_color": row[3],
            "type": "hybrid",
        }
    )


@bp.route("/api/v1/subcategories", methods=["GET", "POST"])
def subcategories():
    if request.method == "GET":
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT id,name FROM subcategories ORDER BY name"
            ).fetchall()
        return jsonify([{"id": r[0], "name": r[1]} for r in rows])
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"detail": "Nome obrigatorio", "code": "VALIDATION_ERROR"}), 400
    with db_connect() as conn:
        ex = conn.execute(
            "SELECT id,name FROM subcategories WHERE name=?", (name,)
        ).fetchone()
        if ex:
            return jsonify({"id": ex[0], "name": ex[1]}), 201
        sid = str(uuid.uuid4())
        conn.execute("INSERT INTO subcategories(id,name) VALUES (?,?)", (sid, name))
    return jsonify({"id": sid, "name": name}), 201


@bp.route("/api/v1/subcategories/<sub_id>", methods=["DELETE", "OPTIONS"])
def subcategory_delete(sub_id: str):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    with db_connect() as conn:
        row = conn.execute(
            "SELECT id, name FROM subcategories WHERE id=?", (sub_id,)
        ).fetchone()
        if not row:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        references = {
            "lancamentos": conn.execute(
                "SELECT COUNT(1) FROM transactions WHERE subcategory_id=?", (sub_id,)
            ).fetchone()[0],
            "historico": conn.execute(
                "SELECT COUNT(1) FROM classification_history WHERE subcategory_id=?",
                (sub_id,),
            ).fetchone()[0],
            "parcelamentos": conn.execute(
                "SELECT COUNT(1) FROM installment_plans WHERE subcategory_id=?",
                (sub_id,),
            ).fetchone()[0],
        }
        used = {
            name: int(total or 0)
            for name, total in references.items()
            if int(total or 0) > 0
        }
        if used:
            detail = ", ".join(f"{name}: {total}" for name, total in used.items())
            return jsonify(
                {
                    "detail": f"Subcategoria ainda possui referencias ({detail}). Reclassifique os dados primeiro.",
                    "code": "SUBCATEGORY_IN_USE",
                    "references": used,
                }
            ), 400
        conn.execute(
            "UPDATE transactions SET suggested_subcategory_id=NULL WHERE suggested_subcategory_id=?",
            (sub_id,),
        )
        conn.execute("DELETE FROM subcategories WHERE id=?", (sub_id,))
        record_audit(
            current_user(),
            "delete_subcategory",
            "subcategory",
            sub_id,
            "name",
            row[1],
            "",
            conn=conn,
        )
    return jsonify({"ok": True})
