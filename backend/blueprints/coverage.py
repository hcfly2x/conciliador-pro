from __future__ import annotations

import base64
import datetime as dt
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request

from auth import record_audit

bp = Blueprint("coverage", __name__)
logger = logging.getLogger(__name__)


def _application():
    from core import application

    return application


def db_connect(*args, **kwargs):
    return _application().db_connect(*args, **kwargs)


def account_folder_name(value):
    return _application().account_folder_name(value)


def project_relative_path(value):
    return _application().project_relative_path(value)


def delete_import_batches(conn, imported_ids):
    return _application().delete_import_batches(conn, imported_ids)


def current_user():
    return _application().current_user()


def is_unknown_historical_account_label(value):
    return _application().is_unknown_historical_account_label(value)


COVERAGE_YEARS = tuple(range(2023, 2027))
COVERAGE_DEFAULT_YEAR = 2026


def coverage_months(year: int) -> list[str]:
    return [f"{year:04d}/{month:02d}" for month in range(1, 13)]


def coverage_account_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id,name,type,color,is_active
        FROM accounts
        WHERE is_active=1
        ORDER BY type,name
        """
    ).fetchall()
    return [r for r in rows if not is_unknown_historical_account_label(r["name"])]


def coverage_files_for(account_name: str, year_month: str) -> list[dict[str, Any]]:
    year, month = year_month.split("/")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 1) Cofre persistente no banco (fonte principal no modo hosted)
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, size, created_at FROM stored_documents WHERE account_name=? AND year_month=? ORDER BY filename",
            (account_name, year_month),
        ).fetchall()
    for r in rows:
        seen.add(str(r[1]).lower())
        files.append(
            {
                "filename": r[1],
                "path": f"db://{r[0]}",
                "doc_id": r[0],
                "size": r[2],
                "modified_at": r[3],
            }
        )
    # 2) Arquivos em disco (uso local / legado)
    folder = _application().DOCS / year / month / account_folder_name(account_name)
    if folder.exists():
        allowed = {".csv", ".xls", ".xlsx", ".pdf"}
        for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if (
                path.is_file()
                and path.suffix.lower() in allowed
                and path.name.lower() not in seen
            ):
                stat = path.stat()
                files.append(
                    {
                        "filename": path.name,
                        "path": project_relative_path(path),
                        "size": stat.st_size,
                        "modified_at": dt.datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(timespec="seconds"),
                    }
                )
    return sorted(files, key=lambda f: str(f["filename"]).lower())


@bp.route("/api/v1/coverage")
def coverage():
    raw_year = (request.args.get("year") or str(COVERAGE_DEFAULT_YEAR)).strip()
    try:
        year = int(raw_year)
    except ValueError:
        return jsonify(
            {"detail": "year deve ser um ano valido", "code": "VALIDATION_ERROR"}
        ), 400
    if year not in COVERAGE_YEARS:
        return jsonify(
            {
                "detail": f"year deve estar entre {COVERAGE_YEARS[0]} e {COVERAGE_YEARS[-1]}",
                "code": "VALIDATION_ERROR",
            }
        ), 400

    months = coverage_months(year)
    month_set = set(months)
    with db_connect() as conn:
        accounts = coverage_account_rows(conn)
        dispensed = {
            (r[0], r[1]): {"status": r[2], "reason": r[3]}
            for r in conn.execute(
                """
                SELECT account_id,year_month,status,reason
                FROM account_file_coverage
                WHERE year_month LIKE ?
                """,
                (f"{year:04d}/%",),
            ).fetchall()
        }

        # Uma consulta traz todos os documentos do ano. Os nomes sao mantidos
        # em conjuntos para evitar contar duas vezes o mesmo arquivo no banco e
        # no armazenamento local legado.
        file_names: dict[tuple[str, str], set[str]] = {}
        for row in conn.execute(
            """
            SELECT account_name,year_month,filename
            FROM stored_documents
            WHERE year_month LIKE ?
            """,
            (f"{year:04d}/%",),
        ).fetchall():
            if row[1] in month_set:
                file_names.setdefault((row[0], row[1]), set()).add(str(row[2]).lower())

    allowed = {".csv", ".xls", ".xlsx", ".pdf"}
    for acc in accounts:
        account_name = acc["name"]
        folder_name = account_folder_name(account_name)
        for ym in months:
            _, month = ym.split("/")
            folder = _application().DOCS / str(year) / month / folder_name
            if not folder.exists():
                continue
            names = file_names.setdefault((account_name, ym), set())
            for path in folder.iterdir():
                if path.is_file() and path.suffix.lower() in allowed:
                    names.add(path.name.lower())

    matrix: dict[str, Any] = {}
    current_month = dt.datetime.now().date().replace(day=1)
    for acc in accounts:
        cells: dict[str, Any] = {}
        for ym in months:
            file_count = len(file_names.get((acc["name"], ym), set()))
            disp = dispensed.get((acc["id"], ym))
            month_date = dt.date(int(ym[:4]), int(ym[5:]), 1)
            if file_count:
                status = "imported"
            elif disp:
                status = "dispensed"
            elif month_date > current_month:
                status = "future"
            else:
                status = "missing"
            cells[ym] = {
                "status": status,
                "file_count": file_count,
                "reason": (disp or {}).get("reason", ""),
            }
        matrix[acc["id"]] = {
            "id": acc["id"],
            "name": acc["name"],
            "type": acc["type"],
            "color": acc["color"],
            "folder": account_folder_name(acc["name"]),
            "cells": cells,
        }
    return jsonify(
        {
            "year": year,
            "available_years": list(COVERAGE_YEARS),
            "months": months,
            "matrix": matrix,
        }
    )


@bp.route("/api/v1/coverage/dispense", methods=["POST", "DELETE"])
def coverage_dispense():
    data = request.get_json(force=True) or {}
    account_id = (data.get("account_id") or "").strip()
    year_month = (data.get("year_month") or "").strip()
    reason = (data.get("reason") or "").strip()
    if not account_id or not re.match(r"^\d{4}/\d{2}$", year_month):
        return jsonify(
            {
                "detail": "account_id e year_month obrigatorios",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    with db_connect() as conn:
        if request.method == "DELETE":
            conn.execute(
                "DELETE FROM account_file_coverage WHERE account_id=? AND year_month=?",
                (account_id, year_month),
            )
            return jsonify({"ok": True})
        conn.execute(
            """
            INSERT INTO account_file_coverage(id,account_id,year_month,status,reason,created_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(account_id,year_month) DO UPDATE SET
              status=excluded.status,
              reason=excluded.reason,
              created_at=excluded.created_at
            """,
            (
                str(uuid.uuid4()),
                account_id,
                year_month,
                "dispensed",
                reason,
                dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return jsonify({"ok": True})


@bp.route("/api/v1/coverage/files")
def coverage_files():
    account_id = (request.args.get("account_id") or "").strip()
    year_month = (request.args.get("year_month") or "").strip()
    if not account_id or not re.match(r"^\d{4}/\d{2}$", year_month):
        return jsonify(
            {
                "detail": "account_id e year_month obrigatorios",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    with db_connect() as conn:
        row = conn.execute(
            "SELECT name FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
    if not row:
        return jsonify({"detail": "Conta nao encontrada", "code": "NOT_FOUND"}), 404
    return jsonify({"files": coverage_files_for(row[0], year_month)})


def resolve_document_path(raw_path: str) -> Path | None:
    cleaned = (raw_path or "").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned)
    if not candidate.is_absolute():
        candidate = _application().BASE.parent / candidate
    try:
        resolved = candidate.resolve()
        docs_root = _application().DOCS.resolve()
        resolved.relative_to(docs_root)
    except (OSError, ValueError):
        return None
    return resolved


@bp.route("/api/v1/documents/<doc_id>/download")
def document_download(doc_id: str):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT filename, content_b64 FROM stored_documents WHERE id=?", (doc_id,)
        ).fetchone()
    if not row:
        return jsonify({"detail": "Arquivo nao encontrado", "code": "NOT_FOUND"}), 404
    filename = row[0]
    content = base64.b64decode(row[1])
    ext = Path(filename).suffix.lower()
    mimetypes_map = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }
    from flask import Response

    return Response(
        content,
        mimetype=mimetypes_map.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/api/v1/coverage/files", methods=["DELETE"])
def coverage_delete_file():
    data = request.get_json(force=True) or {}
    raw_path = (data.get("path") or "").strip()
    delete_transactions = bool(data.get("delete_transactions", False))
    if (
        delete_transactions
        and data.get("confirm_delete_transactions") != "EXCLUIR LANCAMENTOS"
    ):
        return jsonify(
            {
                "detail": "Confirmacao explicita obrigatoria para excluir lancamentos",
                "code": "DELETE_TRANSACTIONS_CONFIRMATION_REQUIRED",
            }
        ), 400
    if raw_path.startswith("db://"):
        doc_id = raw_path[5:]
        with db_connect() as conn:
            row = conn.execute(
                "SELECT id,filename,account_name,year_month,imported_file_id FROM stored_documents WHERE id=?",
                (doc_id,),
            ).fetchone()
            if not row:
                return jsonify(
                    {"detail": "Arquivo nao encontrado", "code": "NOT_FOUND"}
                ), 404
            imported_ids = []
            if delete_transactions:
                if row[4]:
                    linked = conn.execute(
                        "SELECT id FROM imported_files WHERE id=?", (row[4],)
                    ).fetchone()
                    imported_ids = [linked[0]] if linked else []
                if not imported_ids:
                    imported_ids = [
                        r[0]
                        for r in conn.execute(
                            """
                        SELECT id FROM imported_files
                        WHERE filename=? AND account_name=? AND (year || '/' || month)=?
                        """,
                            (row[1], row[2], row[3]),
                        ).fetchall()
                    ]
                if not imported_ids:
                    legacy_candidates = conn.execute(
                        "SELECT id FROM imported_files WHERE filename=? AND account_name=?",
                        (row[1], row[2]),
                    ).fetchall()
                    if len(legacy_candidates) == 1:
                        imported_ids = [legacy_candidates[0][0]]
            tx_deleted = delete_import_batches(conn, imported_ids)
            conn.execute("DELETE FROM stored_documents WHERE id=?", (doc_id,))
            record_audit(
                current_user(),
                "delete_document",
                "document",
                doc_id,
                "filename",
                row[1],
                "",
                detail=f"deleted_transactions={tx_deleted}",
                conn=conn,
            )
        # O banco e a fonte principal, mas o desenvolvimento local mantem uma
        # copia secundaria. Remove-la evita que o mesmo documento reapareca no
        # cofre como arquivo legado logo apos a exclusao persistente.
        try:
            year, month = row[3].split("/", 1)
            local_copy = (
                _application().DOCS
                / year
                / month
                / account_folder_name(row[2])
                / Path(row[1]).name
            ).resolve()
            local_copy.relative_to(_application().DOCS.resolve())
            if local_copy.is_file():
                local_copy.unlink()
        except (AttributeError, OSError, ValueError):
            logger.warning(
                "Falha ao remover copia local do documento %s",
                doc_id,
                exc_info=True,
            )
        return jsonify(
            {
                "ok": True,
                "deleted_file": row[1],
                "deleted_imported_files": len(imported_ids),
                "deleted_transactions": tx_deleted,
            }
        )
    file_path = resolve_document_path(raw_path)
    if not file_path:
        return jsonify({"detail": "Caminho invalido", "code": "VALIDATION_ERROR"}), 400
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"detail": "Arquivo nao encontrado", "code": "NOT_FOUND"}), 404

    rel_path = project_relative_path(file_path)
    imported_ids = []
    tx_deleted = 0
    with db_connect() as conn:
        if delete_transactions:
            imported_ids = [
                r[0]
                for r in conn.execute(
                    """
                    SELECT id FROM imported_files
                    WHERE source_path=? OR source_path=?
                    """,
                    (rel_path, str(file_path)),
                ).fetchall()
            ]
        tx_deleted = delete_import_batches(conn, imported_ids)
        record_audit(
            current_user(),
            "delete_document",
            "document",
            rel_path,
            "filename",
            file_path.name,
            "",
            detail=f"deleted_transactions={tx_deleted}",
            conn=conn,
        )
    file_path.unlink()
    return jsonify(
        {
            "ok": True,
            "deleted_file": rel_path,
            "deleted_imported_files": len(imported_ids),
            "deleted_transactions": tx_deleted,
        }
    )
