from __future__ import annotations

import datetime as dt
import base64
import csv
import hashlib
import io
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, send_from_directory
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo

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


def _csv_bytes(columns: list[str], rows: list[tuple]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


AUDIT_COLUMNS = [
    ("ID do lançamento", "transaction_id"),
    ("Chave técnica", "tx_key"),
    ("Data", "date"),
    ("Competência", "competence_month"),
    ("Descrição", "description"),
    ("Descrição normalizada", "description_norm"),
    ("Valor", "amount"),
    ("Tipo", "type"),
    ("Status", "status"),
    ("Conta", "account_name"),
    ("Tipo de conta", "account_type"),
    ("ID da conta", "account_id"),
    ("Livro/Centro", "ledger_name"),
    ("ID livro/centro", "ledger_id"),
    ("Categoria", "category_name"),
    ("ID categoria", "category_id"),
    ("Subcategoria", "subcategory_name"),
    ("ID subcategoria", "subcategory_id"),
    ("Parcela atual", "installment_current"),
    ("Total de parcelas", "installment_total"),
    ("Plano de parcelas", "installment_plan_id"),
    ("Valor do plano", "installment_plan_amount"),
    ("Parcelas no plano", "installment_plan_members"),
    ("Observações", "notes"),
    ("Sinalizadores", "flags"),
    ("Estabelecimento normalizado", "merchant_norm"),
    ("Método da transação", "transaction_method"),
    ("Contraparte", "counterparty_name"),
    ("Referência bancária", "bank_reference"),
    ("Bloqueado", "locked"),
    ("Classificado por", "classified_by"),
    ("Classificado em", "classified_at"),
    ("Categoria sugerida", "suggested_category_name"),
    ("ID categoria sugerida", "suggested_category_id"),
    ("Subcategoria sugerida", "suggested_subcategory_name"),
    ("ID subcategoria sugerida", "suggested_subcategory_id"),
    ("Probabilidade da sugestão", "match_probability"),
    ("Notas da sugestão", "match_notes"),
    ("ID vínculo histórico", "history_match_id"),
    ("Vínculo histórico confirmado", "history_match_confirmed"),
    ("ID histórico rejeitado", "history_match_rejected_id"),
    ("Pontuação de identidade", "identity_score"),
    ("Data histórica", "history_date"),
    ("Descrição histórica", "history_description"),
    ("Valor histórico", "history_amount"),
    ("Tipo histórico", "history_type"),
    ("Fonte histórica", "history_source_file_id"),
    ("Conta histórica", "history_account_name"),
    ("Categoria histórica", "history_category_name"),
    ("Subcategoria histórica", "history_subcategory_name"),
    ("ID conciliação", "reconciliation_id"),
    ("Papel na conciliação", "reconciliation_role"),
    ("Valor conciliado", "reconciliation_amount"),
    ("Conciliado por", "reconciliation_created_by"),
    ("Conciliado em", "reconciliation_created_at"),
    ("ID contraparte conciliada", "counterpart_id"),
    ("Data contraparte", "counterpart_date"),
    ("Descrição contraparte", "counterpart_description"),
    ("Valor contraparte", "counterpart_amount"),
    ("Tipo contraparte", "counterpart_type"),
    ("Conta contraparte", "counterpart_account_name"),
    ("ID lote de importação", "imported_file_id"),
    ("Arquivo de origem", "source_filename"),
    ("Tipo do arquivo", "source_file_type"),
    ("Hash SHA-1 do arquivo", "source_file_hash"),
    ("Banco detectado", "source_bank"),
    ("Ano do arquivo", "source_year"),
    ("Mês do arquivo", "source_month"),
    ("Natureza da fonte", "source_kind"),
    ("Importado em", "imported_at"),
    ("Linhas interpretadas", "source_total_parsed"),
    ("Linhas inseridas", "source_total_inserted"),
    ("Duplicadas no lote", "source_total_duplicates"),
    ("Erros no lote", "source_total_errors"),
    ("ID documento no cofre", "stored_document_id"),
    ("Documento no cofre", "stored_document_filename"),
    ("Competência no cofre", "stored_document_year_month"),
    ("Tamanho do documento (bytes)", "stored_document_size"),
    ("Documento guardado em", "stored_document_created_at"),
]


def _audit_transaction_rows(conn) -> list[dict]:
    cursor = conn.execute(
        """
        SELECT
          t.id AS transaction_id,t.tx_key,t.date,t.competence_month,t.description,
          t.description_norm,t.amount,t.type,t.status,t.account_id,a.name AS account_name,
          a.type AS account_type,t.ledger_id,l.name AS ledger_name,t.category_id,
          c.name AS category_name,t.subcategory_id,s.name AS subcategory_name,
          t.installment_current,t.installment_total,t.installment_plan_id,
          ip.installment_amount AS installment_plan_amount,
          (SELECT COUNT(1) FROM transactions tp WHERE tp.installment_plan_id=t.installment_plan_id)
            AS installment_plan_members,
          t.notes,t.flags,t.merchant_norm,t.transaction_method,t.counterparty_name,
          t.bank_reference,t.locked,t.classified_by,t.classified_at,
          t.suggested_category_id,sc.name AS suggested_category_name,
          t.suggested_subcategory_id,ss.name AS suggested_subcategory_name,
          t.match_probability,t.match_notes,t.history_match_id,t.history_match_confirmed,
          t.history_match_rejected_id,t.identity_score,hm.date AS history_date,
          hm.description AS history_description,hm.amount AS history_amount,
          hm.type AS history_type,hm.source_file_id AS history_source_file_id,
          ha.name AS history_account_name,hc.name AS history_category_name,
          hs.name AS history_subcategory_name,tr.id AS reconciliation_id,
          CASE WHEN tr.expense_transaction_id=t.id THEN 'despesa' WHEN tr.income_transaction_id=t.id THEN 'receita' ELSE '' END
            AS reconciliation_role,
          tr.amount AS reconciliation_amount,tr.created_by AS reconciliation_created_by,
          tr.created_at AS reconciliation_created_at,rt.id AS counterpart_id,
          rt.date AS counterpart_date,rt.description AS counterpart_description,
          rt.amount AS counterpart_amount,rt.type AS counterpart_type,
          ra.name AS counterpart_account_name,t.imported_file_id,
          f.filename AS source_filename,f.file_type AS source_file_type,
          f.file_hash AS source_file_hash,f.bank AS source_bank,f.year AS source_year,
          f.month AS source_month,f.source_kind,f.imported_at,
          f.total_parsed AS source_total_parsed,f.total_inserted AS source_total_inserted,
          f.total_duplicates AS source_total_duplicates,f.total_errors AS source_total_errors,
          sd.id AS stored_document_id,sd.filename AS stored_document_filename,
          sd.year_month AS stored_document_year_month,sd.size AS stored_document_size,
          sd.created_at AS stored_document_created_at
        FROM transactions t
        JOIN accounts a ON a.id=t.account_id
        LEFT JOIN ledgers l ON l.id=t.ledger_id
        LEFT JOIN categories c ON c.id=t.category_id
        LEFT JOIN subcategories s ON s.id=t.subcategory_id
        LEFT JOIN categories sc ON sc.id=t.suggested_category_id
        LEFT JOIN subcategories ss ON ss.id=t.suggested_subcategory_id
        LEFT JOIN installment_plans ip ON ip.id=t.installment_plan_id
        LEFT JOIN classification_history hm ON hm.id=t.history_match_id
        LEFT JOIN accounts ha ON ha.id=hm.account_id
        LEFT JOIN categories hc ON hc.id=hm.category_id
        LEFT JOIN subcategories hs ON hs.id=hm.subcategory_id
        LEFT JOIN transaction_reconciliations tr
          ON tr.expense_transaction_id=t.id OR tr.income_transaction_id=t.id
        LEFT JOIN transactions rt
          ON rt.id=CASE WHEN tr.expense_transaction_id=t.id THEN tr.income_transaction_id
                        ELSE tr.expense_transaction_id END
        LEFT JOIN accounts ra ON ra.id=rt.account_id
        LEFT JOIN imported_files f ON f.id=t.imported_file_id
        LEFT JOIN stored_documents sd ON sd.imported_file_id=f.id
        ORDER BY t.date,t.id
        """
    )
    columns = [item[0] for item in cursor.description]
    result: list[dict] = []
    seen: set[str] = set()
    for raw in cursor.fetchall():
        row = dict(zip(columns, tuple(raw)))
        if row["transaction_id"] in seen:
            continue
        seen.add(row["transaction_id"])
        result.append(row)
    return result


def _excel_audit_value(key: str, value):
    if value in (None, ""):
        return ""
    if key in {"locked", "history_match_confirmed"}:
        return "Sim" if value else "Não"
    if key in {"date", "history_date", "counterpart_date"} and isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return value
    if key in {"classified_at", "reconciliation_created_at", "imported_at", "stored_document_created_at"} and isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except ValueError:
            return value
    return value


def _audit_workbook(rows: list[dict], created_at: str) -> io.BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Lançamentos"
    sheet.sheet_view.showGridLines = False
    headers = [label for label, _ in AUDIT_COLUMNS]
    sheet.append(headers)
    for row in rows:
        values = []
        for _, key in AUDIT_COLUMNS:
            values.append(_excel_audit_value(key, row.get(key)))
        sheet.append(values)

    dark = "172033"
    light = "DCE6F1"
    white = "FFFFFF"
    thin = Side(style="thin", color="D7DCE5")
    header = sheet[1]
    for cell in header:
        cell.fill = PatternFill("solid", fgColor=dark)
        cell.font = Font(color=white, bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=thin)
    sheet.row_dimensions[1].height = 34
    sheet.freeze_panes = "E2"
    sheet.auto_filter.ref = sheet.dimensions
    if rows:
        table = Table(displayName="LancamentosAuditoria", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
            showRowStripes=True, showColumnStripes=False,
        )
        sheet.add_table(table)

    widths = {
        "Data": 12, "Competência": 13, "Descrição": 38, "Descrição normalizada": 32,
        "Valor": 15, "Conta": 22, "Categoria": 22, "Subcategoria": 24,
        "Observações": 32, "Notas da sugestão": 34, "Descrição histórica": 34,
        "Descrição contraparte": 34, "Arquivo de origem": 36, "Documento no cofre": 36,
    }
    for index, label in enumerate(headers, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = widths.get(label, 20)
    currency_headers = {"Valor", "Valor do plano", "Valor histórico", "Valor conciliado", "Valor contraparte"}
    date_headers = {"Data", "Data histórica", "Data contraparte"}
    datetime_headers = {"Classificado em", "Conciliado em", "Importado em", "Documento guardado em"}
    for index, label in enumerate(headers, start=1):
        column = sheet.cell(1, index).column_letter
        if label in currency_headers:
            for cell in sheet[column][1:]:
                cell.number_format = 'R$ #,##0.00;[Red]-R$ #,##0.00'
        elif label in date_headers:
            for cell in sheet[column][1:]:
                cell.number_format = "dd/mm/yyyy"
        elif label in datetime_headers:
            for cell in sheet[column][1:]:
                cell.number_format = "dd/mm/yyyy hh:mm:ss"

    status_col = headers.index("Status") + 1
    status_letter = sheet.cell(1, status_col).column_letter
    if rows:
        status_range = f"{status_letter}2:{status_letter}{sheet.max_row}"
        sheet.conditional_formatting.add(
            status_range,
            FormulaRule(formula=[f'{status_letter}2="pending"'], fill=PatternFill("solid", fgColor="FFF2CC")),
        )
        sheet.conditional_formatting.add(
            status_range,
            FormulaRule(formula=[f'{status_letter}2="reconciled"'], fill=PatternFill("solid", fgColor="E2F0D9")),
        )

    summary = workbook.create_sheet("Resumo")
    summary.sheet_view.showGridLines = False
    summary.append(["Auditoria de lançamentos", None])
    summary.append(["Gerado em (UTC)", created_at])
    summary.append(["Total de lançamentos", len(rows)])
    summary.append(["Total de receitas", sum(float(row["amount"] or 0) for row in rows if row["type"] == "income")])
    summary.append(["Total de despesas", sum(float(row["amount"] or 0) for row in rows if row["type"] == "expense")])
    summary.append(["Pendentes", sum(row["status"] == "pending" for row in rows)])
    summary.append(["Com categoria", sum(bool(row.get("category_id")) for row in rows)])
    summary.append(["Com vínculo histórico", sum(bool(row.get("history_match_id")) for row in rows)])
    summary.append(["Com documento de origem", sum(bool(row.get("stored_document_id")) for row in rows)])
    summary.merge_cells("A1:B1")
    summary["A1"].fill = PatternFill("solid", fgColor=dark)
    summary["A1"].font = Font(color=white, bold=True, size=14)
    summary["A1"].alignment = Alignment(horizontal="left")
    summary.column_dimensions["A"].width = 32
    summary.column_dimensions["B"].width = 28
    for cell in summary["A"][1:]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=light)
    for cell in (summary["B4"], summary["B5"]):
        cell.number_format = 'R$ #,##0.00;[Red]-R$ #,##0.00'

    dictionary = workbook.create_sheet("Dicionário")
    dictionary.sheet_view.showGridLines = False
    dictionary.append(["Coluna", "Campo técnico", "Grupo"])
    groups = [
        (0, 32, "Lançamento e classificação"),
        (32, 38, "Sugestões"),
        (38, 50, "Base histórica"),
        (50, 61, "Conciliação"),
        (61, 79, "Documento e lote de origem"),
    ]
    for idx, (label, key) in enumerate(AUDIT_COLUMNS):
        group = next(name for start, end, name in groups if start <= idx < end)
        dictionary.append([label, key, group])
    for cell in dictionary[1]:
        cell.fill = PatternFill("solid", fgColor=dark)
        cell.font = Font(color=white, bold=True)
    dictionary.freeze_panes = "A2"
    dictionary.auto_filter.ref = dictionary.dimensions
    dictionary.column_dimensions["A"].width = 38
    dictionary.column_dimensions["B"].width = 34
    dictionary.column_dimensions["C"].width = 30
    workbook.calculation.fullCalcOnLoad = True
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


@bp.route("/api/v1/system/audit-export")
def system_audit_export():
    """Exporta uma linha por lancamento com todos os vinculos de auditoria."""
    application = _application()
    forbidden = application.require_admin()
    if forbidden:
        return forbidden
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with application.db_connect() as conn:
        if IS_POSTGRES:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = _audit_transaction_rows(conn)
    workbook = _audit_workbook(rows, created_at)
    filename = f"auditoria-lancamentos-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"
    return send_file(
        workbook,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@bp.route("/api/v1/system/audit-snapshot")
def system_audit_snapshot():
    """Exporta somente dados necessarios para auditoria financeira."""
    application = _application()
    forbidden = application.require_admin()
    if forbidden:
        return forbidden

    table_names = (
        "accounts",
        "account_file_coverage",
        "imported_files",
        "maintenance_log",
        "transaction_reconciliations",
        "transactions",
    )
    exported: dict[str, tuple[list[str], list[tuple]]] = {}
    stored_rows: list[tuple] = []
    stored_columns = [
        "id", "account_name", "year_month", "filename", "size",
        "content_sha1", "created_at", "imported_file_id",
    ]
    with application.db_connect() as conn:
        if IS_POSTGRES:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table in table_names:
            cursor = conn.execute(f"SELECT * FROM {table}")
            columns = [item[0] for item in cursor.description]
            exported[table] = (columns, [tuple(row) for row in cursor.fetchall()])
        docs = conn.execute(
            """
            SELECT id,account_name,year_month,filename,size,content_b64,
                   created_at,imported_file_id
            FROM stored_documents
            """
        ).fetchall()
        for row in docs:
            try:
                content_hash = hashlib.sha1(base64.b64decode(row[5])).hexdigest()
            except Exception:
                content_hash = "INVALID_BASE64"
            stored_rows.append(
                (row[0], row[1], row[2], row[3], row[4], content_hash,
                 row[6], row[7])
            )

    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    archive = io.BytesIO()
    manifest = {
        "format": "conciliador-audit-export-v1",
        "created_at": created_at,
        "database": "postgres" if IS_POSTGRES else "sqlite",
        "tables": {name: len(rows) for name, (_, rows) in exported.items()},
    }
    manifest["tables"]["stored_documents"] = len(stored_rows)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for name, (columns, rows) in exported.items():
            bundle.writestr(f"tables/{name}.csv", _csv_bytes(columns, rows))
        bundle.writestr(
            "tables/stored_documents.csv",
            _csv_bytes(stored_columns, stored_rows),
        )
    archive.seek(0)
    filename = f"production-audit-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return send_file(
        archive,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


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
