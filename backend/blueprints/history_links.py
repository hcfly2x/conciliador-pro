from __future__ import annotations

import datetime as dt
import time
import uuid
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from auth import record_audit
from ._shared import allow_collab_write

bp = Blueprint("history_links", __name__)


def _application():
    from core import application

    return application


def db_connect(*args, **kwargs):
    return _application().db_connect(*args, **kwargs)


@bp.route("/api/v1/transactions/<tx_id>/history-link", methods=["POST"])
@allow_collab_write
def review_history_link(tx_id: str):
    application = _application()
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action not in {"confirm", "reject"}:
        return jsonify(
            {"detail": "action deve ser confirm ou reject", "code": "VALIDATION_ERROR"}
        ), 400
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT history_match_id,identity_score,history_match_confirmed,locked,type,
                   category_id,subcategory_id,status,installment_plan_id
            FROM transactions
            WHERE id=?
            """,
            (tx_id,),
        ).fetchone()
        if not row:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        match_id = row[0]
        if not match_id:
            return jsonify(
                {
                    "detail": "Nao existe candidato de vinculo",
                    "code": "NO_LINK_CANDIDATE",
                }
            ), 409
        if action == "confirm":
            if float(row[1] or 0) < application.HISTORY_LINK_CANDIDATE_THRESHOLD:
                return jsonify(
                    {
                        "detail": "Candidato abaixo do limiar de seguranca",
                        "code": "LOW_LINK_SCORE",
                    }
                ), 409
            history = conn.execute(
                "SELECT category_id,subcategory_id,type FROM classification_history WHERE id=?",
                (match_id,),
            ).fetchone()
            if not history:
                return jsonify(
                    {
                        "detail": "Registro historico nao encontrado",
                        "code": "HISTORY_NOT_FOUND",
                    }
                ), 409
            validation_error, validation_status = (
                application.validate_classification_selection(conn, history[0], history[1])
            )
            if validation_error:
                return jsonify(validation_error), validation_status
            if history[2] != row[4]:
                return jsonify(
                    {
                        "detail": "Classificacao historica incompativel com o tipo do lancamento",
                        "code": "HISTORY_TYPE_MISMATCH",
                    }
                ), 422
            classification_changes = (row[5], row[6]) != (history[0], history[1])
            if int(row[3] or 0) == 1 and classification_changes:
                return jsonify(
                    {
                        "detail": "Lancamento protegido. Desbloqueie antes de substituir a classificacao pelo vinculo.",
                        "code": "TX_LOCKED",
                    }
                ), 423
            user = application.current_user()
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            conn.execute(
                """
                UPDATE transactions
                SET history_match_confirmed=1,
                    history_match_rejected_id=NULL,
                    match_notes=?,
                    category_id=?,
                    subcategory_id=?,
                    status='reconciled',
                    locked=1,
                    classified_by=?,
                    classified_at=?
                WHERE id=?
                """,
                (
                    "Vinculo historico confirmado; classificacao replicada da base historica",
                    history[0],
                    history[1],
                    user.get("username") or "",
                    now,
                    tx_id,
                ),
            )
            record_audit(
                user,
                "confirm_history_link",
                "transaction",
                tx_id,
                "history_match_id",
                "",
                match_id,
                conn=conn,
            )
            conn.execute(
                "DELETE FROM transaction_suggestions WHERE transaction_id=?", (tx_id,)
            )
            conn.execute(
                "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                (tx_id,),
            )
            affected_ids = [tx_id]
            if row[8]:
                sibling_ids = [
                    item[0]
                    for item in conn.execute(
                        "SELECT id FROM transactions WHERE installment_plan_id=? AND id<>? AND locked=0",
                        (row[8], tx_id),
                    ).fetchall()
                ]
                if sibling_ids:
                    sibling_placeholders = ",".join("?" for _ in sibling_ids)
                    conn.execute(
                        f"""
                        UPDATE transactions
                        SET category_id=?,subcategory_id=?,status='reconciled',locked=1,
                            classified_by=?,classified_at=?,history_match_id=NULL,
                            history_match_confirmed=0,identity_score=0,match_probability=0,match_notes=''
                        WHERE id IN ({sibling_placeholders})
                        """,
                        [history[0], history[1], user.get("username") or "", now]
                        + sibling_ids,
                    )
                    for sibling_id in sibling_ids:
                        conn.execute(
                            "DELETE FROM transaction_suggestions WHERE transaction_id=?",
                            (sibling_id,),
                        )
                        conn.execute(
                            "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                            (sibling_id,),
                        )
                    affected_ids.extend(sibling_ids)
                conn.execute(
                    """
                    UPDATE installment_plans
                    SET category_id=?,subcategory_id=?,classified_by=?,classified_at=?,updated_at=?
                    WHERE id=?
                    """,
                    (
                        history[0],
                        history[1],
                        user.get("username") or "",
                        now,
                        now,
                        row[8],
                    ),
                )
            if row[5] != history[0]:
                record_audit(
                    user,
                    "classify_from_history_link",
                    "transaction",
                    tx_id,
                    "category_id",
                    row[5] or "",
                    history[0],
                    conn=conn,
                )
            if row[6] != history[1]:
                record_audit(
                    user,
                    "classify_from_history_link",
                    "transaction",
                    tx_id,
                    "subcategory_id",
                    row[6] or "",
                    history[1] or "",
                    conn=conn,
                )
            if row[7] != "reconciled":
                record_audit(
                    user,
                    "classify_from_history_link",
                    "transaction",
                    tx_id,
                    "status",
                    row[7] or "",
                    "reconciled",
                    conn=conn,
                )
            return jsonify(
                {
                    "id": tx_id,
                    "history_match_id": match_id,
                    "history_match_confirmed": True,
                    "category_id": history[0],
                    "subcategory_id": history[1],
                    "status": "reconciled",
                    "locked": True,
                    "classified_by": user.get("username") or "",
                    "classified_at": now,
                    "affected_ids": affected_ids,
                    "affected_count": len(affected_ids),
                    "ok": True,
                }
            )
        conn.execute(
            """
            UPDATE transactions
            SET history_match_id=NULL,history_match_confirmed=0,history_match_rejected_id=?,
                identity_score=0,match_probability=0,match_notes='',
                suggested_category_id=NULL,suggested_subcategory_id=NULL
            WHERE id=?
            """,
            (match_id, tx_id),
        )
        record_audit(
            application.current_user(),
            "reject_history_link",
            "transaction",
            tx_id,
            "history_match_id",
            match_id,
            "",
            conn=conn,
        )
        conn.execute(
            "DELETE FROM transaction_suggestions WHERE transaction_id=?", (tx_id,)
        )
        conn.execute(
            "DELETE FROM transaction_suggestion_state WHERE transaction_id=?", (tx_id,)
        )
    return jsonify(
        {
            "id": tx_id,
            "history_match_id": None,
            "history_match_confirmed": False,
            "ok": True,
        }
    )


def confirm_history_link_in_batch(conn, tx_id: str) -> tuple[dict[str, Any], str]:
    """Confirma um candidato ja validado pelo lote usando a mesma regra de classificacao individual."""
    application = _application()
    row = conn.execute(
        """
        SELECT history_match_id,identity_score,history_match_confirmed,locked,type,
               category_id,subcategory_id,status,installment_plan_id
        FROM transactions WHERE id=?
        """,
        (tx_id,),
    ).fetchone()
    if not row or not row[0]:
        return {}, "Candidato de vinculo nao encontrado"
    if float(row[1] or 0) < application.HISTORY_LINK_CANDIDATE_THRESHOLD:
        return {}, "Candidato abaixo do limiar de seguranca"
    history = conn.execute(
        "SELECT category_id,subcategory_id,type FROM classification_history WHERE id=?",
        (row[0],),
    ).fetchone()
    if not history:
        return {}, "Registro historico nao encontrado"
    validation_error, _validation_status = application.validate_classification_selection(
        conn, history[0], history[1]
    )
    if validation_error:
        return {}, str(
            validation_error.get("detail") or "Classificacao historica invalida"
        )
    if history[2] != row[4]:
        return {}, "Classificacao historica incompativel com o tipo do lancamento"
    classification_changes = (row[5], row[6]) != (history[0], history[1])
    if int(row[3] or 0) == 1 and classification_changes:
        return {}, "Lancamento protegido"

    user = application.current_user()
    username = user.get("username") or ""
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    match_id = row[0]
    conn.execute(
        """
        UPDATE transactions
        SET history_match_confirmed=1,history_match_rejected_id=NULL,
            match_notes='Vinculo historico confirmado em lote; classificacao replicada da base historica',
            category_id=?,subcategory_id=?,status='reconciled',locked=1,
            classified_by=?,classified_at=?
        WHERE id=?
        """,
        (history[0], history[1], username, now, tx_id),
    )
    record_audit(
        user,
        "confirm_history_link_batch",
        "transaction",
        tx_id,
        "history_match_id",
        "",
        match_id,
        conn=conn,
    )
    affected = [tx_id]
    if row[8]:
        siblings = [
            item[0]
            for item in conn.execute(
                "SELECT id FROM transactions WHERE installment_plan_id=? AND id<>? AND locked=0",
                (row[8], tx_id),
            ).fetchall()
        ]
        if siblings:
            sibling_placeholders = ",".join("?" for _ in siblings)
            conn.execute(
                f"""
                UPDATE transactions
                SET category_id=?,subcategory_id=?,status='reconciled',locked=1,
                    classified_by=?,classified_at=?,history_match_id=NULL,
                    history_match_confirmed=0,identity_score=0,match_probability=0,match_notes=''
                WHERE id IN ({sibling_placeholders})
                """,
                [history[0], history[1], username, now] + siblings,
            )
            affected.extend(siblings)
        conn.execute(
            """
            UPDATE installment_plans
            SET category_id=?,subcategory_id=?,classified_by=?,classified_at=?,updated_at=?
            WHERE id=?
            """,
            (history[0], history[1], username, now, now, row[8]),
        )
    for affected_id in affected:
        conn.execute(
            "DELETE FROM transaction_suggestions WHERE transaction_id=?", (affected_id,)
        )
        conn.execute(
            "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
            (affected_id,),
        )
    if row[5] != history[0]:
        record_audit(
            user,
            "classify_from_history_link_batch",
            "transaction",
            tx_id,
            "category_id",
            row[5] or "",
            history[0],
            conn=conn,
        )
    if row[6] != history[1]:
        record_audit(
            user,
            "classify_from_history_link_batch",
            "transaction",
            tx_id,
            "subcategory_id",
            row[6] or "",
            history[1] or "",
            conn=conn,
        )
    if row[7] != "reconciled":
        record_audit(
            user,
            "classify_from_history_link_batch",
            "transaction",
            tx_id,
            "status",
            row[7] or "",
            "reconciled",
            conn=conn,
        )
    return {
        "id": tx_id,
        "history_match_id": match_id,
        "history_match_confirmed": True,
        "category_id": history[0],
        "subcategory_id": history[1],
        "affected_ids": affected,
    }, ""


def strict_history_match_for_batch(
    row: Any,
    history_index: dict[tuple[str, str, int], list[Any]],
    installment_amount_index: dict[tuple[str, int], list[Any]],
) -> dict[str, Any] | None:
    """Aplica a regra estrita comum e a excecao confirmada para totais parcelados."""
    application = _application()
    tx_type = str(row[5] or "")
    tx_date = str(row[1] or "")
    tx_description = str(row[2] or row[3] or "")
    tx_amount = abs(float(row[4] or 0))
    rejected_id = row[10]
    try:
        installment_current = int(row[7] or 0)
        installment_total = int(row[8] or 0)
    except (TypeError, ValueError):
        installment_current = installment_total = 0
    best: dict[str, Any] | None = None
    standard_key = (tx_type, tx_date, int(round(tx_amount * 100)))
    for history in history_index.get(standard_key, []):
        history_id = str(history[0])
        if history_id == rejected_id:
            continue
        similarity = round(
            application.description_similarity(tx_description, history[2] or "") * 100, 1
        )
        if similarity < application.BATCH_DESCRIPTION_SIMILARITY_THRESHOLD:
            continue
        candidate = {
            "history_match_id": history_id,
            "identity_score": 100.0,
            "category_id": history[5],
            "subcategory_id": history[6],
            "match_basis": "standard",
            "comparison_date": tx_date,
            "comparison_amount": tx_amount,
            "description_similarity": similarity,
            "date_difference_days": 0,
            "amount_difference": 0.0,
        }
        if best is None or similarity > float(best["description_similarity"]):
            best = candidate

    if best is not None:
        return best

    if 0 < installment_current <= installment_total and installment_total > 1:
        first_date = application.shift_months(tx_date, -(installment_current - 1))
        comparison_amount = round(tx_amount * installment_total, 2)
        comparison_cents = int(round(comparison_amount * 100))
        installment_best: dict[str, Any] | None = None
        installment_best_rank: tuple[float, float, float] | None = None
        valid_installment_candidates = 0
        seen: set[str] = set()
        for amount_cents in range(comparison_cents - 100, comparison_cents + 101):
            for history in installment_amount_index.get((tx_type, amount_cents), []):
                history_id = str(history[0])
                if history_id in seen or history_id == rejected_id:
                    continue
                seen.add(history_id)
                similarity = round(
                    application.description_similarity(tx_description, history[2] or "") * 100, 1
                )
                amount_difference = round(
                    abs(comparison_amount - float(history[3] or 0)), 2
                )
                if similarity < 50.0 or amount_difference > 1.0:
                    continue
                valid_installment_candidates += 1
                try:
                    history_date = dt.date.fromisoformat(str(history[1] or ""))
                    date_options = [value for value in (tx_date, first_date) if value]
                    comparison_date = min(
                        date_options,
                        key=lambda value: abs(
                            (dt.date.fromisoformat(value) - history_date).days
                        ),
                    )
                    date_difference = abs(
                        (dt.date.fromisoformat(comparison_date) - history_date).days
                    )
                except (TypeError, ValueError):
                    comparison_date = first_date
                    date_difference = 999999
                rank = (similarity, -amount_difference, -float(date_difference))
                if installment_best_rank is None or rank > installment_best_rank:
                    installment_best_rank = rank
                    installment_best = {
                        "history_match_id": history_id,
                        "identity_score": 100.0,
                        "category_id": history[5],
                        "subcategory_id": history[6],
                        "match_basis": "installment_total",
                        "comparison_date": comparison_date,
                        "comparison_amount": comparison_amount,
                        "description_similarity": similarity,
                        "date_difference_days": date_difference,
                        "amount_difference": amount_difference,
                    }
        if installment_best is not None:
            installment_best["candidate_count"] = valid_installment_candidates
            installment_best["requires_manual_review"] = (
                valid_installment_candidates > 1
            )
            best = installment_best
    return best


@bp.route("/api/v1/transactions/history-links/batch", methods=["POST"])
@allow_collab_write
def prepare_history_links_batch():
    application = _application()
    started_at = time.perf_counter()
    operation_id = uuid.uuid4().hex[:8]
    data = request.get_json(silent=True) or {}
    ids = list(
        dict.fromkeys(
            str(item).strip() for item in (data.get("ids") or []) if str(item).strip()
        )
    )
    if not ids:
        return jsonify(
            {"detail": "Selecione ao menos um lancamento", "code": "VALIDATION_ERROR"}
        ), 400
    if len(ids) > 500:
        return jsonify(
            {
                "detail": "Selecione no maximo 500 lancamentos por lote",
                "code": "BATCH_TOO_LARGE",
            }
        ), 400
    placeholders = ",".join("?" for _ in ids)
    matched_ids: list[str] = []
    manual_review_ids: list[str] = []
    without_match_ids: list[str] = []
    skipped_ids: list[str] = []
    failed_ids: list[str] = []
    affected_ids: set[str] = set()
    progress_logs: list[dict[str, str]] = []

    def log_progress(message: str) -> None:
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        progress_logs.append({"time": timestamp, "message": message})
        current_app.logger.info("[history-link-batch:%s] %s", operation_id, message)

    def log_position(position: int) -> None:
        if position % 10 == 0 or position == len(ids):
            log_progress(
                f"Progresso: {position}/{len(ids)} analisados; "
                f"{len(matched_ids)} confirmados; {len(manual_review_ids)} para revisao manual; "
                f"{len(without_match_ids)} sem vinculo"
            )

    log_progress(f"Lote iniciado: {len(ids)} lancamento(s) selecionado(s)")
    with db_connect() as conn:
        history_rows = conn.execute(
            """
            SELECT id,date,description,ABS(amount),account_id,category_id,subcategory_id,type
            FROM classification_history
            """
        ).fetchall()
        history_index: dict[tuple[str, str, int], list[Any]] = {}
        installment_amount_index: dict[tuple[str, int], list[Any]] = {}
        for history in history_rows:
            amount_cents = int(round(float(history[3] or 0) * 100))
            history_type = str(history[7] or "")
            history_index.setdefault(
                (history_type, str(history[1] or ""), amount_cents),
                [],
            ).append(history)
            installment_amount_index.setdefault(
                (history_type, amount_cents), []
            ).append(history)
        history_cache: dict[str, list[tuple[Any, ...]]] = {"expense": [], "income": []}
        for history in history_rows:
            history_cache.setdefault(str(history[7] or ""), []).append(
                tuple(history[:7])
            )
        log_progress(f"Base historica indexada: {len(history_rows)} registro(s)")
        rows = conn.execute(
            f"""
            SELECT id,date,description,description_norm,amount,type,account_id,
                   installment_current,installment_total,history_match_confirmed,
                   history_match_rejected_id,locked
            FROM transactions WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        by_id = {row[0]: row for row in rows}
        for position, tx_id in enumerate(ids, start=1):
            row = by_id.get(tx_id)
            if (
                not row
                or bool(row[9])
                or bool(row[11])
            ):
                skipped_ids.append(tx_id)
                log_position(position)
                continue
            identity = strict_history_match_for_batch(
                row, history_index, installment_amount_index
            )
            if not identity:
                manual_identity = application.find_identity_match(
                    conn,
                    {
                        "date": row[1],
                        "description": row[2],
                        "description_norm": row[2],
                        "amount": row[4],
                        "type": row[5],
                        "account_id": row[6],
                        "installment_current": row[7],
                        "installment_total": row[8],
                    },
                    history_cache,
                )
                if (
                    manual_identity
                    and float(manual_identity.get("identity_score") or 0)
                    >= application.HISTORY_LINK_CANDIDATE_THRESHOLD
                    and str(manual_identity.get("history_match_id") or "")
                    != str(row[10] or "")
                ):
                    conn.execute(
                        """
                        UPDATE transactions
                        SET history_match_id=?,history_match_confirmed=0,identity_score=?,match_probability=?,
                            match_notes=?,suggested_category_id=?,suggested_subcategory_id=?
                        WHERE id=?
                        """,
                        (
                            manual_identity.get("history_match_id"),
                            manual_identity.get("identity_score"),
                            manual_identity.get("identity_score"),
                            "Revisao manual apos lote: candidato fora da regra estrita",
                            manual_identity.get("category_id"),
                            manual_identity.get("subcategory_id"),
                            tx_id,
                        ),
                    )
                    conn.execute(
                        "DELETE FROM transaction_suggestions WHERE transaction_id=?",
                        (tx_id,),
                    )
                    conn.execute(
                        "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                        (tx_id,),
                    )
                    manual_review_ids.append(tx_id)
                else:
                    without_match_ids.append(tx_id)
                log_position(position)
                continue
            if identity.get("requires_manual_review"):
                candidate_count = int(identity.get("candidate_count") or 2)
                candidate_label = (
                    "candidatos parcelados validos"
                    if identity.get("match_basis") == "installment_total"
                    else "candidatos validos"
                )
                conn.execute(
                    """
                    UPDATE transactions
                    SET history_match_id=?,history_match_confirmed=0,identity_score=?,match_probability=?,
                        match_notes=?,suggested_category_id=?,suggested_subcategory_id=?
                    WHERE id=?
                    """,
                    (
                        identity.get("history_match_id"),
                        identity.get("identity_score"),
                        identity.get("identity_score"),
                        f"Revisao manual: {candidate_count} {candidate_label}",
                        identity.get("category_id"),
                        identity.get("subcategory_id"),
                        tx_id,
                    ),
                )
                conn.execute(
                    "DELETE FROM transaction_suggestions WHERE transaction_id=?",
                    (tx_id,),
                )
                conn.execute(
                    "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                    (tx_id,),
                )
                manual_review_ids.append(tx_id)
                log_progress(
                    f"Revisao manual: lancamento {position}/{len(ids)} possui "
                    f"{candidate_count} {candidate_label}"
                )
                log_position(position)
                continue
            note = (
                "Match pelo valor total parcelado na base historica"
                if identity.get("match_basis") == "installment_total"
                else "Match com base historica"
            )
            conn.execute(
                """
                UPDATE transactions
                SET history_match_id=?,history_match_confirmed=0,identity_score=?,match_probability=?,
                    match_notes=?,suggested_category_id=?,suggested_subcategory_id=?
                WHERE id=?
                """,
                (
                    identity.get("history_match_id"),
                    identity.get("identity_score"),
                    identity.get("identity_score"),
                    note,
                    identity.get("category_id"),
                    identity.get("subcategory_id"),
                    tx_id,
                ),
            )
            conn.execute(
                "DELETE FROM transaction_suggestions WHERE transaction_id=?", (tx_id,)
            )
            conn.execute(
                "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                (tx_id,),
            )
            confirmation, confirmation_error = confirm_history_link_in_batch(
                conn, tx_id
            )
            if confirmation_error:
                failed_ids.append(tx_id)
                log_position(position)
                continue
            matched_ids.append(tx_id)
            affected_ids.update(confirmation.get("affected_ids") or [tx_id])
            log_position(position)
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    log_progress(
        f"Lote concluido em {duration_ms} ms: {len(matched_ids)} confirmado(s), "
        f"{len(manual_review_ids)} para revisao manual, {len(without_match_ids)} sem vinculo, "
        f"{len(skipped_ids)} ignorado(s), {len(failed_ids)} falha(s)"
    )
    return jsonify(
        {
            "selected": len(ids),
            "matched": len(matched_ids),
            "without_match": len(without_match_ids),
            "manual_review": len(manual_review_ids),
            "skipped": len(skipped_ids),
            "failed": len(failed_ids),
            "matched_ids": matched_ids,
            "manual_review_ids": manual_review_ids,
            "without_match_ids": without_match_ids,
            "skipped_ids": skipped_ids,
            "failed_ids": failed_ids,
            "affected_ids": sorted(affected_ids),
            "operation_id": operation_id,
            "duration_ms": duration_ms,
            "logs": progress_logs,
        }
    )


@bp.route("/api/v1/transactions/<tx_id>/unlink-history", methods=["PATCH"])
def unlink_history_match(tx_id: str):
    application = _application()
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id,history_match_id FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if not exists:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        conn.execute(
            """
            UPDATE transactions
            SET history_match_id=NULL,
                history_match_confirmed=0,
                history_match_rejected_id=?,
                identity_score=0,
                match_probability=0,
                match_notes='',
                suggested_category_id=NULL,
                suggested_subcategory_id=NULL
            WHERE id=?
            """,
            (exists[1], tx_id),
        )
        record_audit(
            application.current_user(),
            "unlink_history",
            "transaction",
            tx_id,
            "history_match_id",
            exists[1] or "",
            "",
            conn=conn,
        )
    return jsonify({"id": tx_id, "ok": True})


@bp.route("/api/v1/transactions/recalculate-probabilities", methods=["POST"])
@bp.route("/api/v1/transactions/recalculate-history-links", methods=["POST"])
def recalculate_probabilities():
    application = _application()
    job_id = application.enqueue_probability_recalculation()
    with db_connect() as conn:
        row = conn.execute(
            "SELECT status FROM recalculation_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return jsonify({"job_id": job_id, "status": row[0] if row else "queued"}), 202


@bp.route("/api/v1/recalculation-jobs/<job_id>")
def recalculation_job_status(job_id: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,status,processed,total,updated,error,created_at,started_at,finished_at
            FROM recalculation_jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return jsonify(
            {"detail": "Processamento nao encontrado", "code": "NOT_FOUND"}
        ), 404
    return jsonify(
        {
            "id": row[0],
            "status": row[1],
            "processed": row[2],
            "total": row[3],
            "updated": row[4],
            "error": row[5],
            "created_at": row[6],
            "started_at": row[7],
            "finished_at": row[8],
        }
    )


@bp.route("/api/v1/history")
def classification_history_list():
    application = _application()
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(500, max(1, int(request.args.get("page_size", 50))))
    where = ["1=1"]
    params: list[Any] = []

    tx_type = (request.args.get("type") or "").strip()
    if tx_type:
        where.append("h.type=?")
        params.append(tx_type)
    account_id = (request.args.get("account_id") or "").strip()
    if account_id:
        where.append("h.account_id=?")
        params.append(account_id)
    category_id = (request.args.get("category_id") or "").strip()
    if category_id:
        where.append("h.category_id=?")
        params.append(category_id)
    subcategory_id = (request.args.get("subcategory_id") or "").strip()
    if subcategory_id:
        where.append("h.subcategory_id=?")
        params.append(subcategory_id)
    linked_filter = (request.args.get("linked") or "").strip().lower()
    if linked_filter in ("true", "1", "yes", "linked"):
        where.append(
            "EXISTS (SELECT 1 FROM transactions tx WHERE tx.history_match_id=h.id AND tx.history_match_confirmed=1)"
        )
    elif linked_filter in ("false", "0", "no", "unlinked"):
        where.append(
            "NOT EXISTS (SELECT 1 FROM transactions tx WHERE tx.history_match_id=h.id AND tx.history_match_confirmed=1)"
        )
    sheet_filter = (request.args.get("sheet") or "").strip().lower()
    if sheet_filter in {"saidas", "entradas", "helcio_smartek"}:
        where.append("h.source_file_id LIKE ?")
        params.append(f"%:sheet:{sheet_filter}")
    search = (request.args.get("search") or "").strip()
    if search:
        s_norm = f"%{application.escape_like(application.norm_text(search))}%"
        s_raw = f"%{application.escape_like(search)}%"
        where.append(
            "("
            "h.description_norm LIKE ? ESCAPE '\\' OR "
            "LOWER(h.description) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(a.name,'')) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(c.name,'')) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(sc.name,'')) LIKE ? ESCAPE '\\' OR "
            "h.date LIKE ? ESCAPE '\\' OR "
            "CAST(h.amount AS TEXT) LIKE ? ESCAPE '\\'"
            ")"
        )
        s_lower = f"%{application.escape_like(search.lower())}%"
        params.extend([s_norm, s_lower, s_lower, s_lower, s_lower, s_raw, s_raw])

    sort_by = (request.args.get("sort_by") or "date").strip()
    sort_order = (request.args.get("sort_order") or "desc").strip().lower()
    order = "DESC" if sort_order != "asc" else "ASC"
    allowed = {
        "date": "h.date",
        "description": "h.description",
        "amount": "h.amount",
        "type": "h.type",
        "account": "a.name",
        "category": "c.name",
        "subcategory": "sc.name",
        "linked": "CASE WHEN EXISTS (SELECT 1 FROM transactions tx WHERE tx.history_match_id=h.id AND tx.history_match_confirmed=1) THEN 1 ELSE 0 END",
    }
    order_by = allowed.get(sort_by, "h.date")

    with db_connect() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(1)
            FROM classification_history h
            LEFT JOIN accounts a ON a.id=h.account_id
            LEFT JOIN categories c ON c.id=h.category_id
            LEFT JOIN subcategories sc ON sc.id=h.subcategory_id
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()[0]
        total_linked = conn.execute(
            f"""
            SELECT COUNT(DISTINCT h.id)
            FROM classification_history h
            LEFT JOIN accounts a ON a.id=h.account_id
            LEFT JOIN categories c ON c.id=h.category_id
            LEFT JOIN subcategories sc ON sc.id=h.subcategory_id
            JOIN transactions t ON t.history_match_id=h.id AND t.history_match_confirmed=1
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()[0]
        off = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT h.id,h.date,h.description,h.amount,h.type,
                   h.account_id,IFNULL(a.name,''),
                   h.category_id,IFNULL(c.name,''),IFNULL(c.color,''),
                   h.subcategory_id,IFNULL(sc.name,''),
                   h.source_file_id,
                   CASE
                     WHEN h.source_file_id LIKE '%:sheet:saidas' THEN 'saidas'
                     WHEN h.source_file_id LIKE '%:sheet:entradas' THEN 'entradas'
                     WHEN h.source_file_id LIKE '%:sheet:helcio_smartek' THEN 'helcio_smartek'
                     ELSE ''
                   END,
                   t.id,t.description,t.date,ABS(t.amount)
            FROM classification_history h
            LEFT JOIN accounts a ON a.id=h.account_id
            LEFT JOIN categories c ON c.id=h.category_id
            LEFT JOIN subcategories sc ON sc.id=h.subcategory_id
            LEFT JOIN transactions t ON t.id=(
                SELECT tx.id
                FROM transactions tx
                WHERE tx.history_match_id=h.id AND tx.history_match_confirmed=1
                ORDER BY tx.date DESC, tx.id ASC
                LIMIT 1
            )
            WHERE {" AND ".join(where)}
            ORDER BY {order_by} {order}, h.description ASC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, off],
        ).fetchall()

    return jsonify(
        {
            "items": [
                {
                    "id": row[0],
                    "date": row[1] or "",
                    "description": row[2],
                    "amount": row[3],
                    "type": row[4],
                    "account_id": row[5],
                    "account_name": row[6],
                    "category_id": row[7],
                    "category_name": row[8],
                    "category_color": row[9],
                    "subcategory_id": row[10],
                    "subcategory_name": row[11],
                    "source_file_id": row[12],
                    "seed_sheet": row[13],
                    "linked_tx_id": row[14],
                    "linked_tx_description": row[15],
                    "linked_tx_date": row[16],
                    "linked_tx_amount": row[17],
                }
                for row in rows
            ],
            "total": total,
            "total_linked": total_linked,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    )
