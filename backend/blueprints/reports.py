from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

bp = Blueprint("reports", __name__)


def _db_connect():
    # Import tardio evita ciclo durante a criacao do app e preserva os pontos de
    # injecao usados por testes e ferramentas legadas (`import app`).
    from core import application

    return application.db_connect()


@bp.route("/api/v1/reports/summary")
def report_summary():
    competence_month = (request.args.get("competence_month") or "").strip()
    if competence_month:
        where = """WHERE competence_month=? AND status NOT IN ('duplicate','ignored')
                   AND NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                                   WHERE r.expense_transaction_id=transactions.id OR r.income_transaction_id=transactions.id)"""
        params: list[Any] = [competence_month]
    else:
        where = """WHERE status NOT IN ('duplicate','ignored')
                   AND NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                                   WHERE r.expense_transaction_id=transactions.id OR r.income_transaction_id=transactions.id)"""
        params = []
    with _db_connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(1),
                   SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status='reconciled' THEN 1 ELSE 0 END),
                   IFNULL(SUM(CASE WHEN type='income' THEN amount ELSE 0 END),0),
                   IFNULL(SUM(CASE WHEN type='expense' THEN amount ELSE 0 END),0)
            FROM transactions
            {where}
            """,
            params,
        ).fetchone()
    income = float(row[3] or 0)
    expense = float(row[4] or 0)
    return jsonify(
        {
            "total_transactions": int(row[0] or 0),
            "pending": int(row[1] or 0),
            "reconciled": int(row[2] or 0),
            "total_income": income,
            "total_expense": expense,
            "balance": income + expense,
        }
    )


@bp.route("/api/v1/reports/by-category")
def report_by_category():
    tx_type = (request.args.get("type") or "expense").strip()
    competence_month = (request.args.get("competence_month") or "").strip()
    where = [
        "t.type=?",
        "t.status NOT IN ('duplicate','ignored')",
        "NOT EXISTS (SELECT 1 FROM transaction_reconciliations r WHERE r.expense_transaction_id=t.id OR r.income_transaction_id=t.id)",
    ]
    params: list[Any] = [tx_type]
    if competence_month:
        where.append("t.competence_month=?")
        params.append(competence_month)
    with _db_connect() as conn:
        rows = conn.execute(
            f"""
            SELECT t.category_id, IFNULL(c.name,'SEM CATEGORIA'), IFNULL(c.color,'#6b7280'),
                   IFNULL(SUM(t.amount),0), COUNT(1)
            FROM transactions t
            LEFT JOIN categories c ON c.id=t.category_id
            WHERE {" AND ".join(where)}
            GROUP BY t.category_id, c.name, c.color
            ORDER BY ABS(SUM(t.amount)) DESC
            """,
            params,
        ).fetchall()
    total_abs = sum(abs(float(r[3] or 0)) for r in rows) or 1.0
    return jsonify(
        [
            {
                "category_id": row[0],
                "category_name": row[1],
                "category_color": row[2],
                "total": float(row[3] or 0),
                "count": int(row[4] or 0),
                "percentage": round(
                    (abs(float(row[3] or 0)) / total_abs) * 100, 2
                ),
            }
            for row in rows
        ]
    )


@bp.route("/api/v1/reports/monthly")
def report_monthly():
    with _db_connect() as conn:
        rows = conn.execute(
            """
            SELECT competence_month,
                   IFNULL(SUM(CASE WHEN type='income' THEN amount ELSE 0 END),0) as income,
                   IFNULL(SUM(CASE WHEN type='expense' THEN amount ELSE 0 END),0) as expense,
                   COUNT(1)
            FROM transactions
            WHERE status NOT IN ('duplicate','ignored')
              AND NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                              WHERE r.expense_transaction_id=transactions.id OR r.income_transaction_id=transactions.id)
            GROUP BY competence_month
            ORDER BY competence_month DESC
            """
        ).fetchall()
    return jsonify(
        [
            {
                "month": row[0],
                "income": float(row[1] or 0),
                "expense": float(row[2] or 0),
                "balance": float(row[1] or 0) + float(row[2] or 0),
                "transaction_count": int(row[3] or 0),
            }
            for row in rows
        ]
    )
