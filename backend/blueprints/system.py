from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory

from auth import record_audit
from db import IS_POSTGRES

bp = Blueprint("system", __name__)
logger = logging.getLogger(__name__)
TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _application():
    # O import tardio evita ciclo e mantem monkeypatches no alias legado `app`.
    from core import application

    return application


def _clear_runtime_directory(path: Path, data_root: Path) -> int:
    """Remove somente filhos de um diretorio controlado pela aplicacao."""
    resolved = path.resolve()
    resolved.relative_to(data_root.resolve())
    removed = 0
    if not resolved.exists():
        resolved.mkdir(parents=True, exist_ok=True)
        return removed
    for child in resolved.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


@bp.route("/api/v1/health")
def health():
    application = _application()
    try:
        with application.db_connect() as conn:
            conn.execute("SELECT 1").fetchone()
            schema_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
    except Exception:
        logger.exception("Banco indisponivel durante health check")
        return jsonify({"status": "error", "db": "unavailable"}), 503
    return jsonify(
        {
            "status": "ok",
            "version": "1.0.0",
            "db": "postgres" if IS_POSTGRES else "sqlite",
            "commit": (os.environ.get("RENDER_GIT_COMMIT") or "")[:12],
            "schema_version": int(schema_row[0]),
            "worker_mode": application.WORKER_MODE,
            "worker_process": bool(application.IS_WORKER_PROCESS),
        }
    )


@bp.route("/ui/importar")
def import_preview_ui():
    return send_from_directory(TOOLS / "import-preview", "index.html")


@bp.route("/ui/varredura")
def import_scan_ui():
    return send_from_directory(TOOLS / "import-scan", "index.html")


@bp.route("/ui/arquivos")
def import_files_ui():
    return send_from_directory(TOOLS / "import-files", "index.html")


@bp.route("/api/v1/system/reset", methods=["POST"])
def system_reset():
    application = _application()
    data = request.get_json(force=True) or {}
    if data.get("confirm") != "RESETAR":
        return jsonify(
            {"detail": "Confirmacao obrigatoria: RESETAR", "code": "VALIDATION_ERROR"}
        ), 400

    if not IS_POSTGRES:
        backups = application.DATA / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / (
            "conciliador_pro_before_system_reset_"
            f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        )
        shutil.copy2(application.DB, backup)
        backup_ref = application.project_relative_path(backup)
    else:
        backup_ref = "hosted: use o backup/branch do provedor Postgres antes de resetar"

    scope = (data.get("scope") or "transactions").strip()
    wipe_categories = bool(data.get("wipe_categories"))
    if scope not in ("transactions", "all"):
        return jsonify(
            {"detail": "scope deve ser transactions ou all", "code": "VALIDATION_ERROR"}
        ), 400

    with application.db_connect() as conn:
        before = {
            table: conn.execute(f"SELECT COUNT(1) FROM {table}").fetchone()[0]
            for table in (
                "transactions",
                "import_previews",
                "import_jobs",
                "imported_files",
                "stored_documents",
                "classification_history",
            )
        }
        for table in (
            "transaction_suggestions",
            "transaction_suggestion_state",
            "suggestion_jobs",
            "transaction_reconciliations",
            "transactions",
            "installment_plans",
            "import_jobs",
            "import_previews",
            "stored_documents",
            "account_file_coverage",
        ):
            conn.execute(f"DELETE FROM {table}")
        if scope == "all":
            conn.execute("DELETE FROM classification_history")
            conn.execute("DELETE FROM imported_files")
            if wipe_categories:
                conn.execute("DELETE FROM subcategories")
                conn.execute("DELETE FROM categories")
        else:
            conn.execute(
                "DELETE FROM imported_files WHERE file_type NOT IN ('xlsx-seed','pdf-seed')"
            )
        record_audit(
            application.current_user(),
            "system_reset",
            "system",
            detail=f"scope={scope}, wipe_categories={wipe_categories}, antes={before}",
            conn=conn,
        )
    local_files_removed = 0
    for runtime_dir in (application.UPLOADS, application.DOCS):
        try:
            local_files_removed += _clear_runtime_directory(
                runtime_dir, application.DATA
            )
        except OSError:
            logger.warning(
                "Falha ao limpar diretorio local apos reset: %s",
                runtime_dir,
                exc_info=True,
            )
    if scope == "all" and wipe_categories:
        application.seed()
    return jsonify(
        {
            "ok": True,
            "backup": backup_ref,
            "scope": scope,
            "wipe_categories": wipe_categories,
            "deleted": before,
            "local_entries_removed": local_files_removed,
        }
    )
