from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from flask import Blueprint, jsonify, request

from auth import record_audit
from ._shared import allow_collab_write

bp = Blueprint("reconciliations", __name__)
logger = logging.getLogger(__name__)


def _application():
    from core import application

    return application


def db_connect(*args, **kwargs):
    return _application().db_connect(*args, **kwargs)


def current_user():
    return _application().current_user()


def escape_like(value):
    return _application().escape_like(value)


def _reconciliation_tx_payload(row: Any, offset: int) -> dict[str, Any]:
    return {
        "id": row[offset],
        "date": row[offset + 1],
        "description": row[offset + 2],
        "amount": float(row[offset + 3] or 0),
        "type": row[offset + 4],
        "account_id": row[offset + 5],
        "account_name": row[offset + 6] or "",
        "status": row[offset + 7],
    }


def _candidate_pagination() -> tuple[int, int]:
    try:
        page = int(request.args.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.args.get("page_size") or 100)
    except (TypeError, ValueError):
        page_size = 100
    return max(1, page), min(100, max(1, page_size))


@bp.route("/api/v1/reconciliations")
def reconciliations():
    view = (request.args.get("view") or "candidates").strip().lower()
    search = (request.args.get("search") or "").strip().lower()
    with db_connect() as conn:
        if view == "completed":
            params: list[Any] = []
            search_sql = ""
            if search:
                search_sql = "AND (LOWER(e.description) LIKE ? ESCAPE '\\' OR LOWER(i.description) LIKE ? ESCAPE '\\' OR LOWER(ea.name) LIKE ? ESCAPE '\\' OR LOWER(ia.name) LIKE ? ESCAPE '\\')"
                term = f"%{escape_like(search)}%"
                params.extend([term, term, term, term])
            rows = conn.execute(
                f"""
                SELECT r.id,r.amount,r.created_by,r.created_at,
                       e.id,e.date,e.description,e.amount,e.type,e.account_id,ea.name,e.status,
                       i.id,i.date,i.description,i.amount,i.type,i.account_id,ia.name,i.status
                FROM transaction_reconciliations r
                JOIN transactions e ON e.id=r.expense_transaction_id
                JOIN accounts ea ON ea.id=e.account_id
                JOIN transactions i ON i.id=r.income_transaction_id
                JOIN accounts ia ON ia.id=i.account_id
                WHERE 1=1 {search_sql}
                ORDER BY r.created_at DESC
                LIMIT 200
                """,
                params,
            ).fetchall()
            return jsonify(
                {
                    "items": [
                        {
                            "id": row[0],
                            "amount": float(row[1] or 0),
                            "created_by": row[2] or "",
                            "created_at": row[3],
                            "expense": _reconciliation_tx_payload(row, 4),
                            "income": _reconciliation_tx_payload(row, 12),
                        }
                        for row in rows
                    ]
                }
            )

        page, page_size = _candidate_pagination()
        params = []
        search_sql = ""
        if search:
            search_sql = "AND (LOWER(e.description) LIKE ? ESCAPE '\\' OR LOWER(i.description) LIKE ? ESCAPE '\\' OR LOWER(ea.name) LIKE ? ESCAPE '\\' OR LOWER(ia.name) LIKE ? ESCAPE '\\')"
            term = f"%{escape_like(search)}%"
            params.extend([term, term, term, term])
        rows = conn.execute(
            f"""
            SELECT e.id,e.date,e.description,e.amount,e.type,e.account_id,ea.name,e.status,
                   i.id,i.date,i.description,i.amount,i.type,i.account_id,ia.name,i.status
            FROM transactions e
            JOIN accounts ea ON ea.id=e.account_id
            JOIN transactions i
              ON i.type='income' AND ABS(ABS(e.amount)-ABS(i.amount))<0.005
            JOIN accounts ia ON ia.id=i.account_id
            WHERE e.type='expense'
              AND e.status NOT IN ('duplicate','ignored')
              AND i.status NOT IN ('duplicate','ignored')
              AND NOT EXISTS (
                SELECT 1 FROM transaction_reconciliations r
                WHERE r.expense_transaction_id=e.id OR r.income_transaction_id=e.id
                   OR r.expense_transaction_id=i.id OR r.income_transaction_id=i.id
              )
              {search_sql}
            """,
            params,
        ).fetchall()
    candidates = []
    for row in rows:
        expense = _reconciliation_tx_payload(row, 0)
        income = _reconciliation_tx_payload(row, 8)
        try:
            date_difference = abs(
                (
                    dt.date.fromisoformat(expense["date"][:10])
                    - dt.date.fromisoformat(income["date"][:10])
                ).days
            )
        except (TypeError, ValueError):
            date_difference = 999999
        candidates.append(
            {
                "expense": expense,
                "income": income,
                "amount": abs(expense["amount"]),
                "date_difference_days": date_difference,
            }
        )
    candidates.sort(
        key=lambda item: (
            item["date_difference_days"],
            -item["amount"],
            item["expense"]["date"],
            item["income"]["date"],
            item["expense"]["id"],
            item["income"]["id"],
        )
    )
    total = len(candidates)
    start = (page - 1) * page_size
    return jsonify(
        {
            "items": candidates[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": start + page_size < total,
        }
    )


@bp.route("/api/v1/reconciliations", methods=["POST"])
@allow_collab_write
def create_reconciliation():
    data = request.get_json(force=True) or {}
    expense_id = (data.get("expense_transaction_id") or "").strip()
    income_id = (data.get("income_transaction_id") or "").strip()
    if not expense_id or not income_id or expense_id == income_id:
        return jsonify(
            {"detail": "Escolha uma entrada e uma saida", "code": "VALIDATION_ERROR"}
        ), 400
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT id,amount,type,status FROM transactions WHERE id IN (?,?)",
            (expense_id, income_id),
        ).fetchall()
        by_id = {row[0]: row for row in rows}
        expense = by_id.get(expense_id)
        income = by_id.get(income_id)
        if not expense or not income:
            return jsonify(
                {"detail": "Lancamento nao encontrado", "code": "NOT_FOUND"}
            ), 404
        if expense[2] != "expense" or income[2] != "income":
            return jsonify(
                {
                    "detail": "O par deve conter uma saida e uma entrada",
                    "code": "TYPE_MISMATCH",
                }
            ), 400
        if expense[3] in ("duplicate", "ignored") or income[3] in (
            "duplicate",
            "ignored",
        ):
            return jsonify(
                {
                    "detail": "Duplicados ou ignorados nao podem ser conciliados",
                    "code": "INVALID_STATUS",
                }
            ), 409
        expense_cents = int(round(abs(float(expense[1])) * 100))
        income_cents = int(round(abs(float(income[1])) * 100))
        if expense_cents != income_cents:
            return jsonify(
                {
                    "detail": "Entrada e saida precisam ter o mesmo valor",
                    "code": "AMOUNT_MISMATCH",
                }
            ), 400
        existing = conn.execute(
            """
            SELECT id FROM transaction_reconciliations
            WHERE expense_transaction_id IN (?,?) OR income_transaction_id IN (?,?)
            """,
            (expense_id, income_id, expense_id, income_id),
        ).fetchone()
        if existing:
            return jsonify(
                {
                    "detail": "Um dos lancamentos ja esta conciliado",
                    "code": "ALREADY_RECONCILED",
                }
            ), 409
        reconciliation_id = str(uuid.uuid4())
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        user = current_user()
        try:
            conn.execute(
                """
                INSERT INTO transaction_reconciliations(
                  id,expense_transaction_id,income_transaction_id,amount,created_by,created_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    reconciliation_id,
                    expense_id,
                    income_id,
                    expense_cents / 100,
                    user.get("username") or "",
                    now,
                ),
            )
        except Exception:
            logger.warning(
                "Conflito ao criar conciliacao entre %s e %s",
                expense_id,
                income_id,
                exc_info=True,
            )
            conn.rollback()
            return jsonify(
                {
                    "detail": "Um dos lancamentos acabou de ser conciliado",
                    "code": "ALREADY_RECONCILED",
                }
            ), 409
        record_audit(
            user,
            "create_reconciliation",
            "reconciliation",
            reconciliation_id,
            detail=f"expense={expense_id}; income={income_id}; amount={expense_cents / 100:.2f}",
            conn=conn,
        )
    return jsonify(
        {
            "id": reconciliation_id,
            "expense_transaction_id": expense_id,
            "income_transaction_id": income_id,
            "amount": expense_cents / 100,
            "created_at": now,
        }
    ), 201


@bp.route(
    "/api/v1/reconciliations/<reconciliation_id>/undo", methods=["POST"]
)
@allow_collab_write
def undo_reconciliation(reconciliation_id: str):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT expense_transaction_id,income_transaction_id,amount FROM transaction_reconciliations WHERE id=?",
            (reconciliation_id,),
        ).fetchone()
        if not row:
            return jsonify(
                {"detail": "Conciliacao nao encontrada", "code": "NOT_FOUND"}
            ), 404
        conn.execute(
            "DELETE FROM transaction_reconciliations WHERE id=?", (reconciliation_id,)
        )
        record_audit(
            current_user(),
            "undo_reconciliation",
            "reconciliation",
            reconciliation_id,
            detail=f"expense={row[0]}; income={row[1]}; amount={float(row[2] or 0):.2f}",
            conn=conn,
        )
    return jsonify({"id": reconciliation_id, "ok": True})
