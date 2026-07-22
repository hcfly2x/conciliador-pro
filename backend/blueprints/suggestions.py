from __future__ import annotations

import datetime as dt

from flask import Blueprint, jsonify, request

from auth import record_audit
from ._shared import allow_collab_write

bp = Blueprint("suggestions", __name__)


def _application():
    from core import application

    return application


def db_connect(*args, **kwargs):
    return _application().db_connect(*args, **kwargs)


@bp.route("/api/v1/transactions/suggestions/jobs", methods=["POST"])
@allow_collab_write
def start_suggestion_job():
    application = _application()
    data = request.get_json(silent=True) or {}
    job_id = application.enqueue_suggestion_job(full=bool(data.get("full")))
    with db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM suggestion_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return jsonify({"job_id": job_id, "status": row[0] if row else "queued"}), 202


@bp.route("/api/v1/suggestion-jobs/<job_id>")
def suggestion_job_status(job_id: str):
    application = _application()
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,status,mode,processed,total,updated,with_suggestions,without_suggestions,
                   message,logs_json,error,created_at,started_at,finished_at
            FROM suggestion_jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return jsonify({"detail": "Calculo nao encontrado", "code": "NOT_FOUND"}), 404
    return jsonify(application.suggestion_job_payload(row))


@bp.route("/api/v1/suggestion-jobs-active")
def active_suggestion_job():
    application = _application()
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,status,mode,processed,total,updated,with_suggestions,without_suggestions,
                   message,logs_json,error,created_at,started_at,finished_at
            FROM suggestion_jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
    if not row:
        return jsonify(
            {"detail": "Nenhum calculo em andamento", "code": "NOT_FOUND"}
        ), 404
    return jsonify(application.suggestion_job_payload(row))


@bp.route("/api/v1/transactions/suggestions/summary")
def suggestion_summary():
    application = _application()
    threshold = application.HISTORY_LINK_CANDIDATE_THRESHOLD
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND t.history_match_id IS NOT NULL
                            AND t.history_match_confirmed=0 AND t.identity_score>=? THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND qs.dismissed=0
                            AND qs.suggestion_count>0 AND qs.best_confidence>=70 THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND qs.dismissed=0
                            AND qs.suggestion_count>0 AND qs.best_confidence<70 THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND qs.dismissed=0
                            AND qs.status='completed' AND qs.suggestion_count=0 THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND qs.transaction_id IS NULL
                            AND NOT (t.history_match_id IS NOT NULL AND t.history_match_confirmed=0 AND t.identity_score>=?)
                       THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NULL AND t.locked=0 AND qs.dismissed=1 THEN 1 ELSE 0 END),
              SUM(CASE WHEN t.category_id IS NOT NULL THEN 1 ELSE 0 END)
            FROM transactions t
            LEFT JOIN transaction_suggestion_state qs ON qs.transaction_id=t.id
            WHERE NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                              WHERE r.expense_transaction_id=t.id OR r.income_transaction_id=t.id)
            """,
            (threshold, threshold),
        ).fetchone()
    return jsonify(
        {
            "pending": int(row[0] or 0),
            "links": int(row[1] or 0),
            "strong": int(row[2] or 0),
            "weak": int(row[3] or 0),
            "none": int(row[4] or 0),
            "waiting": int(row[5] or 0),
            "dismissed": int(row[6] or 0),
            "classified": int(row[7] or 0),
        }
    )


@bp.route("/api/v1/transactions/suggestions/evaluation")
def suggestion_evaluation():
    application = _application()
    try:
        limit = int(request.args.get("limit", "250"))
    except ValueError:
        return jsonify({"detail": "Limite invalido", "code": "INVALID_LIMIT"}), 400
    with db_connect() as conn:
        result = application.evaluate_suggestion_quality(conn, limit=limit)
    return jsonify(result)


@bp.route("/api/v1/transactions/<tx_id>/suggestions/dismiss", methods=["POST"])
@allow_collab_write
def dismiss_transaction_suggestions(tx_id: str):
    application = _application()
    with db_connect() as conn:
        tx = conn.execute(
            "SELECT date,description,description_norm,amount,type,account_id,merchant_norm,transaction_method,counterparty_name,bank_reference FROM transactions WHERE id=?",
            (tx_id,),
        ).fetchone()
        if not tx:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        fingerprint = application.suggestion_fingerprint(tx)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO transaction_suggestion_state(
              transaction_id,fingerprint,status,suggestion_count,best_confidence,dismissed,calculated_at,error
            ) VALUES (?,?,'completed',0,0,1,?,'')
            ON CONFLICT(transaction_id) DO UPDATE SET dismissed=1,calculated_at=excluded.calculated_at
            """,
            (tx_id, fingerprint, now),
        )
        record_audit(
            application.current_user(),
            "dismiss_suggestions",
            "transaction",
            tx_id,
            conn=conn,
        )
    return jsonify({"id": tx_id, "dismissed": True, "ok": True})


@bp.route("/api/v1/transactions/suggestions/batch", methods=["POST"])
@allow_collab_write
def tx_suggestions_batch():
    application = _application()
    data = request.get_json(force=True) or {}
    tx_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in (data.get("transaction_ids") or [])
            if str(item).strip()
        )
    )
    if len(tx_ids) > 100:
        return jsonify(
            {"detail": "No maximo 100 lancamentos por lote", "code": "BATCH_TOO_LARGE"}
        ), 400
    with db_connect() as conn:
        items, states = application.cached_suggestions(conn, tx_ids)
    return jsonify({"items": items, "states": states})


@bp.route("/api/v1/transactions/<tx_id>/suggestions")
def tx_suggestions(tx_id: str):
    application = _application()
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if not exists:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        items, states = application.cached_suggestions(conn, [tx_id])
    return jsonify({"items": items[tx_id], "state": states[tx_id]})
