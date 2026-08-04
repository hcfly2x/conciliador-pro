from __future__ import annotations

import base64
import calendar
import csv
import datetime as dt
import difflib
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import time
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import os
import threading

from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from blueprints import (
    ALL_BLUEPRINTS,
    accounts_bp,
    auth_bp,
    coverage_bp,
    history_links_bp,
    imports_bp,
    reconciliations_bp,
    reports_bp,
    suggestions_bp,
    system_bp,
    transactions_bp,
)

from parsers.engine import ImportResult, run_import_pipeline

from db import DB_PATH, PoolOverloadError, db_connect, IS_POSTGRES
import auth as auth_mod
from auth import record_audit, ROLE_ADMIN
from migrations import run_migrations

HISTORY_LINK_CANDIDATE_THRESHOLD = 96.0
BATCH_DESCRIPTION_SIMILARITY_THRESHOLD = 75.0
UNKNOWN_HISTORICAL_ACCOUNT_LABELS = {"antigo", "planilha passada", "primeira planilha"}
logger = logging.getLogger(__name__)

SENTRY_DSN = (os.environ.get("SENTRY_DSN") or "").strip()
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        environment=os.environ.get("SENTRY_ENVIRONMENT")
        or ("production" if IS_POSTGRES else "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE") or "0"),
        send_default_pii=False,
    )

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CONCILIADOR_DATA_DIR") or BASE / "data").resolve()
UPLOADS = DATA / "uploads"
DOCS = DATA / "documents"
TOOLS = BASE.parent / "tools"
DB = DB_PATH
for d in (DATA, UPLOADS, DOCS):
    d.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = (
    int(os.environ.get("MAX_UPLOAD_MB") or "30") * 1024 * 1024
)
WORKER_MODE = (
    (os.environ.get("WORKER_MODE") or ("process" if IS_POSTGRES else "inline"))
    .strip()
    .lower()
)
if WORKER_MODE not in {"inline", "process"}:
    raise RuntimeError("WORKER_MODE deve ser 'inline' ou 'process'")
IS_WORKER_PROCESS = (os.environ.get("WORKER_PROCESS") or "").strip().lower() in {
    "1",
    "true",
    "yes",
}
_default_trusted_proxies = "1" if IS_POSTGRES else "0"
TRUSTED_PROXY_COUNT = int(
    os.environ.get("TRUSTED_PROXY_COUNT") or _default_trusted_proxies
)
if TRUSTED_PROXY_COUNT < 0:
    raise RuntimeError("TRUSTED_PROXY_COUNT nao pode ser negativo")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=TRUSTED_PROXY_COUNT)
ALLOWED_IMPORT_EXTENSIONS = {".csv", ".xls", ".xlsx", ".pdf"}

# ---------------------------------------------------------------------------
# CORS + Autenticacao (versao web)
# ---------------------------------------------------------------------------
_cors_setting = os.environ.get("CORS_ORIGINS")
if _cors_setting is None:
    CORS_ORIGINS = (
        [] if IS_POSTGRES else ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
else:
    CORS_ORIGINS = [
        o.strip().rstrip("/") for o in _cors_setting.split(",") if o.strip()
    ]
if IS_POSTGRES and "*" in CORS_ORIGINS:
    raise RuntimeError(
        "CORS_ORIGINS='*' nao e permitido com PostgreSQL/ambiente hospedado"
    )
PUBLIC_PATHS = {"/api/v1/health", "/api/v1/auth/login"}


def allow_collab_write(view):
    view._allow_collab_write = True
    return view


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify(
        {"detail": "Arquivo excede o limite permitido", "code": "FILE_TOO_LARGE"}
    ), 413


@app.errorhandler(PoolOverloadError)
def database_pool_overloaded(_error):
    return jsonify(
        {
            "detail": "Banco temporariamente sobrecarregado. Tente novamente em instantes.",
            "code": "DATABASE_OVERLOADED",
        }
    ), 503


def validate_import_filename(filename: str):
    if Path(filename or "").suffix.lower() not in ALLOWED_IMPORT_EXTENSIONS:
        return jsonify(
            {
                "detail": "Formato nao suportado. Use CSV, XLS, XLSX ou PDF.",
                "code": "UNSUPPORTED_FILE_TYPE",
            }
        ), 415
    return None


@app.after_request
def _apply_cors(resp):
    origin = request.headers.get("Origin")
    if origin and ("*" in CORS_ORIGINS or origin in CORS_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = (
            "GET,POST,PUT,PATCH,DELETE,OPTIONS"
        )
        resp.headers["Access-Control-Max-Age"] = "86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    duration_ms = round(
        (time.perf_counter() - getattr(g, "request_started_at", time.perf_counter()))
        * 1000,
        2,
    )
    user = getattr(g, "user", None) or {}
    request_log = {
        "event": "http_request",
        "method": request.method,
        "path": request.path,
        "status": resp.status_code,
        "duration_ms": duration_ms,
        "user": user.get("username") or "anonymous",
    }
    if IS_POSTGRES:
        logger.info(json.dumps(request_log, ensure_ascii=False, separators=(",", ":")))
    else:
        logger.info(
            "%s %s -> %s em %.2fms (%s)",
            request.method,
            request.path,
            resp.status_code,
            duration_ms,
            request_log["user"],
        )
    return resp


@app.before_request
def _auth_guard():
    g.request_started_at = time.perf_counter()
    if request.method == "OPTIONS":
        return None
    path = request.path or ""
    if path in PUBLIC_PATHS:
        return None
    if auth_mod.AUTH_DISABLED:
        g.user = {"id": None, "username": "local", "role": ROLE_ADMIN}
        return None
    if path.startswith("/ui/"):
        # Paginas-ferramenta legadas sao apenas para uso local (AUTH_DISABLED=1).
        return jsonify(
            {"detail": "Indisponivel no modo hosted", "code": "NOT_AVAILABLE"}
        ), 404
    token = (request.headers.get("Authorization") or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    user = auth_mod.user_for_token(token)
    if not user:
        return jsonify({"detail": "Nao autenticado", "code": "UNAUTHORIZED"}), 401
    g.user = user
    if user["role"] != ROLE_ADMIN and request.method not in ("GET", "HEAD"):
        view = app.view_functions.get(request.endpoint or "")
        if not getattr(view, "_allow_collab_write", False):
            return jsonify(
                {
                    "detail": "Apenas administrador pode executar esta acao",
                    "code": "FORBIDDEN",
                }
            ), 403
    return None


def current_user() -> dict:
    return getattr(g, "user", None) or {
        "id": None,
        "username": "sistema",
        "role": ROLE_ADMIN,
    }


def require_admin():
    """Retorna uma resposta de erro se o usuario atual nao for admin, senao None."""
    user = current_user()
    if user.get("role") != ROLE_ADMIN:
        return jsonify(
            {
                "detail": "Apenas administrador pode executar esta acao",
                "code": "FORBIDDEN",
            }
        ), 403
    return None


@dataclass
class ParsedTx:
    date: str
    description: str
    amount: float
    tx_type: str
    installment_current: int | None = None
    installment_total: int | None = None


def strip_accents(text: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(c)
    )


def norm_text(text: str) -> str:
    cleaned = strip_accents((text or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_shadow_metadata(
    description: str,
    account_type: str = "",
    installment_current: int | None = None,
    installment_total: int | None = None,
) -> dict[str, Any]:
    """Extrai campos auxiliares sem alterar descricao, deduplicacao ou ranking."""
    normalized = norm_text(description)
    method = "other"
    for candidate, pattern in (
        ("pix", r"\bpix\b"),
        ("boleto", r"\bboleto\b"),
        ("ted", r"\bted\b"),
        ("doc", r"\bdoc\b"),
        ("automatic_debit", r"\bdebito\s+aut(?:omatico)?\b"),
        ("debit_card", r"\b(?:cartao\s+)?debito\b"),
        ("cashback", r"\bcashback\b"),
        ("refund", r"\b(?:estorno|reembolso|devolucao)\b"),
        ("fee", r"\b(?:tarifa|taxa|iof)\b"),
    ):
        if re.search(pattern, normalized):
            method = candidate
            break
    if method == "other" and account_type == "credit_card":
        method = "credit_card"
    elif method == "other" and re.search(r"\b(?:transferencia|transf)\b", normalized):
        method = "bank_transfer"
    reference = re.search(
        r"\b(?:id|e2e|ref|documento|controle)\s*([a-z0-9-]{6,})\b", normalized
    )
    merchant = re.sub(r"\b\d{1,2}(?:\s*/\s*|\s+)\d{1,2}\b", " ", normalized)
    merchant = re.sub(
        r"\b(?:pix|enviado|recebido|transferencia|transf|compra|cartao|credito|debito|boleto|pagamento|pgto)\b",
        " ",
        merchant,
    )
    merchant = re.sub(
        r"\b(?:id|e2e|ref|documento|controle)\s*[a-z0-9-]{6,}\b|\b\d{6,}\b",
        " ",
        merchant,
    )
    merchant_norm = " ".join(merchant.split()).strip()
    return {
        "merchant_norm": merchant_norm,
        "transaction_method": method,
        "counterparty_name": merchant_norm,
        "bank_reference": reference.group(1) if reference else "",
        "shadow_installment_current": installment_current,
        "shadow_installment_total": installment_total,
    }


def store_shadow_metadata(
    conn,
    table: str,
    row_id: str,
    description: str,
    account_type: str = "",
    installment_current: int | None = None,
    installment_total: int | None = None,
) -> None:
    if table not in {"transactions", "classification_history"}:
        raise ValueError("Tabela invalida para metadados auxiliares")
    meta = extract_shadow_metadata(
        description, account_type, installment_current, installment_total
    )
    conn.execute(
        f"UPDATE {table} SET merchant_norm=?,transaction_method=?,counterparty_name=?,bank_reference=? WHERE id=?",
        (
            meta["merchant_norm"],
            meta["transaction_method"],
            meta["counterparty_name"],
            meta["bank_reference"],
            row_id,
        ),
    )


def clean_path_part(text: str) -> str:
    cleaned = strip_accents(text or "").upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "SEM_NOME"


def clean_archive_filename(filename: str) -> str:
    path = Path(filename or "arquivo")
    stem = clean_path_part(path.stem)
    suffix = path.suffix.lower()
    return f"{stem}{suffix}" if suffix else stem


def account_folder_name(account_name: str) -> str:
    return clean_path_part(account_name)


def project_relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE.parent.resolve()))
    except ValueError:
        return str(path.resolve())


def archive_target_path(source: Path, account_name: str, txs: list[Any]) -> Path:
    if txs:
        from collections import Counter

        month_counts = Counter(
            (t.date[:7] or "").replace("-", "/")
            for t in txs
            if getattr(t, "date", "") and len(t.date) >= 7
        )
        if month_counts:
            ref = month_counts.most_common(1)[0][0]
            year, month = ref[:4], ref[5:7]
        else:
            year, month = txs[0].date[:4], txs[0].date[5:7]
    else:
        year, month = dt.datetime.now().strftime("%Y"), dt.datetime.now().strftime("%m")
    target_dir = DOCS / year / month / account_folder_name(account_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / clean_archive_filename(source.name)
    if target.exists():
        target = (
            target_dir
            / f"{target.stem}-{int(dt.datetime.now().timestamp())}{target.suffix}"
        )
    return target


def store_document_in_db(
    source: Path,
    account_name: str,
    year_month: str,
    filename: str,
    imported_file_id: str = "",
    conn=None,
) -> str:
    """Guarda o conteudo do arquivo no banco (base64) para sobreviver a redeploys."""
    try:
        content = base64.b64encode(source.read_bytes()).decode("ascii")
        size = source.stat().st_size
    except Exception as exc:
        raise RuntimeError(
            f"Nao foi possivel preservar o documento original: {exc}"
        ) from exc
    doc_id = str(uuid.uuid4())

    def persist(active_conn):
        dup = active_conn.execute(
            "SELECT id FROM stored_documents WHERE account_name=? AND year_month=? AND filename=? LIMIT 1",
            (account_name, year_month, filename),
        ).fetchone()
        if dup:
            active_conn.execute(
                "UPDATE stored_documents SET content_b64=?, size=?, imported_file_id=? WHERE id=?",
                (content, size, imported_file_id or None, dup[0]),
            )
            return dup[0]
        active_conn.execute(
            "INSERT INTO stored_documents(id,account_name,year_month,filename,size,content_b64,created_at,imported_file_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                doc_id,
                account_name,
                year_month,
                filename,
                size,
                content,
                dt.datetime.now().isoformat(timespec="seconds"),
                imported_file_id or None,
            ),
        )
        return doc_id

    if conn is not None:
        return persist(conn)
    with db_connect() as own_conn:
        return persist(own_conn)


def archive_import_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return
    shutil.copy2(source, target)
    try:
        source.unlink()
    except FileNotFoundError:
        pass


def parse_installment(value: Any) -> tuple[int | None, int | None]:
    raw = str(value or "").strip()
    if not raw or raw in {"-", "--"}:
        return None, None
    text = norm_text(raw)
    patterns = [
        r"\b(\d{1,2})\s+de\s+(\d{1,2})\b",
        r"\b(\d{1,2})\s*/\s*(\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if 1 <= current <= total:
                return current, total
    return None, None


def installment_label(current: int | None, total: int | None) -> str | None:
    if current and total:
        return f"Parcela {current} de {total}"
    return None


def merchant_signature(text: str) -> str:
    n = norm_text(text)
    n = re.sub(
        r"\b(pix|enviado|recebido|internet|banking|cartao|debito|credito|pagamento|transferencia|transferencias)\b",
        " ",
        n,
    )
    n = re.sub(r"\b\d+\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    parts = n.split(" ")
    return " ".join(parts[:3]).strip()


def token_similarity(a: str, b: str) -> float:
    return description_similarity(a, b)


def first_tokens(text: str, count: int) -> str:
    return " ".join(norm_text(text).split()[:count])


def meaningful_tokens(text: str) -> set[str]:
    stop = {
        "a",
        "o",
        "os",
        "as",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "no",
        "na",
        "nos",
        "nas",
    }
    return {
        token
        for token in norm_text(text).split()
        if len(token) >= 3 and token not in stop
    }


GENERIC_MATCH_TOKENS = {
    "posto",
    "mercado",
    "supermercado",
    "uber",
    "amazon",
    "ifood",
    "drogaria",
    "farmacia",
    "farm",
    "pagamento",
    "compra",
    "cartao",
    "debito",
    "credito",
    "visa",
    "electron",
    "pix",
    "enviado",
    "recebido",
    "internet",
    "banking",
    "transferencia",
    "mp",
    "mercadopago",
    "auto",
}


def descriptions_have_common_parts(a: str, b: str) -> bool:
    na = norm_text(a)
    nb = norm_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
    common = meaningful_tokens(na) & meaningful_tokens(nb)
    if not common:
        return False
    return bool(common - GENERIC_MATCH_TOKENS)


def description_similarity(a: str, b: str) -> float:
    def canonicalize(text: str) -> str:
        source = str(text or "").lower()

        def installment_replacement(match: re.Match[str]) -> str:
            current = int(match.group(1))
            total = int(match.group(2))
            if 1 <= current <= total:
                return f" parcela {current} {total} "
            return match.group(0)

        source = re.sub(
            r"\bparcela\s*0*(\d{1,2})\s*(?:de|/)\s*0*(\d{1,2})\b",
            installment_replacement,
            source,
        )
        source = re.sub(
            r"\b0*(\d{1,2})\s*/\s*0*(\d{1,2})\b",
            installment_replacement,
            source,
        )
        normalized = norm_text(source)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    na = canonicalize(a)
    nb = canonicalize(b)
    installments_a = re.findall(r"\bparcela\s+(\d{1,2})\s+(\d{1,2})\b", na)
    installments_b = re.findall(r"\bparcela\s+(\d{1,2})\s+(\d{1,2})\b", nb)
    for current, total in installments_a:
        marker = f"parcela {int(current)} {int(total)}"
        if marker not in nb:
            nb = re.sub(rf"\b0*{int(current)}\s+0*{int(total)}\b", marker, nb)
    for current, total in installments_b:
        marker = f"parcela {int(current)} {int(total)}"
        if marker not in na:
            na = re.sub(rf"\b0*{int(current)}\s+0*{int(total)}\b", marker, na)
    tokens_a = na.split()
    tokens_b = nb.split()
    if not tokens_a or not tokens_b:
        return 0.0
    if na == nb:
        return 1.0

    counts_a = Counter(tokens_a)
    counts_b = Counter(tokens_b)
    common_count = sum((counts_a & counts_b).values())
    word_overlap = (2 * common_count) / (len(tokens_a) + len(tokens_b))
    word_order = difflib.SequenceMatcher(None, tokens_a, tokens_b).ratio()
    phrase_ratio = difflib.SequenceMatcher(None, na, nb).ratio()

    merchant_a = " ".join(
        token
        for token in merchant_signature(na).split()
        if token != "parcela" and not token.isdigit()
    )
    merchant_b = " ".join(
        token
        for token in merchant_signature(nb).split()
        if token != "parcela" and not token.isdigit()
    )
    merchant_ratio = (
        difflib.SequenceMatcher(None, merchant_a, merchant_b).ratio()
        if merchant_a and merchant_b
        else 0.0
    )
    score = (
        (0.45 * word_overlap)
        + (0.25 * word_order)
        + (0.20 * phrase_ratio)
        + (0.10 * merchant_ratio)
    )
    return round(max(0.0, min(1.0, score)), 4)


def date_similarity(d1: str, d2: str) -> float:
    try:
        a = dt.date.fromisoformat(d1)
        b = dt.date.fromisoformat(d2)
    except (TypeError, ValueError):
        return 0.0
    delta = abs((a - b).days)
    if delta <= 2:
        return round(max(0.0, 1.0 - (delta * 0.15)), 4)
    return 0.0


def amount_similarity(a: float, b: float) -> float:
    aa = abs(float(a or 0))
    bb = abs(float(b or 0))
    diff = abs(aa - bb)
    if diff <= 0.01:
        return 1.0
    if diff <= 1.0:
        return round(max(0.50, 1.0 - (diff / 2.0)), 4)
    return 0.0


def amount_range_fit(tx_amount: float, category_amounts: list[float]) -> float:
    amounts = [abs(float(v or 0)) for v in category_amounts if v is not None]
    if not amounts:
        return 0.5
    tx_amount = abs(float(tx_amount or 0))
    mn = min(amounts)
    mx = max(amounts)
    if mn <= tx_amount <= mx:
        return 1.0
    if tx_amount < mn:
        rel = (mn - tx_amount) / max(mn, 1.0)
    else:
        rel = (tx_amount - mx) / max(mx, 1.0)
    if rel <= 0.20:
        return 0.70
    if rel <= 0.50:
        return 0.40
    if rel <= 1.50:
        return 0.15
    return 0.05


def recurring_pattern_score(tx_date: str, category_dates: list[str]) -> float:
    try:
        tx_day = dt.date.fromisoformat(tx_date).day
    except (TypeError, ValueError):
        return 0.4
    days: list[int] = []
    for value in category_dates:
        try:
            days.append(dt.date.fromisoformat(value).day)
        except (TypeError, ValueError):
            continue
    if len(days) < 3:
        return 0.4
    near = sum(
        1 for day in days if abs(day - tx_day) <= 3 or abs(day - tx_day) >= 28
    ) / len(days)
    if near >= 0.50:
        return 1.0
    if near >= 0.25:
        return 0.6
    return 0.4


def account_similarity(tx_account_id: str | None, ref_account_id: str | None) -> float:
    if not tx_account_id:
        return 0.5
    if not ref_account_id:
        return 0.5
    return 1.0 if tx_account_id == ref_account_id else 0.0


def weighted_match_score(
    tx_date: str,
    tx_desc: str,
    tx_amount: float,
    tx_account_id: str | None,
    ref_date: str,
    ref_desc: str,
    ref_amount: float,
    ref_account_id: str | None,
) -> float:
    d_score = date_similarity(tx_date, ref_date)
    desc_score = token_similarity(tx_desc, ref_desc)
    amt_score = amount_similarity(tx_amount, ref_amount)
    # Conta/cartao nao participa do vinculo historico: a base antiga usava contas
    # como subdivisoes pessoais, entao comparar conta criaria falsos negativos.
    score = (0.36 * d_score) + (0.34 * desc_score) + (0.30 * amt_score)
    return max(0.0, min(1.0, score))


def find_identity_match(
    conn: sqlite3.Connection,
    tx: dict[str, Any],
    hist_cache: dict[str, list[tuple[Any, ...]]] | None = None,
) -> dict[str, Any] | None:
    tx_type = tx.get("type") or ""
    tx_date = tx.get("date") or ""
    tx_desc = tx.get("description") or tx.get("description_norm") or ""
    tx_amount = abs(float(tx.get("amount") or 0))
    tx_account_id = tx.get("account_id")
    if tx_amount < 2.0:
        return None
    if hist_cache is not None:
        rows = hist_cache.get(tx_type, [])
    else:
        rows = conn.execute(
            """
            SELECT id,date,description_norm,ABS(amount),account_id,category_id,subcategory_id
            FROM classification_history
            WHERE type=?
            """,
            (tx_type,),
        ).fetchall()
    best: dict[str, Any] | None = None
    try:
        installment_current = int(tx.get("installment_current") or 0)
        installment_total = int(tx.get("installment_total") or 0)
    except (TypeError, ValueError):
        installment_current = installment_total = 0
    installment_match = (
        installment_current > 0
        and installment_total > 1
        and installment_current <= installment_total
    )
    installment_total_amount = (
        round(tx_amount * installment_total, 2) if installment_match else 0.0
    )
    installment_first_date = (
        shift_months(tx_date, -(installment_current - 1)) if installment_match else ""
    )
    try:
        tx_date_value = dt.date.fromisoformat(tx_date) if tx_date else None
    except (TypeError, ValueError):
        tx_date_value = None
    installment_date_options: list[tuple[str, dt.date]] = []
    if installment_match:
        for candidate_date in (tx_date, installment_first_date):
            if not candidate_date:
                continue
            try:
                installment_date_options.append(
                    (candidate_date, dt.date.fromisoformat(candidate_date))
                )
            except (TypeError, ValueError):
                continue
    for row in rows:
        history_amount = float(row[3] or 0)
        amount_normal = abs(tx_amount - history_amount) <= 1.0
        installment_amount_normal = bool(
            installment_match
            and abs(installment_total_amount - history_amount)
            <= max(1.0, installment_total * 0.02)
        )
        if not amount_normal and not installment_amount_normal:
            continue
        description_normal = descriptions_have_common_parts(tx_desc, row[2] or "")
        if not description_normal:
            continue
        try:
            history_date_value = dt.date.fromisoformat(row[1]) if row[1] else None
        except (TypeError, ValueError):
            history_date_value = None
        date_normal = bool(
            tx_date_value
            and history_date_value
            and abs((tx_date_value - history_date_value).days) <= 2
        )
        installment_date_normal = False
        installment_comparison_date = installment_first_date
        if installment_amount_normal and history_date_value and installment_date_options:
            installment_comparison_date, closest_installment_date = min(
                installment_date_options,
                key=lambda value: abs((value[1] - history_date_value).days),
            )
            installment_date_normal = (
                abs((closest_installment_date - history_date_value).days) <= 7
            )
        aggregate_installment = (
            installment_date_normal and installment_amount_normal and description_normal
        )
        # Vinculo historico representa a mesma transacao da base antiga.
        # Data, valor e descricao precisam estar dentro da normalidade; quando
        # apenas dois batem, o resultado costuma virar sugestao de categoria,
        # nao identidade.
        if not (
            (date_normal and amount_normal and description_normal)
            or aggregate_installment
        ):
            continue
        desc_score = token_similarity(tx_desc, row[2] or "")
        if description_normal and desc_score < 0.50:
            desc_score = 0.50
        comparison_date = (
            installment_comparison_date if aggregate_installment else tx_date
        )
        comparison_amount = (
            installment_total_amount if aggregate_installment else tx_amount
        )
        base = weighted_match_score(
            comparison_date,
            tx_desc,
            comparison_amount,
            tx_account_id,
            row[1] or "",
            row[2] or "",
            float(row[3] or 0),
            row[4],
        )
        amount_exact = abs(comparison_amount - history_amount) < 0.01
        date_exact = bool(comparison_date and row[1] and comparison_date == row[1])
        score = base
        if amount_exact:
            score += 0.14
        if date_exact:
            score += 0.12
        score = round(min(score, 1.0) * 100, 2)
        if best is None or score > best["identity_score"]:
            best = {
                "history_match_id": row[0],
                "identity_score": score,
                "category_id": row[5],
                "subcategory_id": row[6],
                "match_basis": "installment_total"
                if aggregate_installment
                else "standard",
                "comparison_date": comparison_date,
                "comparison_amount": comparison_amount,
                "description_similarity": round(desc_score * 100, 1),
                "date_difference_days": abs(
                    (
                        dt.date.fromisoformat(comparison_date)
                        - dt.date.fromisoformat(row[1])
                    ).days
                ),
                "amount_difference": round(abs(comparison_amount - history_amount), 2),
            }
    return best


def shift_months(value: str, months: int) -> str:
    try:
        source = dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    month_index = source.year * 12 + source.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(source.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day).isoformat()


def historical_match_factors(
    tx_date: str,
    tx_amount: float,
    tx_description: str,
    history_date: str | None,
    history_amount: float | None,
    history_description: str | None,
    installment_current: int | None = None,
    installment_total: int | None = None,
) -> dict[str, Any]:
    current = int(installment_current or 0)
    total = int(installment_total or 0)
    can_be_aggregate = current > 0 and total > 1 and current <= total
    installment_first_date = (
        shift_months(tx_date, -(current - 1)) if can_be_aggregate else ""
    )
    standard_amount = abs(float(tx_amount or 0))
    aggregate_amount = standard_amount * total if can_be_aggregate else standard_amount
    history_amount_abs = abs(float(history_amount or 0))
    try:
        history_date_value = dt.date.fromisoformat(history_date or "")
        date_options = [value for value in (tx_date, installment_first_date) if value]
        aggregate_date = min(
            date_options,
            key=lambda value: abs(
                (dt.date.fromisoformat(value) - history_date_value).days
            ),
        )
        aggregate_date_difference = abs(
            (dt.date.fromisoformat(aggregate_date) - history_date_value).days
        )
    except (TypeError, ValueError):
        aggregate_date = installment_first_date
        aggregate_date_difference = 999999
    aggregate_installment = bool(
        can_be_aggregate
        and abs(aggregate_amount - history_amount_abs)
        < abs(standard_amount - history_amount_abs)
        and aggregate_date_difference <= 7
    )
    comparison_date = aggregate_date if aggregate_installment else tx_date
    comparison_amount = aggregate_amount if aggregate_installment else standard_amount
    try:
        date_difference = abs(
            (
                dt.date.fromisoformat(comparison_date)
                - dt.date.fromisoformat(history_date or "")
            ).days
        )
    except (TypeError, ValueError):
        date_difference = None
    amount_difference = round(
        abs(comparison_amount - abs(float(history_amount or 0))), 2
    )
    description_similarity = round(
        token_similarity(
            norm_text(tx_description), norm_text(history_description or "")
        )
        * 100,
        1,
    )
    return {
        "match_date_difference_days": date_difference,
        "match_amount_difference": amount_difference,
        "match_description_similarity": description_similarity,
        "match_basis": "installment_total" if aggregate_installment else "standard",
        "match_comparison_date": comparison_date,
        "match_comparison_amount": round(comparison_amount, 2),
    }


def build_scored_evidence(
    conn: sqlite3.Connection,
    tx: dict[str, Any],
    exclude_tx_id: str | None = None,
    include_transactions: bool = False,
    include_history: bool = True,
    evidence_rows: list[tuple[Any, ...]] | None = None,
) -> list[dict[str, Any]]:
    """
    Usa o melhor match por categoria, com bonus pequeno de frequencia.
    Isso evita que categorias muito frequentes dominem por volume acumulado.
    """
    import math

    tx_date = tx.get("date") or ""
    tx_desc = tx.get("description_norm") or norm_text(tx.get("description") or "")
    tx_amount = abs(float(tx.get("amount") or 0))
    tx_type = tx.get("type") or ""
    tx_account_id = tx.get("account_id")

    all_rows: list[tuple[Any, ...]] = list(evidence_rows or [])
    if evidence_rows is None and include_transactions:
        all_rows += conn.execute(
            """
            SELECT t.category_id, c.name, t.subcategory_id, IFNULL(s.name,''),
                   t.date, t.description_norm, ABS(t.amount), t.account_id, t.notes, 'transaction'
            FROM transactions t
            LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN subcategories s ON s.id=t.subcategory_id
            WHERE t.category_id IS NOT NULL
              AND t.type=?
              AND (? IS NULL OR t.id<>?)
            """,
            (tx_type, exclude_tx_id, exclude_tx_id),
        ).fetchall()

    if evidence_rows is None and include_history:
        history_filter = (
            "AND h.source_file_id NOT LIKE 'manual:%'" if include_transactions else ""
        )
        all_rows += conn.execute(
            f"""
            SELECT h.category_id, c.name, h.subcategory_id, IFNULL(s.name,''),
                   h.date, h.description_norm, ABS(h.amount), h.account_id, '', 'history'
            FROM classification_history h
            LEFT JOIN categories c ON c.id=h.category_id
            LEFT JOIN subcategories s ON s.id=h.subcategory_id
            WHERE h.type=?
              {history_filter}
            """,
            (tx_type,),
        ).fetchall()

    if not all_rows:
        return []

    relevant: list[tuple[float, tuple[Any, ...]]] = []
    for row in all_rows:
        desc_score = token_similarity(tx_desc, row[5] or "")
        if desc_score >= 0.15:
            relevant.append((desc_score, row))

    if not relevant:
        return []

    cat_amounts: dict[str, list[float]] = {}
    cat_dates: dict[str, list[str]] = {}
    for _, row in relevant:
        cat_id = row[0]
        if not cat_id:
            continue
        cat_amounts.setdefault(cat_id, []).append(float(row[6] or 0))
        cat_dates.setdefault(cat_id, []).append(row[4] or "")

    cat_best: dict[str, dict[str, Any]] = {}
    cat_freq: dict[str, int] = {}
    cat_exact: dict[str, int] = {}
    cat_sources: dict[str, dict[str, int]] = {}
    sub_scores: dict[tuple[str, str | None], float] = {}
    sub_names: dict[tuple[str, str | None], str] = {}
    sub_notes: dict[tuple[str, str | None], str] = {}
    sub_frequency: dict[tuple[str, str | None], int] = {}

    for desc_score, row in relevant:
        cat_id = row[0]
        if not cat_id:
            continue
        cat_name = row[1] or ""
        sub_id = row[2]
        sub_name = row[3] or ""
        ref_date = row[4] or ""
        ref_amount = float(row[6] or 0)
        ref_acc = row[7]
        ref_notes = row[8] or ""

        date_score = recurring_pattern_score(tx_date, cat_dates.get(cat_id, []))
        amount_score = amount_range_fit(tx_amount, cat_amounts.get(cat_id, []))
        account_score = account_similarity(tx_account_id, ref_acc)
        full_score = (
            (0.60 * desc_score)
            + (0.20 * account_score)
            + (0.15 * amount_score)
            + (0.05 * date_score)
        )

        if cat_id not in cat_best or full_score > cat_best[cat_id]["best_score"]:
            cat_best[cat_id] = {
                "category_id": cat_id,
                "category_name": cat_name,
                "best_score": full_score,
                "best_notes": ref_notes,
            }

        cat_freq[cat_id] = cat_freq.get(cat_id, 0) + 1
        source = row[9] if len(row) > 9 else "history"
        cat_sources.setdefault(cat_id, {"history": 0, "transaction": 0})[source] += 1
        if desc_score > 0.85:
            cat_exact[cat_id] = cat_exact.get(cat_id, 0) + 1

        sub_key = (cat_id, sub_id)
        if full_score > sub_scores.get(sub_key, 0.0):
            sub_scores[sub_key] = full_score
            sub_names[sub_key] = sub_name
            sub_notes[sub_key] = ref_notes
        if sub_id:
            sub_frequency[sub_key] = sub_frequency.get(sub_key, 0) + 1

    ranked: list[dict[str, Any]] = []
    for cat_id, info in cat_best.items():
        freq = cat_freq.get(cat_id, 1)
        exact = cat_exact.get(cat_id, 0)
        final_score = (
            info["best_score"] + (math.log(1 + freq) * 0.05) + min(exact * 0.08, 0.25)
        )
        candidates = [(k, v) for k, v in sub_scores.items() if k[0] == cat_id]
        if candidates:
            best_sub_key = max(candidates, key=lambda x: x[1])[0]
            best_sub_id = best_sub_key[1]
            best_sub_name = sub_names.get(best_sub_key, "")
            best_sub_notes = sub_notes.get(best_sub_key, info.get("best_notes", ""))
        else:
            best_sub_id = None
            best_sub_name = ""
            best_sub_notes = info.get("best_notes", "")

        subcategory_candidates = []
        for (candidate_cat, candidate_sub), candidate_score in sorted(
            sub_scores.items(), key=lambda item: item[1], reverse=True
        ):
            if candidate_cat != cat_id or not candidate_sub:
                continue
            subcategory_candidates.append(
                {
                    "subcategory_id": candidate_sub,
                    "subcategory_name": sub_names.get(
                        (candidate_cat, candidate_sub), ""
                    ),
                    "confidence": round(min(100.0, candidate_score * 100.0), 2),
                    "frequency": sub_frequency.get((candidate_cat, candidate_sub), 0),
                }
            )
            if len(subcategory_candidates) >= 3:
                break

        ranked.append(
            {
                "category_id": cat_id,
                "category_name": info["category_name"],
                "subcategory_id": best_sub_id,
                "subcategory_name": best_sub_name,
                "best_notes": best_sub_notes,
                "score": final_score,
                "best_score": info["best_score"],
                "frequency": freq,
                "exact_matches": exact,
                "history_evidence": cat_sources.get(cat_id, {}).get("history", 0),
                "transaction_evidence": cat_sources.get(cat_id, {}).get(
                    "transaction", 0
                ),
                "subcategories": subcategory_candidates,
            }
        )

    ranked.sort(key=lambda x: x["score"], reverse=True)
    total = sum(float(r["score"]) for r in ranked) or 1.0
    cat_total: dict[str, float] = {}
    for r in ranked:
        cat_total[r["category_id"]] = cat_total.get(r["category_id"], 0.0) + float(
            r["score"]
        )

    for r in ranked:
        r["probability"] = round((float(r["score"]) / total) * 100, 2)
        r["confidence"] = round(min(100.0, float(r["score"]) * 100.0), 2)
        cat_score = cat_total.get(r["category_id"], 1.0)
        sub_key = (r["category_id"], r["subcategory_id"])
        r["subcategory_probability"] = (
            round(min(100.0, sub_scores.get(sub_key, 0.0) * 100.0), 2)
            if r["subcategory_id"]
            else 0.0
        )
        r["category_probability"] = r["confidence"]
        r["frequency"] = int(r["frequency"])
    return ranked


def best_history_match_for_tx(
    conn: sqlite3.Connection, tx: dict[str, Any]
) -> dict[str, Any] | None:
    ranked = build_scored_evidence(
        conn, tx, None, include_transactions=False, include_history=True
    )
    if not ranked:
        return None
    best = ranked[0]
    raw_score = float(best.get("best_score") or 0)
    if raw_score < 0.20:
        return None

    return {
        "match_probability": round(raw_score * 100.0, 2),
        "match_category_id": best["category_id"],
        "match_category_name": best["category_name"] or "",
        "match_subcategory_id": best.get("subcategory_id"),
        "match_subcategory_name": best.get("subcategory_name") or "",
        "match_notes": best.get("best_notes") or "",
    }


def parse_date(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dt.datetime):
        return raw.date().isoformat()
    if isinstance(raw, dt.date):
        return raw.isoformat()
    if isinstance(raw, (float, int)):
        try:
            d = dt.datetime(1899, 12, 30) + dt.timedelta(days=float(raw))
            return d.date().isoformat()
        except (OverflowError, TypeError, ValueError):
            return ""
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse_money(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    trailing_minus = text.endswith("-")
    if trailing_minus:
        text = text[:-1]
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        val = float(text)
    except ValueError:
        return None
    return -val if trailing_minus else val


def parse_csv(path: Path) -> list[ParsedTx]:
    out: list[ParsedTx] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delim)
        headers = {norm_text(h).replace(" ", "_"): h for h in (reader.fieldnames or [])}
        h_date = headers.get("data") or headers.get("date") or headers.get("dia")
        h_desc = (
            headers.get("descricao")
            or headers.get("historico")
            or headers.get("estabelecimento")
        )
        h_val = headers.get("valor")
        h_type = headers.get("tipo")
        h_cred = headers.get("credito")
        h_deb = headers.get("debito")
        h_inst = (
            headers.get("parcela")
            or headers.get("parcelas")
            or headers.get("parcelamento")
        )
        for row in reader:
            d = parse_date(row.get(h_date, "")) if h_date else ""
            desc = (row.get(h_desc, "") or "").strip() if h_desc else ""
            if not (d and desc):
                continue
            inst_current, inst_total = (
                parse_installment(row.get(h_inst, "")) if h_inst else (None, None)
            )
            if h_cred or h_deb:
                cred = parse_money(row.get(h_cred, "")) if h_cred else None
                deb = parse_money(row.get(h_deb, "")) if h_deb else None
                if cred not in (None, 0.0):
                    out.append(
                        ParsedTx(d, desc, abs(cred), "income", inst_current, inst_total)
                    )
                if deb not in (None, 0.0):
                    out.append(
                        ParsedTx(d, desc, abs(deb), "expense", inst_current, inst_total)
                    )
                continue
            v = parse_money(row.get(h_val, "")) if h_val else None
            if v is None:
                continue
            rt = (row.get(h_type, "") or "").strip().lower() if h_type else ""
            if rt in {"entrada", "income", "credito", "crÃ©dito"}:
                t = "income"
            elif rt in {"saida", "saÃ­da", "expense", "debito", "dÃ©bito"}:
                t = "expense"
            else:
                t = "income" if v >= 0 else "expense"
            out.append(ParsedTx(d, desc, abs(v), t, inst_current, inst_total))
    return out


def parse_xlsx(path: Path) -> list[ParsedTx]:
    if openpyxl is None:
        raise RuntimeError("openpyxl nao encontrado")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return parse_tabular_rows(rows)


def parse_xls(path: Path) -> list[ParsedTx]:
    if xlrd is None:
        raise RuntimeError("xlrd nao encontrado")
    book = xlrd.open_workbook(str(path))
    sh = book.sheet_by_index(0)
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    return parse_tabular_rows(rows)


def parse_tabular_rows(rows: list[list[Any]]) -> list[ParsedTx]:
    if not rows:
        return []
    best, score = 0, -1
    keys = {
        "data",
        "dia",
        "date",
        "descricao",
        "historico",
        "estabelecimento",
        "valor",
        "credito",
        "debito",
        "tipo",
        "parcela",
        "parcelas",
        "parcelamento",
    }
    for i, row in enumerate(rows[:20]):
        rk = {norm_text(str(c)).replace(" ", "_") for c in row if str(c).strip()}
        s = len(rk.intersection(keys))
        if s > score:
            best, score = i, s
    header = [norm_text(str(c)).replace(" ", "_") for c in rows[best]]
    idx = {h: i for i, h in enumerate(header) if h}

    def get(row: list[Any], k: str) -> Any:
        i = idx.get(k)
        if i is None or i >= len(row):
            return None
        return row[i]

    out: list[ParsedTx] = []
    for row in rows[best + 1 :]:
        d = parse_date(get(row, "data") or get(row, "dia") or get(row, "date"))
        desc = str(
            get(row, "descricao")
            or get(row, "historico")
            or get(row, "estabelecimento")
            or ""
        ).strip()
        if not (d and desc):
            continue
        inst_current, inst_total = parse_installment(
            get(row, "parcela") or get(row, "parcelas") or get(row, "parcelamento")
        )
        cred = parse_money(get(row, "credito"))
        deb = parse_money(get(row, "debito"))
        if cred not in (None, 0.0):
            out.append(ParsedTx(d, desc, abs(cred), "income", inst_current, inst_total))
        if deb not in (None, 0.0):
            out.append(ParsedTx(d, desc, abs(deb), "expense", inst_current, inst_total))
        if cred not in (None, 0.0) or deb not in (None, 0.0):
            continue
        v = parse_money(get(row, "valor"))
        if v is None:
            continue
        rt = str(get(row, "tipo") or "").strip().lower()
        if rt in {"entrada", "income", "credito", "crÃ©dito"}:
            t = "income"
        elif rt in {"saida", "saÃ­da", "expense", "debito", "dÃ©bito"}:
            t = "expense"
        else:
            t = "income" if v >= 0 else "expense"
        out.append(ParsedTx(d, desc, abs(v), t, inst_current, inst_total))
    return out


def parse_pdf(path: Path) -> list[ParsedTx]:
    if PdfReader is None:
        raise RuntimeError("pypdf nao encontrado")
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        logger.exception("Falha ao abrir PDF %s", path)
        raise RuntimeError(f"Falha ao abrir PDF: {exc}") from exc
    page_texts: list[str] = []
    for pg in reader.pages:
        try:
            page_texts.append(pg.extract_text() or "")
        except Exception:
            # Ignora pagina com erro e segue com as demais.
            logger.warning("Falha ao extrair pagina do PDF %s", path, exc_info=True)
            continue
    text = "\n".join(page_texts)
    if not text.strip():
        return []
    out: list[ParsedTx] = []
    amount_re = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")

    year = dt.datetime.now().year
    ym = re.search(r"/(\d{4})", text[:2500])
    if ym:
        try:
            year = int(ym.group(1))
        except (TypeError, ValueError):
            logger.warning("Ano invalido detectado no PDF %s", path, exc_info=True)

    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    pending_date = ""
    pending_parts: list[str] = []

    def maybe_commit() -> None:
        nonlocal pending_date, pending_parts, out
        if not pending_date or not pending_parts:
            return
        joined = " ".join(pending_parts).strip()
        vals = amount_re.findall(joined)
        if not vals:
            return
        mov = vals[-2] if len(vals) >= 2 else vals[-1]
        pos = joined.find(mov)
        if pos <= 0:
            return
        desc = joined[:pos].strip(" -")
        v = parse_money(mov)
        if not desc or v is None:
            return
        d = parse_date(f"{pending_date}/{year}")
        if not d:
            return
        out.append(ParsedTx(d, desc, abs(v), "income" if v > 0 else "expense"))
        pending_date = ""
        pending_parts = []

    for ln in lines:
        ln_norm = norm_text(ln)
        # Extrato Santander costuma repetir operaÃ§Ãµes no bloco final de comprovantes.
        # Quando esse bloco inicia, ignoramos o restante para evitar lanÃ§amentos espelhados.
        if (
            "comprovantes de lancamento" in ln_norm
            or "comprovante de lancamento" in ln_norm
        ):
            maybe_commit()
            break
        if ln.lower().startswith("data descricao") or ln.lower().startswith(
            "saldo em "
        ):
            continue
        m = re.match(r"^(\d{2}/\d{2})\s+(.*)$", ln)
        if m:
            maybe_commit()
            pending_date = m.group(1)
            rest = m.group(2).strip()
            pending_parts = [rest] if rest else []
            maybe_commit()
            continue
        if pending_date:
            pending_parts.append(ln)
            maybe_commit()
            if len(pending_parts) > 4:
                pending_date = ""
                pending_parts = []

    maybe_commit()

    # Fallback generico para comprovantes/faturas em formato compacto.
    if not out:
        for ln in lines:
            m = re.search(r"(\d{2}/\d{2}/\d{4}).*?(-?\d{1,3}(?:\.\d{3})*,\d{2}-?)", ln)
            if not m:
                continue
            d = parse_date(m.group(1))
            v = parse_money(m.group(2))
            if not d or v is None:
                continue
            desc = ln.replace(m.group(1), "").replace(m.group(2), "").strip(" -")
            if not desc:
                desc = "LANCAMENTO PDF"
            out.append(ParsedTx(d, desc, abs(v), "income" if v > 0 else "expense"))

    return out


def parse_santander_card_statement_pdf(path: Path) -> list[ParsedTx]:
    if PdfReader is None:
        raise RuntimeError("pypdf nao encontrado")
    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    if not text.strip():
        return []

    # CompetÃªncia no nome: "... - 03-26 - ...", fallback para ano atual.
    name_norm = norm_text(path.name)
    ref_year = dt.datetime.now().year
    ref_month = dt.datetime.now().month
    mref = re.search(r"(\d{2})[-_/](\d{2})", name_norm)
    if mref:
        ref_month = int(mref.group(1))
        ref_year = 2000 + int(mref.group(2))

    amount_re = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")
    out: list[ParsedTx] = []
    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    for ln in lines:
        ln_norm = norm_text(ln)
        if any(
            k in ln_norm
            for k in (
                "detalhamento da fatura",
                "pagamento e demais creditos",
                "parcelamentos",
                "despesas",
                "valor total",
                "compra data descricao",
                "parcela",
                "santander",
            )
        ):
            continue
        m = re.search(r"(\d{2}/\d{2})\s+(.+)$", ln)
        if not m:
            continue
        ddmm = m.group(1)
        rest = m.group(2).strip()
        vals = amount_re.findall(rest)
        if not vals:
            continue
        val_txt = vals[-1]
        val = parse_money(val_txt)
        if val is None:
            continue
        pos = rest.rfind(val_txt)
        desc = rest[:pos].strip(" -")
        if not desc:
            continue
        inst_current, inst_total = parse_installment(desc)
        desc = re.sub(r"\s+\d{1,2}/\d{1,2}\s*$", "", desc).strip()
        if not desc:
            continue

        day = int(ddmm[:2])
        month = int(ddmm[3:5])
        year = ref_year if month <= ref_month else (ref_year - 1)
        d = parse_date(f"{day:02d}/{month:02d}/{year}")
        if not d:
            continue
        out.append(
            ParsedTx(
                d,
                desc,
                abs(val),
                "income" if val > 0 else "expense",
                inst_current,
                inst_total,
            )
        )
    return out


def remove_santander_statement_mirrors(txs: list[ParsedTx]) -> list[ParsedTx]:
    if not txs:
        return txs
    incomes = []
    expenses = []
    for i, t in enumerate(txs):
        if t.tx_type == "income":
            incomes.append((i, t))
        elif t.tx_type == "expense":
            expenses.append((i, t))

    remove_income_idx: set[int] = set()
    for i_idx, inc in incomes:
        inc_desc = norm_text(inc.description)
        inc_amt = round(abs(float(inc.amount or 0)), 2)
        try:
            inc_date = dt.date.fromisoformat(inc.date)
        except (TypeError, ValueError):
            continue
        is_proof_line = inc_desc.startswith(
            "internet banking pix"
        ) or inc_desc.startswith("cartao de credito")
        if not is_proof_line:
            continue

        for _, exp in expenses:
            exp_desc = norm_text(exp.description)
            exp_amt = round(abs(float(exp.amount or 0)), 2)
            if exp_amt != inc_amt:
                continue
            try:
                exp_date = dt.date.fromisoformat(exp.date)
            except (TypeError, ValueError):
                continue
            date_delta = abs((inc_date - exp_date).days)
            if date_delta > 1:
                continue

            pix_pair = "internet banking pix" in inc_desc and "pix enviado" in exp_desc
            card_pair = (
                "cartao de credito" in inc_desc
                and "debito aut" in exp_desc
                and "fatura cartao" in exp_desc
            )
            if pix_pair or card_pair:
                remove_income_idx.add(i_idx)
                break

    if not remove_income_idx:
        return txs
    return [t for idx, t in enumerate(txs) if idx not in remove_income_idx]


def load_transactions(path: Path) -> list[ParsedTx]:
    ext = path.suffix.lower()
    if ext == ".csv":
        return parse_csv(path)
    if ext == ".xlsx":
        return parse_xlsx(path)
    if ext == ".xls":
        return parse_xls(path)
    if ext == ".pdf":
        return parse_pdf(path)
    raise RuntimeError(f"Formato nao suportado: {ext}")


def tx_key(account_id: str, date: str, amount: float, desc: str) -> str:
    return f"{account_id}|{date}|{amount:.2f}|{norm_text(desc)}"


def normalize_history_label(value: Any) -> str:
    normalized = norm_text(str(value or ""))
    compact = normalized.replace(" ", "")
    degraded_aliases = {
        "sadas": "saidas",
        "descrio": "descricao",
        "observao": "observacao",
        "hlcio": "helcio",
        "hlciosmartek": "helcio_smartek",
    }
    return degraded_aliases.get(compact, normalized.replace(" ", "_"))


def map_headers(cells: list[Any]) -> dict[str, int]:
    headers: dict[str, int] = {}
    for i, cell in enumerate(cells):
        key = normalize_history_label(cell)
        if key:
            headers[key] = i
    return headers


def row_get(row: list[Any], idx: dict[str, int], keys: list[str]) -> Any:
    for k in keys:
        i = idx.get(k)
        if i is not None and i < len(row):
            return row[i]
    return None


def create_index_safely(conn, index_name: str, sql: str) -> None:
    """Cria indices ausentes sem impedir o boot quando o Postgres estiver bloqueado."""
    if not IS_POSTGRES:
        conn.execute(sql)
        return
    exists = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname=current_schema() AND indexname=?",
        (index_name,),
    ).fetchone()
    if exists:
        return
    conn.execute("SAVEPOINT create_optional_index")
    try:
        conn.execute(sql)
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT create_optional_index")
        logger.warning(
            "Indice opcional %s adiado: %s: %s", index_name, type(exc).__name__, exc
        )
    finally:
        conn.execute("RELEASE SAVEPOINT create_optional_index")


def delete_import_batches(conn, imported_ids: list[str]) -> int:
    """Remove lotes de importacao e todos os dados derivados dos lancamentos."""
    deleted_transactions = 0
    for imported_id in imported_ids:
        deleted_transactions += int(
            conn.execute(
                "SELECT COUNT(1) FROM transactions WHERE imported_file_id=?",
                (imported_id,),
            ).fetchone()[0]
            or 0
        )
        conn.execute(
            """
            DELETE FROM transaction_reconciliations
            WHERE expense_transaction_id IN (SELECT id FROM transactions WHERE imported_file_id=?)
               OR income_transaction_id IN (SELECT id FROM transactions WHERE imported_file_id=?)
            """,
            (imported_id, imported_id),
        )
        conn.execute(
            "DELETE FROM transaction_suggestions WHERE transaction_id IN "
            "(SELECT id FROM transactions WHERE imported_file_id=?)",
            (imported_id,),
        )
        conn.execute(
            "DELETE FROM transaction_suggestion_state WHERE transaction_id IN "
            "(SELECT id FROM transactions WHERE imported_file_id=?)",
            (imported_id,),
        )
        conn.execute(
            "DELETE FROM classification_history WHERE source_file_id IN "
            "(SELECT ('manual:' || id) FROM transactions WHERE imported_file_id=?)",
            (imported_id,),
        )
        conn.execute(
            "DELETE FROM transactions WHERE imported_file_id=?", (imported_id,)
        )
        conn.execute("DELETE FROM imported_files WHERE id=?", (imported_id,))
    if imported_ids:
        conn.execute(
            "DELETE FROM installment_plans WHERE id NOT IN "
            "(SELECT installment_plan_id FROM transactions WHERE installment_plan_id IS NOT NULL)"
        )
    return deleted_transactions


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              type TEXT NOT NULL,
              color TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              color TEXT NOT NULL,
              text_color TEXT NOT NULL,
              type TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subcategories(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS imported_files(
              id TEXT PRIMARY KEY,
              filename TEXT NOT NULL,
              file_type TEXT NOT NULL,
              file_hash TEXT NOT NULL,
              source_path TEXT NOT NULL,
              account_id TEXT NOT NULL,
              account_name TEXT NOT NULL,
              total_parsed INTEGER NOT NULL,
              total_inserted INTEGER NOT NULL,
              total_duplicates INTEGER NOT NULL,
              total_errors INTEGER NOT NULL,
              year TEXT NOT NULL DEFAULT '',
              month TEXT NOT NULL DEFAULT '',
              source_kind TEXT NOT NULL DEFAULT '',
              bank TEXT NOT NULL DEFAULT '',
              imported_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions(
              id TEXT PRIMARY KEY,
              tx_key TEXT NOT NULL UNIQUE,
              date TEXT NOT NULL,
              competence_month TEXT NOT NULL,
              description TEXT NOT NULL,
              description_norm TEXT NOT NULL,
              merchant_norm TEXT NOT NULL DEFAULT '',
              transaction_method TEXT NOT NULL DEFAULT 'other',
              counterparty_name TEXT NOT NULL DEFAULT '',
              bank_reference TEXT NOT NULL DEFAULT '',
              amount REAL NOT NULL,
              type TEXT NOT NULL,
              status TEXT NOT NULL,
              account_id TEXT NOT NULL,
              category_id TEXT,
              subcategory_id TEXT,
              notes TEXT NOT NULL DEFAULT '',
              suggested_category_id TEXT,
              suggested_subcategory_id TEXT,
              installment_current INTEGER,
              installment_total INTEGER,
              flags TEXT NOT NULL DEFAULT '',
              match_probability REAL NOT NULL DEFAULT 0.0,
              match_notes TEXT NOT NULL DEFAULT '',
              history_match_id TEXT,
              history_match_confirmed INTEGER NOT NULL DEFAULT 0,
              history_match_rejected_id TEXT,
              identity_score REAL NOT NULL DEFAULT 0.0,
              imported_file_id TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS classification_history(
              id TEXT PRIMARY KEY,
              source_file_id TEXT NOT NULL,
              account_id TEXT,
              date TEXT,
              description TEXT NOT NULL,
              description_norm TEXT NOT NULL,
              merchant_norm TEXT NOT NULL DEFAULT '',
              transaction_method TEXT NOT NULL DEFAULT 'other',
              counterparty_name TEXT NOT NULL DEFAULT '',
              bank_reference TEXT NOT NULL DEFAULT '',
              amount REAL NOT NULL,
              type TEXT NOT NULL,
              category_id TEXT NOT NULL,
              subcategory_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transaction_reconciliations(
              id TEXT PRIMARY KEY,
              expense_transaction_id TEXT NOT NULL,
              income_transaction_id TEXT NOT NULL,
              amount REAL NOT NULL,
              created_by TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS installment_plans(
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL,
              description TEXT NOT NULL,
              description_norm TEXT NOT NULL,
              installment_total INTEGER NOT NULL,
              installment_amount REAL NOT NULL,
              first_seen_date TEXT NOT NULL,
              category_id TEXT,
              subcategory_id TEXT,
              classified_by TEXT NOT NULL DEFAULT '',
              classified_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_previews(
              id TEXT PRIMARY KEY,
              filename TEXT NOT NULL,
              temp_path TEXT NOT NULL,
              account_id TEXT NOT NULL,
              detected_type TEXT NOT NULL,
              detection_confidence REAL NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recalculation_jobs(
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'queued',
              processed INTEGER NOT NULL DEFAULT 0,
              total INTEGER NOT NULL DEFAULT 0,
              updated INTEGER NOT NULL DEFAULT 0,
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_jobs(
              id TEXT PRIMARY KEY,
              preview_id TEXT NOT NULL UNIQUE,
              filename TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued',
              phase TEXT NOT NULL DEFAULT 'queued',
              processed INTEGER NOT NULL DEFAULT 0,
              total INTEGER NOT NULL DEFAULT 0,
              message TEXT NOT NULL DEFAULT '',
              logs_json TEXT NOT NULL DEFAULT '[]',
              result_json TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seed_import_jobs(
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'queued',
              filename TEXT NOT NULL,
              phase TEXT NOT NULL DEFAULT 'queued',
              processed INTEGER NOT NULL DEFAULT 0,
              total INTEGER NOT NULL DEFAULT 0,
              message TEXT NOT NULL DEFAULT '',
              logs_json TEXT NOT NULL DEFAULT '[]',
              result_json TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS suggestion_jobs(
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'queued',
              mode TEXT NOT NULL DEFAULT 'incremental',
              processed INTEGER NOT NULL DEFAULT 0,
              total INTEGER NOT NULL DEFAULT 0,
              updated INTEGER NOT NULL DEFAULT 0,
              with_suggestions INTEGER NOT NULL DEFAULT 0,
              without_suggestions INTEGER NOT NULL DEFAULT 0,
              message TEXT NOT NULL DEFAULT '',
              logs_json TEXT NOT NULL DEFAULT '[]',
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transaction_suggestion_state(
              transaction_id TEXT PRIMARY KEY,
              fingerprint TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'completed',
              suggestion_count INTEGER NOT NULL DEFAULT 0,
              best_confidence REAL NOT NULL DEFAULT 0,
              dismissed INTEGER NOT NULL DEFAULT 0,
              calculated_at TEXT NOT NULL,
              error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transaction_suggestions(
              transaction_id TEXT NOT NULL,
              rank INTEGER NOT NULL,
              category_id TEXT NOT NULL,
              subcategory_id TEXT,
              confidence REAL NOT NULL DEFAULT 0,
              category_probability REAL NOT NULL DEFAULT 0,
              subcategory_probability REAL NOT NULL DEFAULT 0,
              frequency INTEGER NOT NULL DEFAULT 0,
              history_evidence INTEGER NOT NULL DEFAULT 0,
              transaction_evidence INTEGER NOT NULL DEFAULT 0,
              justification TEXT NOT NULL DEFAULT '',
              subcategories_json TEXT NOT NULL DEFAULT '[]',
              calculated_at TEXT NOT NULL,
              PRIMARY KEY(transaction_id, rank)
            )
            """
        )
        seed_job_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(seed_import_jobs)").fetchall()
        ]
        for col, definition in (
            ("phase", "TEXT NOT NULL DEFAULT 'queued'"),
            ("processed", "INTEGER NOT NULL DEFAULT 0"),
            ("total", "INTEGER NOT NULL DEFAULT 0"),
            ("message", "TEXT NOT NULL DEFAULT ''"),
            ("logs_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("source_path", "TEXT NOT NULL DEFAULT ''"),
            ("replace_existing", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in seed_job_cols:
                conn.execute(
                    f"ALTER TABLE seed_import_jobs ADD COLUMN {col} {definition}"
                )
        import_job_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(import_jobs)").fetchall()
        ]
        for col, definition in (
            ("phase", "TEXT NOT NULL DEFAULT 'queued'"),
            ("processed", "INTEGER NOT NULL DEFAULT 0"),
            ("total", "INTEGER NOT NULL DEFAULT 0"),
            ("message", "TEXT NOT NULL DEFAULT ''"),
            ("logs_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("confirm_duplicates", "INTEGER NOT NULL DEFAULT 0"),
            ("competence_month", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in import_job_cols:
                conn.execute(f"ALTER TABLE import_jobs ADD COLUMN {col} {definition}")
        if WORKER_MODE == "inline":
            now = dt.datetime.now().isoformat(timespec="seconds")
            for table, extra_fields, message in (
                (
                    "seed_import_jobs",
                    "phase='interrupted',",
                    "Processamento interrompido; envie o arquivo novamente",
                ),
                ("suggestion_jobs", "", "Processamento interrompido; tente novamente"),
                (
                    "import_jobs",
                    "phase='interrupted',",
                    "Processamento interrompido; tente novamente",
                ),
            ):
                conn.execute(
                    f"""
                    UPDATE {table}
                    SET status='failed', {extra_fields}
                        error='Processamento interrompido por reinicializacao do servidor',
                        message=?, finished_at=?
                    WHERE status IN ('queued','running','claimed')
                    """,
                    (message, now),
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_log(
              id TEXT PRIMARY KEY,
              executed_at TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Remove somente lotes parciais de planilhas: importacoes concluidas sempre
        # possuem imported_files.id igual ao prefixo anterior a ':sheet:'.
        conn.execute(
            """
            DELETE FROM classification_history
            WHERE source_file_id LIKE '%:sheet:%'
              AND NOT EXISTS (
                SELECT 1 FROM imported_files f
                WHERE source_file_id LIKE (f.id || ':sheet:%')
              )
            """
        )
        # Manutencoes destrutivas nunca devem rodar implicitamente no startup.
        # A limpeza pontual da base historica de 2026-07-15 foi removida depois
        # de executada; ambientes restaurados nao podem repetir essa operacao.
        if WORKER_MODE == "inline":
            conn.execute(
                """
            UPDATE recalculation_jobs
            SET status='failed',
                error='Processamento interrompido por reinicializacao do servidor',
                finished_at=?
            WHERE status IN ('queued','running','claimed')
            """,
                (dt.datetime.now().isoformat(timespec="seconds"),),
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_file_coverage(
              id TEXT PRIMARY KEY,
              account_id TEXT NOT NULL,
              year_month TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'dispensed',
              reason TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              UNIQUE(account_id, year_month)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledgers(
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              description TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '#c9a84c',
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            )
            """
        )
        create_index_safely(
            conn,
            "idx_tx_desc_norm",
            "CREATE INDEX IF NOT EXISTS idx_tx_desc_norm ON transactions(description_norm)",
        )
        create_index_safely(
            conn,
            "idx_tx_status",
            "CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status)",
        )
        create_index_safely(
            conn,
            "idx_hist_desc_norm",
            "CREATE INDEX IF NOT EXISTS idx_hist_desc_norm ON classification_history(description_norm)",
        )
        create_index_safely(
            conn,
            "idx_tx_status_date",
            "CREATE INDEX IF NOT EXISTS idx_tx_status_date ON transactions(status,date)",
        )
        create_index_safely(
            conn,
            "idx_tx_month_status_account",
            "CREATE INDEX IF NOT EXISTS idx_tx_month_status_account ON transactions(competence_month,status,account_id)",
        )
        create_index_safely(
            conn,
            "idx_tx_dedupe",
            "CREATE INDEX IF NOT EXISTS idx_tx_dedupe ON transactions(account_id,date,amount,type,description_norm,installment_current,installment_total)",
        )
        create_index_safely(
            conn,
            "idx_tx_history_match_status",
            "CREATE INDEX IF NOT EXISTS idx_tx_history_match_status ON transactions(history_match_id,status)",
        )
        create_index_safely(
            conn,
            "idx_hist_type_desc_norm",
            "CREATE INDEX IF NOT EXISTS idx_hist_type_desc_norm ON classification_history(type,description_norm)",
        )
        create_index_safely(
            conn,
            "idx_hist_type_account_date_amount",
            "CREATE INDEX IF NOT EXISTS idx_hist_type_account_date_amount ON classification_history(type,account_id,date,amount)",
        )
        # MigraÃ§Ã£o segura para bases antigas.
        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(classification_history)"
            ).fetchall()
        ]
        if "account_id" not in cols:
            conn.execute(
                "ALTER TABLE classification_history ADD COLUMN account_id TEXT"
            )
        tx_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()
        ]
        for col, definition in (
            ("merchant_norm", "TEXT NOT NULL DEFAULT ''"),
            ("transaction_method", "TEXT NOT NULL DEFAULT 'other'"),
            ("counterparty_name", "TEXT NOT NULL DEFAULT ''"),
            ("bank_reference", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in tx_cols:
                conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {definition}")
        if "installment_current" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN installment_current INTEGER"
            )
        if "installment_total" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN installment_total INTEGER"
            )
        if "flags" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN flags TEXT NOT NULL DEFAULT ''"
            )
        if "match_probability" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN match_probability REAL NOT NULL DEFAULT 0.0"
            )
        if "match_notes" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN match_notes TEXT NOT NULL DEFAULT ''"
            )
        if "history_match_id" not in tx_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN history_match_id TEXT")
        if "history_match_confirmed" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN history_match_confirmed INTEGER NOT NULL DEFAULT 0"
            )
        if "history_match_rejected_id" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN history_match_rejected_id TEXT"
            )
        if "identity_score" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN identity_score REAL NOT NULL DEFAULT 0.0"
            )
        if "ledger_id" not in tx_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN ledger_id TEXT")
        hist_cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(classification_history)"
            ).fetchall()
        ]
        for col, definition in (
            ("merchant_norm", "TEXT NOT NULL DEFAULT ''"),
            ("transaction_method", "TEXT NOT NULL DEFAULT 'other'"),
            ("counterparty_name", "TEXT NOT NULL DEFAULT ''"),
            ("bank_reference", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in hist_cols:
                conn.execute(
                    f"ALTER TABLE classification_history ADD COLUMN {col} {definition}"
                )
        if "ledger_id" not in hist_cols:
            conn.execute("ALTER TABLE classification_history ADD COLUMN ledger_id TEXT")
        create_index_safely(
            conn,
            "idx_tx_ledger",
            "CREATE INDEX IF NOT EXISTS idx_tx_ledger ON transactions(ledger_id)",
        )
        create_index_safely(
            conn,
            "idx_hist_ledger",
            "CREATE INDEX IF NOT EXISTS idx_hist_ledger ON classification_history(ledger_id)",
        )
        file_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(imported_files)").fetchall()
        ]
        if "year" not in file_cols:
            conn.execute(
                "ALTER TABLE imported_files ADD COLUMN year TEXT NOT NULL DEFAULT ''"
            )
        if "month" not in file_cols:
            conn.execute(
                "ALTER TABLE imported_files ADD COLUMN month TEXT NOT NULL DEFAULT ''"
            )
        if "source_kind" not in file_cols:
            conn.execute(
                "ALTER TABLE imported_files ADD COLUMN source_kind TEXT NOT NULL DEFAULT ''"
            )
        if "bank" not in file_cols:
            conn.execute(
                "ALTER TABLE imported_files ADD COLUMN bank TEXT NOT NULL DEFAULT ''"
            )
        # Colunas de protecao contra alteracao acidental (versao web).
        if "locked" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN locked INTEGER NOT NULL DEFAULT 0"
            )
        if "classified_by" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN classified_by TEXT NOT NULL DEFAULT ''"
            )
        if "classified_at" not in tx_cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN classified_at TEXT NOT NULL DEFAULT ''"
            )
        if "installment_plan_id" not in tx_cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN installment_plan_id TEXT")
        create_index_safely(
            conn,
            "idx_tx_locked",
            "CREATE INDEX IF NOT EXISTS idx_tx_locked ON transactions(locked)",
        )
        create_index_safely(
            conn,
            "idx_tx_installment_plan",
            "CREATE INDEX IF NOT EXISTS idx_tx_installment_plan ON transactions(installment_plan_id)",
        )
        create_index_safely(
            conn,
            "idx_suggestion_state_status",
            "CREATE INDEX IF NOT EXISTS idx_suggestion_state_status ON transaction_suggestion_state(status,dismissed,best_confidence)",
        )
        create_index_safely(
            conn,
            "idx_suggestions_category",
            "CREATE INDEX IF NOT EXISTS idx_suggestions_category ON transaction_suggestions(category_id,subcategory_id)",
        )
        create_index_safely(
            conn,
            "idx_reconciliation_expense",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliation_expense ON transaction_reconciliations(expense_transaction_id)",
        )
        create_index_safely(
            conn,
            "idx_reconciliation_income",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliation_income ON transaction_reconciliations(income_transaction_id)",
        )
        create_index_safely(
            conn,
            "idx_suggestion_jobs_single_active",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestion_jobs_single_active "
            "ON suggestion_jobs((1)) WHERE status IN ('queued','running')",
        )
        create_index_safely(
            conn,
            "idx_installment_plan_match",
            "CREATE INDEX IF NOT EXISTS idx_installment_plan_match "
            "ON installment_plans(account_id,description_norm,installment_total,installment_amount)",
        )
        # Cofre de arquivos persistente no banco (o disco do hosting e efemero).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stored_documents(
              id TEXT PRIMARY KEY,
              account_name TEXT NOT NULL,
              year_month TEXT NOT NULL,
              filename TEXT NOT NULL,
              size INTEGER NOT NULL DEFAULT 0,
              content_b64 TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        stored_document_cols = [
            r[1] for r in conn.execute("PRAGMA table_info(stored_documents)").fetchall()
        ]
        if "imported_file_id" not in stored_document_cols:
            conn.execute(
                "ALTER TABLE stored_documents ADD COLUMN imported_file_id TEXT"
            )
        create_index_safely(
            conn,
            "idx_docs_acc_month",
            "CREATE INDEX IF NOT EXISTS idx_docs_acc_month ON stored_documents(account_name, year_month)",
        )
        create_index_safely(
            conn,
            "idx_docs_imported_file",
            "CREATE INDEX IF NOT EXISTS idx_docs_imported_file ON stored_documents(imported_file_id)",
        )

        # Manutencao unica confirmada pelo proprietario em 21/07/2026: o documento
        # CARTAO NUBANK 01-25 foi apagado do cofre com a intencao de remover tambem
        # seus lancamentos, mas o vinculo legado por competencia nao encontrou o lote.
        repair_id = "repair-deleted-cartao-nubank-2025-01"
        repair_done = conn.execute(
            "SELECT 1 FROM maintenance_log WHERE id=?", (repair_id,)
        ).fetchone()
        if not repair_done:
            repair_import_ids = [
                r[0]
                for r in conn.execute(
                    """
                SELECT DISTINCT t.imported_file_id
                FROM transactions t JOIN accounts a ON a.id=t.account_id
                WHERE a.name='CARTAO NUBANK' AND t.competence_month='2025/01'
                """
                ).fetchall()
            ]
            repair_deleted = delete_import_batches(conn, repair_import_ids)
            conn.execute(
                "INSERT INTO maintenance_log(id,executed_at,detail) VALUES (?,?,?)",
                (
                    repair_id,
                    dt.datetime.now().isoformat(timespec="seconds"),
                    f"imported_files={len(repair_import_ids)};deleted_transactions={repair_deleted}",
                ),
            )

        # Reparo idempotente autorizado em 22/07/2026. O parser Nubank antigo
        # encerrava no rodape da primeira pagina e omitiu os tres movimentos de
        # 18/10/2025. Eles pertencem ao mesmo lote/documento ja importado.
        repair_id = "repair-nubank-checking-2025-10-page-2"
        repair_done = conn.execute(
            "SELECT 1 FROM maintenance_log WHERE id=?", (repair_id,)
        ).fetchone()
        if not repair_done:
            target = conn.execute(
                """
                SELECT f.id, f.account_id
                FROM imported_files f JOIN accounts a ON a.id=f.account_id
                WHERE a.name='CONTA NUBANK'
                  AND f.year='2025' AND f.month='10'
                  AND f.file_hash='ce73cc17f31a0bfa9a49d7296759d83dedbdb4b4'
                """
            ).fetchone()
            if target:
                imported_file_id, account_id = target[0], target[1]
                # Preservar a grafia exibida no documento e usada nas demais
                # linhas do mesmo extrato.
                pix_display = (
                    "Transferência recebida pelo Pix HELCIO CARNEIRO DE AVILA "
                    "MENDONCA - •••. 243.161-•• - BCO SANTANDER (BRASIL) S.A. "
                    "(0033) Agência: 1901 Conta: 1002864-2"
                )
                pix_norm = norm_text(pix_display)
                concebra_display = "Compra no débito CONCEBRA"
                concebra_norm = norm_text(concebra_display)
                source_pix = conn.execute(
                    """
                    SELECT suggested_category_id,suggested_subcategory_id
                    FROM transactions
                    WHERE imported_file_id=? AND description_norm LIKE 'transferencia recebida pelo pix%'
                    LIMIT 1
                    """,
                    (imported_file_id,),
                ).fetchone()
                source_concebra = conn.execute(
                    """
                    SELECT suggested_category_id,suggested_subcategory_id
                    FROM transactions
                    WHERE imported_file_id=? AND description_norm=?
                    LIMIT 1
                    """,
                    (imported_file_id, concebra_norm),
                ).fetchone()
                repairs = [
                    (
                        str(uuid.uuid5(uuid.NAMESPACE_URL, repair_id + ":pix")),
                        "2025-10-18",
                        pix_display,
                        pix_norm,
                        20.0,
                        "income",
                        1,
                        source_pix,
                    ),
                    (
                        str(uuid.uuid5(uuid.NAMESPACE_URL, repair_id + ":concebra:1")),
                        "2025-10-18",
                        concebra_display,
                        concebra_norm,
                        -5.4,
                        "expense",
                        1,
                        source_concebra,
                    ),
                    (
                        str(uuid.uuid5(uuid.NAMESPACE_URL, repair_id + ":concebra:2")),
                        "2025-10-18",
                        concebra_display,
                        concebra_norm,
                        -5.4,
                        "expense",
                        2,
                        source_concebra,
                    ),
                ]
                inserted = 0
                for (
                    tx_id,
                    date,
                    desc,
                    desc_norm,
                    amount,
                    tx_type,
                    occurrence,
                    source,
                ) in repairs:
                    tx_key = (
                        f"{account_id}|{date}|{amount:.2f}|{desc_norm}|"
                        f"{tx_type}|0|0#{occurrence}"
                    )
                    if conn.execute(
                        "SELECT 1 FROM transactions WHERE tx_key=?", (tx_key,)
                    ).fetchone():
                        continue
                    suggested_category_id = source[0] if source else None
                    suggested_subcategory_id = source[1] if source else None
                    conn.execute(
                        """
                        INSERT INTO transactions(
                          id,tx_key,date,competence_month,description,description_norm,
                          amount,type,status,account_id,category_id,subcategory_id,notes,
                          suggested_category_id,suggested_subcategory_id,match_probability,
                          match_notes,history_match_id,identity_score,installment_current,
                          installment_total,flags,imported_file_id,installment_plan_id,
                          locked,classified_by,classified_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            tx_id, tx_key, date, "2025/10", desc, desc_norm, amount,
                            tx_type, "pending", account_id, None, None, "",
                            suggested_category_id, suggested_subcategory_id, 0.0, "",
                            None, 0.0, None, None, "", imported_file_id, None, 0, "", "",
                        ),
                    )
                    store_shadow_metadata(
                        conn, "transactions", tx_id, desc, "checking", None, None
                    )
                    inserted += 1
                conn.execute(
                    """
                    UPDATE imported_files
                    SET total_parsed=(SELECT COUNT(1) FROM transactions WHERE imported_file_id=?),
                        total_inserted=(SELECT COUNT(1) FROM transactions WHERE imported_file_id=?)
                    WHERE id=?
                    """,
                    (imported_file_id, imported_file_id, imported_file_id),
                )
                conn.execute(
                    "INSERT INTO maintenance_log(id,executed_at,detail) VALUES (?,?,?)",
                    (
                        repair_id,
                        dt.datetime.now().isoformat(timespec="seconds"),
                        f"imported_file_id={imported_file_id};inserted={inserted}",
                    ),
                )
        applied_migrations = run_migrations(conn)
        if applied_migrations:
            logger.info("Migrations aplicadas: %s", applied_migrations)


def seed() -> None:
    with db_connect() as conn:
        now = dt.datetime.now().isoformat(timespec="seconds")
        desired = [
            ("CONTA XP", "checking", "#2563eb"),
            ("CARTAO XP", "credit_card", "#7c3aed"),
            ("CONTA NUBANK", "checking", "#14b8a6"),
            ("CARTAO NUBANK", "credit_card", "#8b5cf6"),
            ("CONTA SANTANDER", "checking", "#dc2626"),
            ("CARTAO SANTANDER", "credit_card", "#f43f5e"),
        ]
        for name, acc_type, color in desired:
            ex = conn.execute(
                "SELECT id FROM accounts WHERE name=?", (name,)
            ).fetchone()
            if not ex:
                conn.execute(
                    "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), name, acc_type, color, 1, now),
                )
        normalization = normalize_legacy_account_aliases(conn)
        if (
            normalization["history_without_account"]
            or normalization["sulivan_migrated"]
        ):
            app.logger.info(
                "[account-normalization] historico_sem_conta=%s sulivan_para_santander=%s contas_removidas=%s",
                normalization["history_without_account"],
                normalization["sulivan_migrated"],
                normalization["accounts_removed"],
            )
        if conn.execute("SELECT COUNT(1) FROM categories").fetchone()[0] == 0:
            base = [
                ("GASTO PESSOAL", "#dc2626", "#ffffff", "expense"),
                ("ALIMENTACAO", "#ea580c", "#ffffff", "expense"),
                ("TRANSPORTE", "#7c3aed", "#ffffff", "expense"),
                ("MORADIA", "#2563eb", "#ffffff", "expense"),
                ("RECEITA", "#16a34a", "#ffffff", "income"),
            ]
            for n, c, tc, t in base:
                conn.execute(
                    "INSERT INTO categories(id,name,color,text_color,type) VALUES (?,?,?,?,?)",
                    (str(uuid.uuid4()), n, c, tc, t),
                )


def get_account(conn: sqlite3.Connection, account_id: str):
    return conn.execute(
        "SELECT id,name,type,color FROM accounts WHERE id=?", (account_id,)
    ).fetchone()


def validate_classification_selection(
    conn: sqlite3.Connection,
    category_id: str,
    subcategory_id: str | None,
) -> tuple[dict[str, Any] | None, int]:
    category = conn.execute(
        "SELECT id FROM categories WHERE id=?", (category_id,)
    ).fetchone()
    if not category:
        return {"detail": "Categoria nao encontrada", "code": "CATEGORY_NOT_FOUND"}, 404
    if (
        subcategory_id
        and not conn.execute(
            "SELECT id FROM subcategories WHERE id=?", (subcategory_id,)
        ).fetchone()
    ):
        return {
            "detail": "Subcategoria nao encontrada",
            "code": "SUBCATEGORY_NOT_FOUND",
        }, 404
    return None, 200


def detect_account_by_filename(conn: sqlite3.Connection, filename: str):
    n = norm_text(filename)
    if any(
        k in n
        for k in (
            "fatura",
            "cartao",
            "comprovante de fatura",
            "comprovante de cartao",
            "comprovante-de-fatura",
        )
    ):
        if "xp" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CARTAO XP' LIMIT 1"
            ).fetchone()
        if "nubank" in n or "nu " in n or "nu_" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CARTAO NUBANK' LIMIT 1"
            ).fetchone()
        if "santander" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CARTAO SANTANDER' LIMIT 1"
            ).fetchone()
    else:
        if "xp" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CONTA XP' LIMIT 1"
            ).fetchone()
        if "nubank" in n or "nu " in n or "nu_" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CONTA NUBANK' LIMIT 1"
            ).fetchone()
        if "santander" in n:
            return conn.execute(
                "SELECT id,name,type,color FROM accounts WHERE name='CONTA SANTANDER' LIMIT 1"
            ).fetchone()
    return None


def detect_account_by_content(conn: sqlite3.Connection, path: Path):
    ext = path.suffix.lower()
    text = ""
    try:
        if ext == ".pdf" and PdfReader is not None:
            text = "\n".join(
                (p.extract_text() or "") for p in PdfReader(str(path)).pages[:3]
            )
        elif ext == ".csv":
            text = path.read_text(encoding="utf-8-sig", errors="ignore")[:12000]
        elif ext in (".xlsx", ".xls"):
            # Leitura tabular jÃ¡ padroniza texto suficiente para sinal de origem.
            sample_rows = load_transactions(path)[:40]
            text = "\n".join(f"{t.date} {t.description}" for t in sample_rows)
    except Exception:
        logger.warning(
            "Falha ao ler amostra para detectar origem de %s", path, exc_info=True
        )
        text = ""
    n = norm_text(text)
    if not n:
        return None
    is_statement = any(
        k in n
        for k in ("conta corrente", "extrato consolidado", "movimentacao", "saldo em")
    )
    is_card = any(
        k in n
        for k in (
            "fatura",
            "comprovante de fatura",
            "cartao final",
            "vencimento da fatura",
        )
    )
    if is_statement:
        is_card = False
    if "nubank" in n:
        name = "CARTAO NUBANK" if is_card else "CONTA NUBANK"
        return conn.execute(
            "SELECT id,name,type,color FROM accounts WHERE name=? LIMIT 1", (name,)
        ).fetchone()
    if "santander" in n:
        name = "CARTAO SANTANDER" if is_card else "CONTA SANTANDER"
        return conn.execute(
            "SELECT id,name,type,color FROM accounts WHERE name=? LIMIT 1", (name,)
        ).fetchone()
    if "xp invest" in n or "xp investimentos" in n or re.search(r"\bxp\b", n):
        name = "CARTAO XP" if is_card else "CONTA XP"
        return conn.execute(
            "SELECT id,name,type,color FROM accounts WHERE name=? LIMIT 1", (name,)
        ).fetchone()
    return None


def read_detection_sample(path: Path) -> str:
    """Le uma amostra do documento sem depender da conta selecionada."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf" and PdfReader is not None:
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:4])[
                :50000
            ]
        if ext == ".csv":
            raw = path.read_bytes()[:50000]
            for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
        if ext == ".xlsx" and openpyxl is not None:
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                sheet = workbook[workbook.sheetnames[0]]
                return "\n".join(
                    " ".join(str(value) for value in row if value is not None)
                    for row in sheet.iter_rows(max_row=60, values_only=True)
                )[:50000]
            finally:
                workbook.close()
        if ext == ".xls" and xlrd is not None:
            workbook = xlrd.open_workbook(path, on_demand=True)
            try:
                sheet = workbook.sheet_by_index(0)
                rows: list[str] = []
                for row_index in range(min(60, sheet.nrows)):
                    values: list[str] = []
                    for cell in sheet.row(row_index):
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value = (
                                xlrd.xldate_as_datetime(cell.value, workbook.datemode)
                                .date()
                                .isoformat()
                            )
                        else:
                            value = str(cell.value)
                        if value:
                            values.append(value)
                    rows.append(" ".join(values))
                return "\n".join(rows)[:50000]
            finally:
                workbook.release_resources()
    except Exception:
        logger.warning("Falha ao extrair amostra de %s", path, exc_info=True)
        return ""
    return ""


def detect_document_identity(
    path: Path, sample_text: str | None = None
) -> dict[str, Any]:
    """Infere banco e tipo usando nome e conteudo, com evidencias auditaveis."""
    filename = norm_text(path.name)
    content = norm_text(
        sample_text if sample_text is not None else read_detection_sample(path)
    )
    bank_scores = {"SANTANDER": 0, "XP": 0, "NUBANK": 0}
    kind_scores = {"credit_card": 0, "checking": 0}
    evidence: list[str] = []

    def add_bank(bank: str, points: int, reason: str) -> None:
        bank_scores[bank] += points
        evidence.append(reason)

    def add_kind(kind: str, points: int, reason: str) -> None:
        kind_scores[kind] += points
        evidence.append(reason)

    if "santander" in filename:
        add_bank("SANTANDER", 5, "Nome do arquivo menciona Santander")
    if re.search(r"\bxp\b", filename):
        add_bank("XP", 5, "Nome do arquivo menciona XP")
    if "nubank" in filename:
        add_bank("NUBANK", 5, "Nome do arquivo menciona Nubank")

    if "santander" in content:
        add_bank("SANTANDER", 5, "Conteudo identifica Santander")
    if "xp investimentos" in content or "xp invest" in content:
        add_bank("XP", 5, "Conteudo identifica XP Investimentos")
    elif re.search(r"\bxp\b", content[:12000]):
        add_bank("XP", 2, "Conteudo contem identificacao XP")
    if "nubank" in content:
        add_bank("NUBANK", 5, "Conteudo identifica Nubank")

    if any(term in filename for term in ("cartao", "fatura", "card")):
        add_kind("credit_card", 5, "Nome indica fatura de cartao")
    if "extrato" in filename or "statement" in filename:
        add_kind("checking", 5, "Nome indica extrato de conta")

    card_markers = (
        "detalhamento da fatura",
        "vencimento da fatura",
        "pagamento e demais creditos",
        "limite de credito",
        "data de compra",
        "nome no extrato",
    )
    statement_markers = (
        "extrato consolidado",
        "extrato de",
        "conta corrente",
        "saldo em",
        "saldo anterior",
        "movimentacao da conta",
    )
    card_hits = [marker for marker in card_markers if marker in content]
    statement_hits = [marker for marker in statement_markers if marker in content]
    if card_hits:
        add_kind(
            "credit_card",
            min(8, 2 + len(card_hits) * 2),
            f"Conteudo de fatura: {', '.join(card_hits[:3])}",
        )
    if statement_hits:
        add_kind(
            "checking",
            min(8, 2 + len(statement_hits) * 2),
            f"Conteudo de extrato: {', '.join(statement_hits[:3])}",
        )

    ranked_banks = sorted(bank_scores.items(), key=lambda item: item[1], reverse=True)
    ranked_kinds = sorted(kind_scores.items(), key=lambda item: item[1], reverse=True)
    bank, bank_score = ranked_banks[0]
    kind, kind_score = ranked_kinds[0]
    bank_margin = bank_score - ranked_banks[1][1]
    kind_margin = kind_score - ranked_kinds[1][1]

    if bank_score <= 0:
        bank = "DESCONHECIDO"
    if kind_score <= 0 or kind_margin == 0:
        kind = "desconhecido"

    confidence = 0.0
    if bank != "DESCONHECIDO" and kind != "desconhecido":
        confidence = min(
            0.99,
            0.45
            + min(bank_score, 10) * 0.025
            + min(kind_score, 10) * 0.025
            + min(bank_margin + kind_margin, 10) * 0.025,
        )

    account_name = ""
    if bank != "DESCONHECIDO" and kind != "desconhecido":
        account_name = f"{'CARTAO' if kind == 'credit_card' else 'CONTA'} {bank}"

    return {
        "bank": bank,
        "account_type": kind,
        "suggested_account_name": account_name,
        "confidence": round(confidence * 100.0, 2),
        "evidence": evidence,
        "scores": {"banks": bank_scores, "types": kind_scores},
    }


def detect_account_with_evidence(
    conn: sqlite3.Connection, path: Path, sample_text: str | None = None
) -> tuple[Any | None, dict[str, Any]]:
    detection = detect_document_identity(path, sample_text)
    account = None
    if detection["suggested_account_name"]:
        account = conn.execute(
            "SELECT id,name,type,color FROM accounts WHERE name=? LIMIT 1",
            (detection["suggested_account_name"],),
        ).fetchone()
    if account:
        detection["suggested_account_id"] = account[0]
    else:
        detection["suggested_account_id"] = ""
    return account, detection


def suggest_for_desc(conn: sqlite3.Connection, dnorm: str, tx_type: str = "expense"):
    row = conn.execute(
        """
        SELECT h.category_id, h.subcategory_id, COUNT(*) c
        FROM classification_history h
        WHERE h.description_norm=? AND h.category_id IS NOT NULL AND h.type=?
        GROUP BY h.category_id, h.subcategory_id
        ORDER BY c DESC
        LIMIT 1
        """,
        (dnorm, tx_type),
    ).fetchone()
    if row:
        return row[0], row[1]

    row = conn.execute(
        """
        SELECT category_id, subcategory_id, COUNT(*) c
        FROM transactions
        WHERE description_norm=? AND category_id IS NOT NULL AND type=?
        GROUP BY category_id, subcategory_id
        ORDER BY c DESC
        LIMIT 1
        """,
        (dnorm, tx_type),
    ).fetchone()
    if row:
        return row[0], row[1]

    ranked = build_scored_evidence(
        conn,
        {
            "description_norm": dnorm,
            "amount": 0,
            "date": "",
            "type": tx_type,
            "account_id": None,
        },
        None,
        include_transactions=False,
        include_history=True,
    )
    if ranked and float(ranked[0].get("best_score") or 0) >= 0.40:
        best = ranked[0]
        return best["category_id"], best.get("subcategory_id")
    return None, None


def detect_file_type(filename: str, account_name: str) -> tuple[str, float]:
    n = norm_text(filename)
    acc = (account_name or "").upper()
    if "SANTANDER" in acc:
        bank = "SANTANDER"
    elif "XP" in acc:
        bank = "XP"
    elif "NUBANK" in acc:
        bank = "NUBANK"
    else:
        bank = "DESCONHECIDO"
    kind = "CARTAO" if "CARTAO" in acc else "EXTRATO"
    detected = f"{kind} {bank}"
    confidence = 0.7
    if bank != "DESCONHECIDO" and bank.lower() in n:
        confidence += 0.2
    if kind == "CARTAO" and any(k in n for k in ("cartao", "fatura", "comprovante")):
        confidence += 0.1
    if kind == "EXTRATO" and "extrato" in n:
        confidence += 0.1
    return detected, min(0.99, confidence)


def scan_source_metadata(path: Path, root: Path) -> dict[str, Any]:
    rel_parts = path.relative_to(root).parts if root in path.parents else path.parts
    text = norm_text(" ".join(rel_parts))
    year = ""
    month = ""
    source_kind = "desconhecido"
    bank = "desconhecido"

    for part in rel_parts:
        if re.fullmatch(r"20\d{2}", str(part)):
            year = str(part)
            break
    for part in rel_parts:
        m = re.match(r"(\d{2})", str(part))
        if m and 1 <= int(m.group(1)) <= 12:
            month = m.group(1)
            break

    if "cartao" in text or "cartoes" in text or "fatura" in text:
        source_kind = "cartao"
    elif "extrato" in text or "extratos" in text or "conta" in text:
        source_kind = "extrato"

    if "santander" in text:
        bank = "SANTANDER"
    elif "nubank" in text:
        bank = "NUBANK"
    elif re.search(r"\bxp\b", text):
        bank = "XP"
    elif "smartek" in text or "smtk" in text:
        bank = "SMARTEK"
    elif "sulivan" in text:
        bank = "SULIVAN"

    return {"year": year, "month": month, "source_kind": source_kind, "bank": bank}


def import_metadata_from_account(path: Path, account_name: str) -> dict[str, Any]:
    meta = scan_source_metadata(path, path.parent)
    acc = norm_text(account_name)
    if "cartao" in acc:
        meta["source_kind"] = "cartao"
    elif "conta" in acc:
        meta["source_kind"] = "extrato"
    if "santander" in acc:
        meta["bank"] = "SANTANDER"
    elif "nubank" in acc:
        meta["bank"] = "NUBANK"
    elif re.search(r"\bxp\b", acc):
        meta["bank"] = "XP"
    elif "smartek" in acc or "smtk" in acc:
        meta["bank"] = "SMARTEK"
    elif "sulivan" in acc:
        meta["bank"] = "SULIVAN"
    return meta


def competence_from_filename(filename: str) -> str:
    clean = strip_accents(filename).lower()
    matches = re.findall(r"(?<!\d)(\d{1,2})\s*[-_/]\s*(\d{2})(?!\d)", clean)
    valid = [
        (int(month), 2000 + int(year))
        for month, year in matches
        if 1 <= int(month) <= 12 and 20 <= int(year) <= 40
    ]
    if not valid:
        return ""
    month, year = valid[-1]
    return f"{year:04d}/{month:02d}"


def declared_statement_competence(path: Path, sample_text: str | None = None) -> str:
    sample = sample_text if sample_text is not None else read_detection_sample(path)
    text = re.sub(r"\s+", " ", strip_accents(sample).lower())
    range_patterns = (
        r"(?:periodo(?: de)?|extrato de)\s*(\d{2}/\d{2}/20\d{2})\s*(?:a|ate|-)\s*(\d{2}/\d{2}/20\d{2})",
        r"(?:periodo|periodo de|extrato de)\D{0,30}(\d{2}/\d{2}/20\d{2})\D{1,20}(\d{2}/\d{2}/20\d{2})",
    )
    for pattern in range_patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            end = dt.datetime.strptime(match.group(2), "%d/%m/%Y").date()
            return end.strftime("%Y/%m")
        except ValueError:
            continue

    month_names = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    title = re.search(
        r"(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s*[/ -]\s*(20\d{2})",
        text[:12000],
    )
    if title:
        return f"{int(title.group(2)):04d}/{month_names[title.group(1)]:02d}"
    return ""


def declared_card_payment_competence(
    path: Path, sample_text: str | None = None
) -> tuple[str, str]:
    """Retorna a competencia da fatura pela data declarada de pagamento/vencimento."""
    sample = sample_text if sample_text is not None else read_detection_sample(path)
    text = re.sub(r"\s+", " ", strip_accents(sample).lower())
    labels = (
        ("data de pagamento", "Data de pagamento da fatura"),
        ("data de vencimento", "Vencimento da fatura"),
        ("vencimento da fatura", "Vencimento da fatura"),
        ("vencimento", "Vencimento da fatura"),
    )
    for label, evidence_label in labels:
        match = re.search(
            rf"\b{re.escape(label)}\b\D{{0,30}}(\d{{2}}/\d{{2}}/20\d{{2}}|20\d{{2}}-\d{{2}}-\d{{2}})",
            text,
        )
        if not match:
            continue
        raw_date = match.group(1)
        for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                payment_date = dt.datetime.strptime(raw_date, date_format).date()
                return payment_date.strftime(
                    "%Y/%m"
                ), f"{evidence_label}: {payment_date.strftime('%d/%m/%Y')}"
            except ValueError:
                continue
    return "", ""


def detect_competence(
    path: Path, txs: list[Any] | None, account_type: str, sample_text: str | None = None
) -> dict[str, Any]:
    filename_month = competence_from_filename(path.name)
    declared_month = (
        declared_statement_competence(path, sample_text)
        if account_type != "credit_card"
        else ""
    )
    card_payment_month, card_payment_evidence = (
        declared_card_payment_competence(path, sample_text)
        if account_type == "credit_card"
        else ("", "")
    )
    evidence: list[str] = []
    warning = ""
    valid_dates: list[str] = []
    for tx in txs or []:
        value = getattr(tx, "date", "") or ""
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            valid_dates.append(value)

    if filename_month:
        evidence.append(f"Nome do arquivo indica {filename_month}")
    if declared_month:
        evidence.append(f"Periodo declarado no documento indica {declared_month}")

    if account_type == "credit_card":
        if card_payment_month:
            evidence.append(card_payment_evidence)
            if filename_month and filename_month != card_payment_month:
                warning = f"Data de pagamento/vencimento ({card_payment_month}) difere do nome do arquivo ({filename_month})."
            return {
                "month": card_payment_month,
                "confidence": 98.0,
                "strategy": "card_payment_date",
                "evidence": evidence,
                "warning": warning,
            }
        if filename_month:
            return {
                "month": filename_month,
                "confidence": 70.0,
                "strategy": "card_filename",
                "evidence": evidence,
                "warning": "Data de pagamento/vencimento da fatura nao encontrada; confirme a competencia sugerida pelo nome do arquivo.",
            }
        return {
            "month": "",
            "confidence": 0.0,
            "strategy": "unknown",
            "evidence": evidence,
            "warning": "Data de pagamento/vencimento da fatura nao encontrada. Informe a competencia manualmente.",
        }

    month_counts: dict[str, int] = {}
    for value in valid_dates:
        key = value[:7].replace("-", "/")
        month_counts[key] = month_counts.get(key, 0) + 1
    if month_counts:
        dominant, count = sorted(
            month_counts.items(), key=lambda item: (item[1], item[0]), reverse=True
        )[0]
        share = count / max(1, len(valid_dates))
        evidence.append(
            f"Mes predominante nos lancamentos: {dominant} ({share * 100:.0f}%)"
        )
        if declared_month:
            if declared_month != dominant and share >= 0.60:
                warning = f"Periodo declarado ({declared_month}) difere do mes predominante ({dominant})."
            elif filename_month and filename_month != declared_month:
                warning = f"Periodo declarado ({declared_month}) difere do nome do arquivo ({filename_month})."
            return {
                "month": declared_month,
                "confidence": 98.0,
                "strategy": "statement_declared_period",
                "evidence": evidence,
                "warning": warning,
            }
        if filename_month == dominant:
            return {
                "month": dominant,
                "confidence": 98.0,
                "strategy": "statement_filename_and_transactions",
                "evidence": evidence,
                "warning": "",
            }
        if filename_month and share < 0.60:
            evidence.append(
                "Distribuicao de datas nao contradiz de forma forte o nome do arquivo"
            )
            return {
                "month": filename_month,
                "confidence": 82.0,
                "strategy": "statement_filename",
                "evidence": evidence,
                "warning": "",
            }
        if filename_month and filename_month != dominant:
            warning = f"Mes predominante ({dominant}) difere do nome do arquivo ({filename_month})."
        return {
            "month": dominant,
            "confidence": round(75.0 + min(20.0, share * 20.0), 2),
            "strategy": "statement_transactions",
            "evidence": evidence,
            "warning": warning,
        }

    if declared_month:
        return {
            "month": declared_month,
            "confidence": 90.0,
            "strategy": "statement_declared_period",
            "evidence": evidence,
            "warning": "Nao foi possivel confirmar o periodo pelas datas lidas.",
        }
    if filename_month:
        return {
            "month": filename_month,
            "confidence": 70.0,
            "strategy": "filename_only",
            "evidence": evidence,
            "warning": "Nao foi possivel confirmar a competencia pelas datas lidas.",
        }
    return {
        "month": "",
        "confidence": 0.0,
        "strategy": "unknown",
        "evidence": evidence,
        "warning": "Competencia nao detectada.",
    }


def existing_db_duplicate_count(
    conn: sqlite3.Connection,
    account_id: str,
    row: dict[str, Any],
    competence_month: str = "",
    card_statement: bool = False,
) -> int:
    installment_current = int(row.get("installment_current") or 0)
    installment_total = int(row.get("installment_total") or 0)
    competence_filter = " AND competence_month=?" if competence_month else ""
    params = [
        account_id,
        row["date"],
        row["amount_signed"],
        row["description_norm"],
        row["tx_type"],
        installment_current,
        installment_total,
    ]
    if competence_month:
        params.append(competence_month)
    if card_statement:
        candidates = conn.execute(
            f"""
            SELECT description_norm FROM transactions
            WHERE account_id=?
              AND date=?
              AND ROUND(amount,2)=?
              AND type=?
              AND IFNULL(installment_current,0)=?
              AND IFNULL(installment_total,0)=?
              {competence_filter}
            """,
            tuple(
                [
                    account_id,
                    row["date"],
                    row["amount_signed"],
                    row["tx_type"],
                    installment_current,
                    installment_total,
                ]
                + ([competence_month] if competence_month else [])
            ),
        ).fetchall()
        target_description = import_dedupe_description(row["description_norm"])
        return sum(
            import_dedupe_description(candidate[0]) == target_description
            for candidate in candidates
        )
    return int(
        conn.execute(
            f"""
        SELECT COUNT(1) FROM transactions
        WHERE account_id=?
          AND date=?
          AND ROUND(amount,2)=?
          AND description_norm=?
          AND type=?
          AND IFNULL(installment_current,0)=?
          AND IFNULL(installment_total,0)=?
          {competence_filter}
        """,
            tuple(params),
        ).fetchone()[0]
        or 0
    )


def import_dedupe_description(value: str) -> str:
    """Compara descrições de cartão sem repetir a parcela já estruturada."""
    normalized = norm_text(value)
    normalized = re.sub(r"\bparcela\s+\d+\s+(?:de\s+)?\d+\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def existing_db_duplicate_count_for_rows(
    conn: sqlite3.Connection, account_id: str, rows: list[dict[str, Any]]
) -> int:
    db_counts = {
        r["sig"]: existing_db_duplicate_count(conn, account_id, r) for r in rows
    }
    occurrences: dict[tuple[Any, ...], int] = {}
    duplicates = 0
    for row in rows:
        sig = row["sig"]
        occurrences[sig] = occurrences.get(sig, 0) + 1
        if occurrences[sig] <= db_counts.get(sig, 0):
            duplicates += 1
    return duplicates


def add_csv_flag(flags_text: str, flag: str) -> str:
    flags = [part for part in (flags_text or "").split(",") if part]
    if flag not in flags:
        flags.append(flag)
    return ",".join(flags)


def installment_members_are_compatible(
    existing_date: str,
    existing_current: int,
    new_date: str,
    new_current: int,
) -> bool:
    """Aceita datas originais repetidas ou a progressao mensal das parcelas."""
    if existing_date == new_date:
        return True
    try:
        old = dt.date.fromisoformat(existing_date)
        new = dt.date.fromisoformat(new_date)
    except (TypeError, ValueError):
        return False
    month_delta = (new.year - old.year) * 12 + new.month - old.month
    installment_delta = int(new_current) - int(existing_current)
    return month_delta == installment_delta and abs(new.day - old.day) <= 7


def find_or_create_installment_plan(
    conn: sqlite3.Connection,
    account_id: str,
    row: dict[str, Any],
) -> tuple[str | None, tuple[Any, ...] | None]:
    """Vincula somente quando existe um unico plano compativel; ambiguidade cria outro."""
    current = int(row.get("installment_current") or 0)
    total = int(row.get("installment_total") or 0)
    if current <= 0 or total <= 1:
        return None, None

    amount = round(abs(float(row.get("amount_signed") or 0)), 2)
    plans = conn.execute(
        """
        SELECT id,category_id,subcategory_id,classified_by,classified_at
        FROM installment_plans
        WHERE account_id=? AND description_norm=? AND installment_total=?
          AND ROUND(installment_amount,2)=?
        """,
        (account_id, row["description_norm"], total, amount),
    ).fetchall()
    compatible: list[tuple[Any, ...]] = []
    for plan in plans:
        members = conn.execute(
            "SELECT date,installment_current FROM transactions WHERE installment_plan_id=?",
            (plan[0],),
        ).fetchall()
        if any(int(member[1] or 0) == current for member in members):
            continue
        if any(
            installment_members_are_compatible(
                member[0], int(member[1] or 0), row["date"], current
            )
            for member in members
        ):
            compatible.append(plan)

    if len(compatible) == 1:
        return compatible[0][0], compatible[0]

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    plan_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO installment_plans(
          id,account_id,description,description_norm,installment_total,installment_amount,
          first_seen_date,category_id,subcategory_id,classified_by,classified_at,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            plan_id,
            account_id,
            row["description"],
            row["description_norm"],
            total,
            amount,
            row["date"],
            None,
            None,
            "",
            "",
            now,
            now,
        ),
    )
    return plan_id, None


def build_import_preview(
    path: Path, acc: tuple[Any, ...], detection_sample: str | None = None
) -> dict[str, Any]:
    account_name = acc[1] or ""
    account_type = (acc[2] or "checking").lower()
    result: ImportResult = run_import_pipeline(path, account_name, account_type)

    parsed_rows: list[dict[str, Any]] = []
    internal_counter: dict[tuple[Any, ...], int] = {}
    for t in result.txs:
        display_desc = (
            f"{t.description} ({t.installment_label})"
            if t.installment_label
            else t.description
        )
        flags_text = ",".join(t.flags)
        if account_type == "credit_card" and abs(float(t.amount_signed or 0)) < 2.0:
            flags_text = add_csv_flag(flags_text, "non_count")
        sig = (
            t.date,
            round(float(t.amount_signed or 0), 2),
            t.description_norm,
            t.tx_type,
            t.installment_current or 0,
            t.installment_total or 0,
            flags_text,
        )
        internal_counter[sig] = internal_counter.get(sig, 0) + 1
        parsed_rows.append(
            {
                "date": t.date,
                "description": display_desc,
                "description_norm": t.description_norm,
                "amount_signed": round(float(t.amount_signed or 0), 2),
                "tx_type": t.tx_type,
                "installment_current": t.installment_current,
                "installment_total": t.installment_total,
                "installment_label": t.installment_label,
                "is_installment": t.is_installment,
                "flags": flags_text,
                "sig": sig,
            }
        )

    competence = detect_competence(path, result.txs, account_type, detection_sample)
    warnings = list(result.warnings)
    if (
        account_type != "credit_card"
        and len(parsed_rows) < 15
        and not result.empty_statement_confirmed
    ):
        warnings.append(
            f"Atencao: o extrato gerou somente {len(parsed_rows)} lancamento(s). Revise a pre-visualizacao antes de importar."
        )
    if competence["warning"]:
        warnings.append(competence["warning"])

    return {
        "txs": result.txs,
        "parsed_rows": parsed_rows,
        "internal_counter": internal_counter,
        "warnings": warnings,
        "balance_check": {
            "ok": result.balance_check.ok,
            "message": result.balance_check.message,
            "saldo_anterior": result.balance_check.saldo_anterior,
            "saldo_final_declarado": result.balance_check.saldo_final_declarado,
            "saldo_calculado": result.balance_check.saldo_calculado,
            "diferenca": result.balance_check.diferenca,
        },
        "import_meta": {
            "bank": result.format_detection.bank,
            "doc_type": result.format_detection.doc_type,
            "file_format": result.format_detection.file_format,
            "encoding": result.format_detection.encoding,
            "detection_confidence": result.format_detection.confidence,
            "suggested_competence_month": competence["month"],
            "competence_confidence": competence["confidence"],
            "competence_strategy": competence["strategy"],
            "competence_evidence": competence["evidence"],
            "competence_warning": competence["warning"],
            "total_installments": result.total_installments,
            "total_inter_account": result.total_inter_account,
            "total_cashback": result.total_cashback,
            "total_discarded": len(result.discarded_lines),
            "empty_statement_confirmed": result.empty_statement_confirmed,
        },
        "rejected_lines": result.rejected_lines,
        "discarded_lines": result.discarded_lines,
    }


def load_suggestion_evidence(conn) -> dict[str, list[tuple[Any, ...]]]:
    evidence: dict[str, list[tuple[Any, ...]]] = {"expense": [], "income": []}
    rows = conn.execute(
        """
        SELECT t.type,t.category_id,c.name,t.subcategory_id,IFNULL(s.name,''),
               t.date,t.description_norm,ABS(t.amount),t.account_id,t.notes,'transaction'
        FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        LEFT JOIN subcategories s ON s.id=t.subcategory_id
        WHERE t.category_id IS NOT NULL
        UNION ALL
        SELECT h.type,h.category_id,c.name,h.subcategory_id,IFNULL(s.name,''),
               h.date,h.description_norm,ABS(h.amount),h.account_id,'','history'
        FROM classification_history h
        LEFT JOIN categories c ON c.id=h.category_id
        LEFT JOIN subcategories s ON s.id=h.subcategory_id
        WHERE h.source_file_id NOT LIKE 'manual:%'
        """
    ).fetchall()
    for row in rows:
        evidence.setdefault(row[0] or "", []).append(tuple(row[1:]))
    return evidence


def build_suggestions_for_tx(
    conn: sqlite3.Connection,
    tx_id: str,
    evidence_by_type: dict[str, list[tuple[Any, ...]]] | None = None,
):
    tx_row = conn.execute(
        """
        SELECT id, date, description, description_norm, amount, type, account_id
        FROM transactions
        WHERE id=?
        """,
        (tx_id,),
    ).fetchone()
    if not tx_row:
        return None
    tx = {
        "id": tx_row[0],
        "date": tx_row[1],
        "description": tx_row[2],
        "description_norm": tx_row[3],
        "amount": tx_row[4],
        "type": tx_row[5],
        "account_id": tx_row[6],
    }
    ranked = build_scored_evidence(
        conn,
        tx,
        tx_id,
        include_transactions=True,
        include_history=True,
        evidence_rows=evidence_by_type.get(tx["type"], [])
        if evidence_by_type is not None
        else None,
    )
    if not ranked:
        return []
    return [
        {
            "category_id": r["category_id"],
            "category_name": r["category_name"] or "",
            "subcategory_id": r.get("subcategory_id"),
            "subcategory_name": r.get("subcategory_name") or "",
            "best_notes": r.get("best_notes") or "",
            "probability": round(float(r["probability"]), 2),
            "relative_score": round(float(r["probability"]), 2),
            "confidence": round(float(r.get("confidence", 0.0)), 2),
            "category_probability": round(
                float(r.get("category_probability", r["probability"])), 2
            ),
            "subcategory_probability": round(
                float(r.get("subcategory_probability", 0.0)), 2
            ),
            "subcategories": r.get("subcategories") or [],
            "frequency": int(r.get("frequency", 0)),
            "history_evidence": int(r.get("history_evidence", 0)),
            "transaction_evidence": int(r.get("transaction_evidence", 0)),
            "justification": (
                f"{int(r.get('frequency', 0))} evidencia(s) semelhante(s): "
                f"{int(r.get('history_evidence', 0))} da base historica e "
                f"{int(r.get('transaction_evidence', 0))} de lancamentos classificados."
            ),
        }
        for r in ranked[:12]
        if float(r.get("category_probability", r.get("probability", 0.0))) >= 20.0
    ]


def evaluate_suggestion_quality(
    conn: sqlite3.Connection,
    limit: int = 250,
    target_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Avalia o motor contra classificacoes conhecidas sem usar o alvo como evidencia."""
    safe_limit = max(1, min(int(limit or 250), 1000))
    eligible_rows = conn.execute(
        """
        SELECT id,category_id,subcategory_id,type
        FROM transactions
        WHERE category_id IS NOT NULL
          AND COALESCE(history_match_confirmed,0)=0
          AND COALESCE(status,'') NOT IN ('duplicate','ignored')
        ORDER BY date DESC,id
        """
    ).fetchall()
    if target_ids is not None:
        requested = set(target_ids)
        eligible_rows = [row for row in eligible_rows if row[0] in requested]
    eligible_total = len(eligible_rows)
    rows = eligible_rows[:safe_limit]

    calibration_ranges = (
        (0.0, 50.0, "0-49%"),
        (50.0, 70.0, "50-69%"),
        (70.0, 85.0, "70-84%"),
        (85.0, 101.0, "85-100%"),
    )
    calibration = {
        label: {"range": label, "count": 0, "correct": 0, "confidence_sum": 0.0}
        for _, _, label in calibration_ranges
    }
    by_type: dict[str, dict[str, int]] = {}
    with_suggestions = category_top1 = category_top3 = 0
    subcategory_labeled = subcategory_evaluated = subcategory_top1 = (
        subcategory_top3
    ) = 0

    for tx_id, expected_category, expected_subcategory, tx_type in rows:
        type_metrics = by_type.setdefault(
            tx_type or "unknown",
            {"evaluated": 0, "with_suggestions": 0, "top1_hits": 0, "top3_hits": 0},
        )
        type_metrics["evaluated"] += 1
        if expected_subcategory:
            subcategory_labeled += 1

        # Nao reutiliza o cache em lote: a consulta individual exclui tx_id das
        # evidencias e torna a medicao retrospectiva um verdadeiro leave-one-out.
        suggestions = build_suggestions_for_tx(conn, tx_id) or []
        if not suggestions:
            continue
        top_categories = suggestions[:3]
        with_suggestions += 1
        type_metrics["with_suggestions"] += 1
        top1_correct = top_categories[0]["category_id"] == expected_category
        top3_correct = any(
            item["category_id"] == expected_category for item in top_categories
        )
        if top1_correct:
            category_top1 += 1
            type_metrics["top1_hits"] += 1
        if top3_correct:
            category_top3 += 1
            type_metrics["top3_hits"] += 1

        confidence = float(top_categories[0].get("confidence") or 0.0)
        for lower, upper, label in calibration_ranges:
            if lower <= confidence < upper:
                bucket = calibration[label]
                bucket["count"] += 1
                bucket["correct"] += int(top1_correct)
                bucket["confidence_sum"] += confidence
                break

        if expected_subcategory:
            expected_category_suggestion = next(
                (
                    item
                    for item in suggestions
                    if item["category_id"] == expected_category
                ),
                None,
            )
            if expected_category_suggestion:
                subcategory_evaluated += 1
                subcategory_ids: list[str] = []
                for candidate in (
                    expected_category_suggestion.get("subcategories") or []
                ):
                    candidate_id = candidate.get("subcategory_id")
                    if candidate_id and candidate_id not in subcategory_ids:
                        subcategory_ids.append(candidate_id)
                if subcategory_ids and subcategory_ids[0] == expected_subcategory:
                    subcategory_top1 += 1
                if expected_subcategory in subcategory_ids[:3]:
                    subcategory_top3 += 1

    def percent(numerator: int, denominator: int) -> float:
        return round((numerator / denominator) * 100.0, 2) if denominator else 0.0

    calibration_items = []
    for _, _, label in calibration_ranges:
        bucket = calibration[label]
        count = int(bucket["count"])
        calibration_items.append(
            {
                "range": label,
                "count": count,
                "accuracy": percent(int(bucket["correct"]), count),
                "average_confidence": round(float(bucket["confidence_sum"]) / count, 2)
                if count
                else 0.0,
            }
        )

    type_items = []
    for tx_type, metrics in sorted(by_type.items()):
        suggested = metrics["with_suggestions"]
        type_items.append(
            {
                "type": tx_type,
                **metrics,
                "coverage": percent(suggested, metrics["evaluated"]),
                "top1_accuracy": percent(metrics["top1_hits"], suggested),
                "top3_accuracy": percent(metrics["top3_hits"], suggested),
            }
        )

    evaluated = len(rows)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "eligible_total": eligible_total,
        "evaluated": evaluated,
        "limit": safe_limit,
        "truncated": eligible_total > evaluated,
        "with_suggestions": with_suggestions,
        "coverage": percent(with_suggestions, evaluated),
        "category": {
            "top1_hits": category_top1,
            "top3_hits": category_top3,
            "top1_accuracy": percent(category_top1, with_suggestions),
            "top3_accuracy": percent(category_top3, with_suggestions),
        },
        "subcategory": {
            "labeled": subcategory_labeled,
            "evaluated": subcategory_evaluated,
            "top1_hits": subcategory_top1,
            "top3_hits": subcategory_top3,
            "top1_accuracy": percent(subcategory_top1, subcategory_evaluated),
            "top3_accuracy": percent(subcategory_top3, subcategory_evaluated),
        },
        "calibration": calibration_items,
        "by_type": type_items,
        "methodology": "leave-one-out; vinculos historicos confirmados nao entram como gabarito",
    }


def find_category_id(conn: sqlite3.Connection, name: str):
    cname = (name or "").strip()
    if not cname:
        return None
    row = conn.execute(
        "SELECT id FROM categories WHERE UPPER(name)=UPPER(?) LIMIT 1",
        (cname,),
    ).fetchone()
    if row:
        return row[0]
    cat_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO categories(id,name,color,text_color,type) VALUES (?,?,?,?,?)",
        (cat_id, cname.upper(), "#334155", "#ffffff", "hybrid"),
    )
    return cat_id


def find_or_create_subcategory(conn: sqlite3.Connection, name: str):
    sname = (name or "").strip()
    if not sname:
        return None
    target = sname.upper()
    row = conn.execute(
        "SELECT id FROM subcategories WHERE lower(name)=lower(?) LIMIT 1", (target,)
    ).fetchone()
    if row:
        return row[0]
    sid = str(uuid.uuid4())
    # ON CONFLICT funciona igual em SQLite (3.24+) e Postgres, evitando erro de
    # duplicidade em concorrencia sem abortar a transacao no Postgres.
    conn.execute(
        "INSERT INTO subcategories(id,name) VALUES (?,?) ON CONFLICT(name) DO NOTHING",
        (sid, target),
    )
    row = conn.execute(
        "SELECT id FROM subcategories WHERE name=? LIMIT 1", (target,)
    ).fetchone()
    return row[0] if row else sid


def is_unknown_historical_account_label(value: Any) -> bool:
    return norm_text(str(value or "")) in UNKNOWN_HISTORICAL_ACCOUNT_LABELS


def is_legacy_sulivan_account_label(value: Any) -> bool:
    return "sulivan" in norm_text(str(value or ""))


def normalize_legacy_account_aliases(conn: sqlite3.Connection) -> dict[str, int]:
    """Corrige contas criadas indevidamente a partir da planilha historica."""
    result = {
        "history_without_account": 0,
        "sulivan_migrated": 0,
        "accounts_removed": 0,
    }
    accounts = conn.execute("SELECT id,name FROM accounts").fetchall()
    santander = next(
        (row for row in accounts if norm_text(row[1]) == "cartao santander"), None
    )
    unknown = [row for row in accounts if is_unknown_historical_account_label(row[1])]
    sulivan = [row for row in accounts if is_legacy_sulivan_account_label(row[1])]

    for account_id, _account_name in unknown:
        history_count = conn.execute(
            "SELECT COUNT(1) FROM classification_history WHERE account_id=?",
            (account_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE classification_history SET account_id=NULL WHERE account_id=?",
            (account_id,),
        )
        conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (account_id,))
        result["history_without_account"] += int(history_count or 0)

    if santander:
        santander_id = santander[0]
        for account_id, _account_name in sulivan:
            history_count = conn.execute(
                "SELECT COUNT(1) FROM classification_history WHERE account_id=?",
                (account_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE classification_history SET account_id=? WHERE account_id=?",
                (santander_id, account_id),
            )
            result["sulivan_migrated"] += int(history_count or 0)

    referenced_tables = (
        "transactions",
        "installment_plans",
        "imported_files",
        "import_previews",
        "account_file_coverage",
    )
    for account_id, _account_name in unknown + sulivan:
        if all(
            int(
                conn.execute(
                    f"SELECT COUNT(1) FROM {table} WHERE account_id=?", (account_id,)
                ).fetchone()[0]
                or 0
            )
            == 0
            for table in referenced_tables
        ):
            conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            result["accounts_removed"] += 1
    return result


def resolve_account_from_text(conn: sqlite3.Connection, raw: str):
    n = norm_text(raw or "")
    if n in UNKNOWN_HISTORICAL_ACCOUNT_LABELS:
        return None
    if "sulivan" in n:
        name = "CARTAO SANTANDER"
    elif "smartek" in n or "smtk" in n:
        name = "CONTA SMARTEK"
    elif "nubank" in n:
        name = "CARTAO NUBANK" if "cart" in n or "fatura" in n else "CONTA NUBANK"
    elif "santander" in n:
        name = "CARTAO SANTANDER" if "cart" in n or "fatura" in n else "CONTA SANTANDER"
    elif "xp" in n:
        name = "CARTAO XP" if "cart" in n or "fatura" in n else "CONTA XP"
    else:
        name = clean_label(raw)
    if not name:
        return None
    rows = conn.execute("SELECT id,name,type,color FROM accounts").fetchall()
    for row in rows:
        if norm_text(row[1]) == norm_text(name):
            return row
    acc_type = "credit_card" if "cartao" in norm_text(name) else "checking"
    color = "#7c3aed" if acc_type == "credit_card" else "#2563eb"
    acc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES (?,?,?,?,?,?)",
        (
            acc_id,
            name,
            acc_type,
            color,
            1,
            dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return (acc_id, name, acc_type, color)


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper()


def seed_type_for_row(
    sheet_type: str | None, cat_raw: Any, amount: float | None = None
) -> str | None:
    if sheet_type:
        return sheet_type
    cat = norm_text(cat_raw or "")
    if any(k in cat for k in ("smartek", "smtk")):
        if amount is None:
            return "expense"
        return "income" if amount < 0 else "expense"
    if any(
        k in cat
        for k in ("deposito", "retirada", "reembolso", "acerto", "venda", "pro labore")
    ):
        return "income"
    if cat:
        return "expense"
    return None


def smartek_seed_subcategory(
    tx_type: str, desc_raw: Any, cat_raw: Any, notes_raw: Any
) -> str:
    desc_notes = norm_text(f"{desc_raw or ''} {notes_raw or ''}")
    cat = norm_text(cat_raw or "")
    text = f"{desc_notes} {cat}".strip()
    if tx_type == "income":
        if "juros" in text or "2" in text and "capital" in text:
            return "JUROS 2%"
        if "devol" in text or "retirada" in text or "receb" in text:
            return "DEVOLUCAO CAPITAL"
        return "REEMBOLSO"
    if "emprest" in text or "deposito" in cat or "smtk" in cat:
        return "EMPRESTIMO"
    if "aporte" in text:
        return "APORTE"
    return "PAGAMENTO POR CONTA DA EMPRESA"


def move_duplicate_history_to_smartek_sheet(
    conn: sqlite3.Connection,
    smartek_account_id: str | None,
    smartek_source_id: str,
    smartek_category_id: str,
    smartek_subcategory_id: str | None,
    date: str,
    description_norm: str,
    amount: float,
    tx_type: str,
) -> int:
    if not smartek_account_id:
        return 0
    cur = conn.execute(
        """
        UPDATE classification_history
        SET source_file_id=?,
            account_id=?,
            category_id=?,
            subcategory_id=?
        WHERE source_file_id NOT LIKE '%:sheet:helcio_smartek'
          AND date=?
          AND description_norm=?
          AND ROUND(amount, 2)=ROUND(?, 2)
          AND type=?
        """,
        (
            smartek_source_id,
            smartek_account_id,
            smartek_category_id,
            smartek_subcategory_id,
            date,
            description_norm,
            abs(float(amount or 0)),
            tx_type,
        ),
    )
    return cur.rowcount or 0


def history_sheet_key(sheet_name: str) -> str:
    normalized = normalize_history_label(sheet_name)
    if normalized == "saidas":
        return "saidas"
    if normalized == "entradas":
        return "entradas"
    if normalized in {"helcio_smartek", "smartek"}:
        return "helcio_smartek"
    return normalized or "historico"


def import_seed_workbook(
    path: Path, progress=None, imported_file_id: str | None = None
):
    if openpyxl is None:
        raise RuntimeError("openpyxl nao encontrado")
    wb = openpyxl.load_workbook(path, data_only=True)
    wanted = {
        "saidas": "expense",
        "entradas": "income",
        "helcio_smartek": None,
        "smartek": None,
    }
    now = dt.datetime.now().isoformat(timespec="seconds")
    imported_file_id = imported_file_id or str(uuid.uuid4())
    total_parsed = 0
    total_inserted = 0
    total_duplicates = 0

    sheets_found = [ws.title for ws in wb.worksheets]
    total_rows = sum(
        max(0, ws.max_row - 1)
        for ws in wb.worksheets
        if normalize_history_label(ws.title) in wanted
    )
    processed_rows = 0
    if progress:
        progress(
            "reading", 0, total_rows, f"Planilha aberta: {len(wb.worksheets)} aba(s)"
        )
    sheets_recognized: list[str] = []
    with db_connect() as conn:
        for ws in wb.worksheets:
            sname = normalize_history_label(ws.title)
            if sname not in wanted:
                continue
            sheets_recognized.append(ws.title)
            if progress:
                progress(
                    "importing",
                    processed_rows,
                    total_rows,
                    f"Processando aba {ws.title}",
                )
            sheet_type = wanted.get(sname)
            sheet_source_id = f"{imported_file_id}:sheet:{history_sheet_key(ws.title)}"
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue
            header_idx = 0
            score = -1
            for i, row in enumerate(rows[:30]):
                idx = map_headers(row)
                s = sum(
                    1
                    for k in (
                        "data",
                        "descricao",
                        "historico",
                        "valor",
                        "categoria",
                        "subcategoria",
                    )
                    if k in idx
                )
                if s > score:
                    header_idx, score = i, s
            idx = map_headers(rows[header_idx])
            is_smartek_sheet = sname in {"helcio_smartek", "smartek"}
            for row in rows[header_idx + 1 :]:
                processed_rows += 1
                if processed_rows % 100 == 0:
                    conn.commit()
                    if progress:
                        progress(
                            "importing",
                            processed_rows,
                            total_rows,
                            f"{total_inserted} inseridos, {total_duplicates} duplicados",
                        )
                date_raw = row_get(row, idx, ["data", "date", "dia"])
                desc_raw = row_get(
                    row, idx, ["descricao", "historico", "estabelecimento"]
                )
                value_raw = row_get(row, idx, ["valor", "value", "total"])
                cat_raw = row_get(
                    row, idx, ["categoria", "centro_de_custo", "centro_custo"]
                )
                sub_raw = row_get(row, idx, ["subcategoria", "sub_categoria"])
                notes_raw = row_get(
                    row, idx, ["observacao", "observacoes", "obs", "nota"]
                )
                account_raw = row_get(
                    row, idx, ["forma", "conta", "cartao", "cartÃ£o", "banco"]
                )
                d = parse_date(date_raw)
                desc = str(desc_raw or "").strip()
                v = parse_money(value_raw)
                if not (d and desc and v is not None):
                    continue
                total_parsed += 1
                tx_type = seed_type_for_row(sheet_type, cat_raw, v)
                if not tx_type:
                    continue
                category_label = "SMARTEK" if is_smartek_sheet else str(cat_raw or "")
                cat_id = find_category_id(conn, category_label)
                if not cat_id:
                    continue
                sub_label = (
                    smartek_seed_subcategory(tx_type, desc_raw, cat_raw, notes_raw)
                    if is_smartek_sheet
                    else str(sub_raw or notes_raw or "")
                )
                sub_id = find_or_create_subcategory(conn, sub_label)
                acc_id = None
                acc = None
                account_label = (
                    "CONTA SMARTEK" if is_smartek_sheet else str(account_raw or "")
                )
                if account_label:
                    acc = resolve_account_from_text(conn, account_label)
                    if acc:
                        acc_id = acc[0]
                dnorm = norm_text(desc)
                if is_smartek_sheet:
                    moved = move_duplicate_history_to_smartek_sheet(
                        conn,
                        acc_id,
                        sheet_source_id,
                        cat_id,
                        sub_id,
                        d,
                        dnorm,
                        abs(v),
                        tx_type,
                    )
                    if moved:
                        total_duplicates += moved
                        total_inserted += moved
                        continue
                if conn.execute(
                    """
                    SELECT 1
                    FROM classification_history
                    WHERE source_file_id=?
                      AND date=?
                      AND description_norm=?
                      AND ROUND(amount, 2)=ROUND(?, 2)
                      AND type=?
                    LIMIT 1
                    """,
                    (sheet_source_id, d, dnorm, abs(float(v)), tx_type),
                ).fetchone():
                    total_duplicates += 1
                    continue
                history_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO classification_history(
                      id, source_file_id, account_id, date, description, description_norm, amount, type, category_id, subcategory_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        history_id,
                        sheet_source_id,
                        acc_id,
                        d,
                        desc,
                        dnorm,
                        abs(v),
                        tx_type,
                        cat_id,
                        sub_id,
                    ),
                )
                store_shadow_metadata(
                    conn,
                    "classification_history",
                    history_id,
                    desc,
                    acc[2] if acc else "",
                )
                total_inserted += 1
            conn.commit()
            if progress:
                progress(
                    "importing", processed_rows, total_rows, f"Aba {ws.title} concluida"
                )
        conn.execute(
            """
            INSERT INTO imported_files(
              id,filename,file_type,file_hash,source_path,account_id,account_name,
              total_parsed,total_inserted,total_duplicates,total_errors,imported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                imported_file_id,
                path.name,
                "xlsx-seed",
                hashlib.sha1(path.read_bytes()).hexdigest(),
                str(path),
                "seed",
                "IMPORT_SEED",
                total_parsed,
                total_inserted,
                total_duplicates,
                0,
                now,
            ),
        )
    if not sheets_recognized:
        return {
            "detail": (
                "Nenhuma aba reconhecida na planilha. Abas esperadas: SAIDAS e/ou ENTRADAS. "
                f"Abas encontradas no arquivo: {', '.join(sheets_found) or 'nenhuma'}. "
                "Renomeie as abas e tente novamente."
            ),
            "code": "SEED_NO_SHEETS",
            "sheets_found": sheets_found,
        }, 422
    if total_parsed == 0:
        return {
            "detail": (
                f"Abas reconhecidas ({', '.join(sheets_recognized)}), mas nenhuma linha valida foi lida. "
                "Confira se ha colunas de Data, Descricao e Valor preenchidas."
            ),
            "code": "SEED_NO_ROWS",
            "sheets_found": sheets_found,
        }, 422
    return {
        "imported_file_id": imported_file_id,
        "filename": path.name,
        "account_name": "IMPORT_SEED",
        "total_parsed": total_parsed,
        "total_inserted": total_inserted,
        "total_duplicates": total_duplicates,
        "total_errors": 0,
        "sheets_recognized": sheets_recognized,
        "transactions_preview": [],
    }, 201


def import_seed_pdf(path: Path, progress=None, imported_file_id: str | None = None):
    if PdfReader is None:
        raise RuntimeError("pypdf nao encontrado")
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if progress:
        progress("reading", 0, len(lines), f"PDF extraido: {len(lines)} linha(s)")

    now = dt.datetime.now().isoformat(timespec="seconds")
    imported_file_id = imported_file_id or str(uuid.uuid4())
    total_parsed = 0
    total_inserted = 0
    total_duplicates = 0

    row_re = re.compile(
        r"^(\d{2}/\d{2}/\d{4})\s+\d{4}/\d{2}\s+(.+?)\s*[(]R[$]\s*[(]?([\d.,]+)[-]?[)]?[)]\s*(.*)$"
    )
    rejected: list[str] = []

    with db_connect() as conn:
        cat_rows = conn.execute("SELECT id,name,type FROM categories").fetchall()
        cat_map = [(r[0], r[1], r[2], norm_text(r[1])) for r in cat_rows]

        for line_number, ln in enumerate(lines, start=1):
            if line_number % 100 == 0:
                conn.commit()
                if progress:
                    progress(
                        "importing",
                        line_number,
                        len(lines),
                        f"{total_inserted} inseridos, {total_duplicates} duplicados",
                    )
            m = row_re.match(ln)
            if not m:
                if re.search(r"\d{2}/\d{2}/\d{4}", ln):
                    rejected.append(ln[:150])
                continue
            d = parse_date(m.group(1))
            desc = (m.group(2) or "").strip()
            val = parse_money((m.group(3) or "").replace(" ", ""))
            tail = (m.group(4) or "").strip()
            if not (d and desc and val is not None):
                continue
            total_parsed += 1

            tx_type = "income" if val >= 0 else "expense"
            dnorm = norm_text(desc)
            tail_norm = norm_text(tail)

            matched = None
            for cid, cname, _ctype, cnorm in sorted(
                cat_map, key=lambda x: len(x[3]), reverse=True
            ):
                if cnorm and (
                    tail_norm.startswith(cnorm) or f" {cnorm} " in f" {tail_norm} "
                ):
                    matched = (cid, cname, cnorm)
                    break
            if not matched:
                continue

            cat_id = matched[0]
            sub_txt = tail_norm.replace(matched[2], "", 1).strip()
            sub_txt = re.sub(r"\b(antigo|primeira planilha)\b", "", sub_txt).strip()
            sub_id = (
                find_or_create_subcategory(conn, sub_txt.upper()) if sub_txt else None
            )

            if conn.execute(
                """
                SELECT 1 FROM classification_history
                WHERE source_file_id=? AND description_norm=? AND type=? AND category_id=? AND IFNULL(subcategory_id,'')=IFNULL(?, '')
                LIMIT 1
                """,
                (imported_file_id, dnorm, tx_type, cat_id, sub_id),
            ).fetchone():
                total_duplicates += 1
                continue

            history_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO classification_history(
                  id, source_file_id, account_id, date, description, description_norm, amount, type, category_id, subcategory_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    history_id,
                    imported_file_id,
                    None,
                    d,
                    desc,
                    dnorm,
                    abs(val),
                    tx_type,
                    cat_id,
                    sub_id,
                ),
            )
            store_shadow_metadata(conn, "classification_history", history_id, desc)
            total_inserted += 1

        conn.execute(
            """
            INSERT INTO imported_files(
              id,filename,file_type,file_hash,source_path,account_id,account_name,
              total_parsed,total_inserted,total_duplicates,total_errors,imported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                imported_file_id,
                path.name,
                "pdf-seed",
                hashlib.sha1(path.read_bytes()).hexdigest(),
                str(path),
                "seed",
                "IMPORT_SEED",
                total_parsed,
                total_inserted,
                total_duplicates,
                0,
                now,
            ),
        )

    return {
        "imported_file_id": imported_file_id,
        "filename": path.name,
        "account_name": "IMPORT_SEED",
        "total_parsed": total_parsed,
        "total_inserted": total_inserted,
        "total_duplicates": total_duplicates,
        "total_errors": 0,
        "debug_rejected_sample": rejected[:15],
        "transactions_preview": [],
    }, 201


def import_document(
    path: Path,
    account_id: str,
    confirm_duplicates: bool = False,
    competence_month_override: str = "",
    progress=None,
):
    h = hashlib.sha1(path.read_bytes()).hexdigest()
    ext = path.suffix.lower().replace(".", "")
    now = dt.datetime.now().isoformat(timespec="seconds")
    imported_file_id = str(uuid.uuid4())

    with db_connect() as conn:
        acc = get_account(conn, account_id) if account_id else None
        if not acc:
            return {
                "detail": "Conta/cartao obrigatorio",
                "code": "ACCOUNT_REQUIRED",
            }, 400

        preview_data = build_import_preview(path, acc)
        txs = preview_data["txs"]
        parsed_rows = preview_data["parsed_rows"]
        warnings = preview_data["warnings"]
        if progress:
            progress(
                "validating",
                0,
                len(parsed_rows),
                f"{len(parsed_rows)} lancamento(s) lido(s); validando duplicidade no banco",
            )

        prev = conn.execute(
            "SELECT id, imported_at, total_parsed FROM imported_files WHERE file_hash=?",
            (h,),
        ).fetchone()
        if prev and int(prev[2] or 0) > 0:
            return {
                "detail": (
                    f"Arquivo ja importado em {prev[1]} "
                    f"com {int(prev[2] or 0)} lancamentos."
                ),
                "code": "FILE_ALREADY_IMPORTED",
                "imported_file_id": prev[0],
            }, 409
        if prev and int(prev[2] or 0) == 0:
            # Permite reprocessar arquivo que antes foi salvo sem lancamentos.
            conn.execute(
                """
                DELETE FROM transaction_reconciliations
                WHERE expense_transaction_id IN (SELECT id FROM transactions WHERE imported_file_id=?)
                   OR income_transaction_id IN (SELECT id FROM transactions WHERE imported_file_id=?)
                """,
                (prev[0], prev[0]),
            )
            conn.execute(
                "DELETE FROM transactions WHERE imported_file_id=?", (prev[0],)
            )
            conn.execute(
                "DELETE FROM installment_plans WHERE id NOT IN (SELECT installment_plan_id FROM transactions WHERE installment_plan_id IS NOT NULL)"
            )
            conn.execute("DELETE FROM imported_files WHERE id=?", (prev[0],))

        # Prova real: comprovante de fatura Santander (PDF) nÃ£o Ã© extrato detalhado de compras.
        # Para cartÃ£o Santander, a fonte correta dos itens Ã© o CSV da fatura.
        if (
            ext == "pdf"
            and (acc[1] or "").upper() == "CARTAO SANTANDER"
            and len(txs) < 12
        ):
            return {
                "detail": "PDF de cartao Santander sem detalhamento suficiente. Use preferencialmente o CSV da fatura.",
                "code": "CARD_SUMMARY_PDF_NOT_SUPPORTED",
            }, 422
        internal_counter = preview_data["internal_counter"]

        internal_duplicates = sum(max(0, c - 1) for c in internal_counter.values())

        # Repeticoes internas representam ocorrencias reais distintas e sao preservadas.
        # Sobreposicoes com documentos anteriores so podem ser ignoradas mediante
        # confirmacao explicita. O hash integral continua bloqueando reimportacoes.
        card_competence = (
            competence_month_override
            if (acc[2] or "").lower() == "credit_card"
            and re.match(r"^\d{4}/\d{2}$", competence_month_override or "")
            else ""
        )
        is_card_statement = (acc[2] or "").lower() == "credit_card"
        db_counts = {
            r["sig"]: existing_db_duplicate_count(
                conn,
                acc[0],
                r,
                competence_month=card_competence,
                card_statement=is_card_statement,
            )
            for r in parsed_rows
        }
        preview_occ: dict[tuple[Any, ...], int] = {}
        existing_db_duplicates = 0
        for r in parsed_rows:
            preview_occ[r["sig"]] = preview_occ.get(r["sig"], 0) + 1
            if preview_occ[r["sig"]] <= db_counts.get(r["sig"], 0):
                existing_db_duplicates += 1

        if existing_db_duplicates > 0 and not confirm_duplicates:
            return {
                "detail": (
                    f"Importacao bloqueada: {existing_db_duplicates} lancamento(s) do arquivo "
                    "ja existem no banco. Confirme a sobreposicao para importar apenas "
                    "os lancamentos novos."
                ),
                "code": "DATABASE_DUPLICATES_FOUND",
                "duplicates_found": existing_db_duplicates,
                "duplicates_db_found": existing_db_duplicates,
                "duplicates_internal_found": internal_duplicates,
                "total_parsed": len(txs),
            }, 409

        metadata = import_metadata_from_account(path, acc[1])
        if competence_month_override and re.match(
            r"^\d{4}/\d{2}$", competence_month_override
        ):
            metadata["year"], metadata["month"] = competence_month_override.split("/")
        archived_target = archive_target_path(path, acc[1], txs)
        if metadata.get("year") and metadata.get("month"):
            archived_target = (
                DOCS
                / metadata["year"]
                / metadata["month"]
                / account_folder_name(acc[1])
                / clean_archive_filename(path.name)
            )
        archived_source_path = project_relative_path(archived_target)

        inserted = 0
        duplicates_db = 0
        duplicates_internal = internal_duplicates
        preview = []
        occ: dict[tuple[str, float, str, str], int] = {}
        if progress:
            progress("saving", 0, len(parsed_rows), "Salvando lancamentos no banco")
        for row_index, r in enumerate(parsed_rows, start=1):
            occ[r["sig"]] = occ.get(r["sig"], 0) + 1
            if occ[r["sig"]] <= db_counts.get(r["sig"], 0):
                duplicates_db += 1
                if progress and (
                    row_index == len(parsed_rows) or row_index % 25 == 0
                ):
                    progress(
                        "saving",
                        row_index,
                        len(parsed_rows),
                        f"{row_index} de {len(parsed_rows)} lancamentos conferidos",
                    )
                continue

            # Ocorrencias internas repetidas sao legitimas e recebem chaves distintas.
            key = (
                f"{acc[0]}|{r['date']}|{r['amount_signed']:.2f}|{r['description_norm']}|"
                f"{r['tx_type']}|{int(r['installment_current'] or 0)}|{int(r['installment_total'] or 0)}"
                f"|{h[:12]}#{occ[r['sig']]}"
            )
            installment_plan_id, installment_plan = find_or_create_installment_plan(
                conn, acc[0], r
            )

            status = "pending"
            cat = None
            sub = None
            s_cat = None
            s_sub = None
            identity = None
            inherited_from_plan = bool(installment_plan and installment_plan[1])
            if inherited_from_plan:
                cat, sub = installment_plan[1], installment_plan[2]
                status = "reconciled"
            else:
                identity = find_identity_match(
                    conn,
                    {
                        "date": r["date"],
                        "description": r["description"],
                        "description_norm": r["description_norm"],
                        "amount": r["amount_signed"],
                        "type": r["tx_type"],
                        "account_id": acc[0],
                        "installment_current": r["installment_current"],
                        "installment_total": r["installment_total"],
                    },
                )
                if identity:
                    s_cat = identity.get("category_id")
                    s_sub = identity.get("subcategory_id")
                else:
                    s_cat, s_sub = suggest_for_desc(
                        conn, r["description_norm"], r["tx_type"]
                    )
            match_probability = float((identity or {}).get("identity_score") or 0)
            is_link_candidate = bool(
                identity and match_probability >= HISTORY_LINK_CANDIDATE_THRESHOLD
            )
            history_match_id = (
                (identity or {}).get("history_match_id") if is_link_candidate else None
            )
            identity_score = match_probability
            match_notes = (
                "Possivel vinculo pelo valor total parcelado na base historica"
                if is_link_candidate
                and identity.get("match_basis") == "installment_total"
                else "Possivel vinculo com base historica"
                if is_link_candidate
                else ""
            )
            tx_id = str(uuid.uuid4())
            row_flags = [flag for flag in (r.get("flags", "") or "").split(",") if flag]
            flags_text = ",".join(row_flags)
            conn.execute(
                """
                INSERT INTO transactions(
                  id,tx_key,date,competence_month,description,description_norm,amount,type,status,account_id,
                  category_id,subcategory_id,notes,suggested_category_id,suggested_subcategory_id,
                  match_probability,match_notes,history_match_id,identity_score,
                  installment_current,installment_total,flags,imported_file_id,
                  installment_plan_id,locked,classified_by,classified_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    tx_id,
                    key,
                    r["date"],
                    competence_month_override
                    if re.match(r"^\d{4}/\d{2}$", competence_month_override or "")
                    else r["date"][:7].replace("-", "/"),
                    r["description"],
                    r["description_norm"],
                    r["amount_signed"],
                    r["tx_type"],
                    status,
                    acc[0],
                    cat,
                    sub,
                    "",
                    s_cat,
                    s_sub,
                    match_probability,
                    match_notes,
                    history_match_id,
                    identity_score,
                    r["installment_current"],
                    r["installment_total"],
                    flags_text,
                    imported_file_id,
                    installment_plan_id,
                    1 if inherited_from_plan else 0,
                    installment_plan[3] if inherited_from_plan else "",
                    installment_plan[4] if inherited_from_plan else "",
                ),
            )
            store_shadow_metadata(
                conn,
                "transactions",
                tx_id,
                r["description"],
                acc[2],
                r["installment_current"],
                r["installment_total"],
            )
            inserted += 1
            if progress and (row_index == len(parsed_rows) or row_index % 25 == 0):
                progress(
                    "saving",
                    row_index,
                    len(parsed_rows),
                    f"{row_index} de {len(parsed_rows)} lancamentos preparados",
                )
            if len(preview) < 20:
                preview.append(
                    {
                        "id": tx_id,
                        "date": r["date"],
                        "description": r["description"],
                        "amount": r["amount_signed"],
                        "type": r["tx_type"],
                        "status": status,
                        "installment_current": r["installment_current"],
                        "installment_total": r["installment_total"],
                        "installment_label": r["installment_label"],
                        "is_installment": r["is_installment"],
                        "installment_plan_id": installment_plan_id,
                        "classification_inherited": inherited_from_plan,
                        "flags": flags_text,
                    }
                )

        conn.execute(
            """
            INSERT INTO imported_files(
              id,filename,file_type,file_hash,source_path,account_id,account_name,
              total_parsed,total_inserted,total_duplicates,total_errors,year,month,source_kind,bank,imported_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                imported_file_id,
                path.name,
                ext,
                h,
                archived_source_path,
                acc[0],
                acc[1],
                len(txs),
                inserted,
                duplicates_db,
                0,
                metadata.get("year", ""),
                metadata.get("month", ""),
                metadata.get("source_kind", ""),
                metadata.get("bank", ""),
                now,
            ),
        )

        # O documento e os lancamentos pertencem a mesma transacao. Se o cofre
        # persistente falhar, todo o lote e revertido.
        if progress:
            progress(
                "document",
                len(parsed_rows),
                len(parsed_rows),
                "Preservando o arquivo original no cofre",
            )
        store_document_in_db(
            path,
            acc[1],
            f"{archived_target.parents[2].name}/{archived_target.parents[1].name}",
            archived_target.name,
            imported_file_id=imported_file_id,
            conn=conn,
        )

    # A copia em disco e secundaria no hosting. O original persistente ja foi
    # confirmado atomicamente com o lote no banco.
    try:
        archive_import_file(path, archived_target)
    except Exception as exc:
        logger.warning(
            "Falha ao copiar importacao para arquivo local: %s", path, exc_info=True
        )
        warnings.append(
            f"Documento preservado no cofre, mas a copia local falhou: {type(exc).__name__}"
        )
    if progress:
        progress(
            "completed",
            len(parsed_rows),
            len(parsed_rows),
            f"Importacao concluida: {inserted} lancamento(s) salvo(s)",
        )

    return {
        "imported_file_id": imported_file_id,
        "filename": path.name,
        "account_name": acc[1],
        "total_parsed": len(txs),
        "total_inserted": inserted,
        "total_duplicates": duplicates_db,
        "total_duplicates_db": duplicates_db,
        "total_duplicates_internal": duplicates_internal,
        "total_errors": 0,
        "warnings": warnings,
        "balance_check": preview_data.get("balance_check", {}),
        "import_meta": preview_data.get("import_meta", {}),
        "rejected_lines": preview_data.get("rejected_lines", []),
        "discarded_lines": preview_data.get("discarded_lines", []),
        "transactions_preview": preview,
    }, 201


@app.after_request
def legacy_ui_cache_headers(resp):
    # CORS e tratado em _apply_cors (respeita CORS_ORIGINS). Aqui apenas cache das paginas /ui.
    if request.path.startswith("/ui/"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp




@imports_bp.route("/api/v1/import/upload", methods=["POST"])
def import_upload():
    return jsonify(
        {
            "detail": "Importacao direta desativada. Use preview e confirmacao.",
            "code": "IMPORT_PREVIEW_REQUIRED",
        }
    ), 410


@imports_bp.route("/api/v1/import/preview", methods=["POST"])
def import_preview():
    f = request.files.get("file")
    account_id = (request.form.get("account_id") or "").strip()
    if not f or not f.filename:
        return jsonify(
            {"detail": "Arquivo obrigatorio", "code": "VALIDATION_ERROR"}
        ), 400
    invalid_file = validate_import_filename(f.filename)
    if invalid_file:
        return invalid_file

    preview_id = str(uuid.uuid4())
    safe_name = secure_filename(f.filename) or "arquivo"
    p = UPLOADS / f"preview-{preview_id}-{safe_name}"
    f.save(p)
    try:
        with db_connect() as conn:
            detection_sample = read_detection_sample(p)
            detected_acc, account_detection = detect_account_with_evidence(
                conn, p, detection_sample
            )
            acc = get_account(conn, account_id) if account_id else detected_acc
            if not acc:
                try:
                    p.unlink()
                except OSError:
                    logger.warning(
                        "Falha ao remover upload temporario %s", p, exc_info=True
                    )
                return jsonify(
                    {
                        "detail": "Nao foi possivel detectar a conta. Selecione uma conta e analise novamente.",
                        "code": "ACCOUNT_DETECTION_FAILED",
                        "account_detection": account_detection,
                    }
                ), 422

            selection_source = "manual" if account_id else "automatic"
            conflict = bool(detected_acc and detected_acc[0] != acc[0])
            account_detection.update(
                {
                    "selected_account_id": acc[0],
                    "selected_account_name": acc[1],
                    "selection_source": selection_source,
                    "conflict": conflict,
                }
            )

            prep = build_import_preview(p, acc, detection_sample)
            parsed_rows = prep["parsed_rows"]
            internal_counter = prep["internal_counter"]
            warnings = list(prep["warnings"])
            if conflict:
                warnings.append(
                    f"A conta selecionada ({acc[1]}) difere da conta detectada ({detected_acc[1]}). Confirme antes de importar."
                )
            internal_duplicates = sum(max(0, c - 1) for c in internal_counter.values())

            existing_db_duplicates = 0
            historical_matches = 0
            occ: dict[tuple[str, float, str, str], int] = {}
            rows_preview: list[dict[str, Any]] = []
            preview_competence = ""
            if (acc[2] or "").lower() == "credit_card":
                candidate = str(
                    prep.get("import_meta", {}).get("suggested_competence_month")
                    or ""
                )
                if re.match(r"^\d{4}/\d{2}$", candidate):
                    preview_competence = candidate
            db_counts = {
                r["sig"]: existing_db_duplicate_count(
                    conn,
                    acc[0],
                    r,
                    competence_month=preview_competence,
                    card_statement=(acc[2] or "").lower() == "credit_card",
                )
                for r in parsed_rows
            }
            for r in parsed_rows:
                occ[r["sig"]] = occ.get(r["sig"], 0) + 1
                is_db_dup = occ[r["sig"]] <= db_counts.get(r["sig"], 0)
                if is_db_dup:
                    existing_db_duplicates += 1
                match = (
                    find_identity_match(
                        conn,
                        {
                            "date": r["date"],
                            "description": r["description"],
                            "description_norm": r["description_norm"],
                            "amount": r["amount_signed"],
                            "type": r["tx_type"],
                            "account_id": acc[0],
                            "installment_current": r.get("installment_current"),
                            "installment_total": r.get("installment_total"),
                        },
                    )
                    or {}
                )
                match_probability = float(match.get("identity_score") or 0)
                if match_probability >= 70:
                    historical_matches += 1
                rows_preview.append(
                    {
                        "date": r["date"],
                        "description": r["description"],
                        "amount": r["amount_signed"],
                        "type": r["tx_type"],
                        "installment_current": r["installment_current"],
                        "installment_total": r["installment_total"],
                        "installment_label": r["installment_label"],
                        "is_installment": r["is_installment"],
                        "flags": r.get("flags", ""),
                        "duplicate_db": is_db_dup,
                        "duplicate_internal": (internal_counter.get(r["sig"], 0) > 1),
                        "occurrence": occ[r["sig"]],
                        "match_probability": match_probability,
                        "history_match_id": match.get("history_match_id") or "",
                    }
                )

            import_meta = prep.get("import_meta", {})
            detected_kind = (
                "CARTAO" if (acc[2] or "").lower() == "credit_card" else "EXTRATO"
            )
            detected_bank = (
                import_meta.get("bank")
                or account_detection.get("bank")
                or "DESCONHECIDO"
            )
            detected_type = f"{detected_kind} {detected_bank}"
            confidence = float(import_meta.get("detection_confidence") or 0.0)
            conn.execute(
                "INSERT INTO import_previews(id,filename,temp_path,account_id,detected_type,detection_confidence,created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    preview_id,
                    f.filename,
                    str(p),
                    acc[0],
                    detected_type,
                    confidence,
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )

            total_income = round(
                sum(
                    float(row["amount_signed"])
                    for row in parsed_rows
                    if row["tx_type"] == "income"
                ),
                2,
            )
            total_expense = round(
                sum(
                    abs(float(row["amount_signed"]))
                    for row in parsed_rows
                    if row["tx_type"] == "expense"
                ),
                2,
            )
            income_count = sum(1 for row in parsed_rows if row["tx_type"] == "income")
            expense_count = sum(1 for row in parsed_rows if row["tx_type"] == "expense")
            critical_errors: list[str] = []
            if not parsed_rows and not bool(
                import_meta.get("empty_statement_confirmed")
            ):
                critical_errors.append("Nenhum lancamento foi identificado no arquivo.")
        return jsonify(
            {
                "preview_id": preview_id,
                "filename": f.filename,
                "account_id": acc[0],
                "account_name": acc[1],
                "account_detection": account_detection,
                "detected_type": detected_type,
                "detection_confidence": round(confidence * 100, 2),
                "total_parsed": len(parsed_rows),
                "duplicates_db": existing_db_duplicates,
                "duplicates_internal": internal_duplicates,
                "new_records": max(0, len(parsed_rows) - existing_db_duplicates),
                "income_count": income_count,
                "expense_count": expense_count,
                "total_income": total_income,
                "total_expense": total_expense,
                "historical_matches": historical_matches,
                "quality_gate": {
                    "can_commit": not critical_errors,
                    "critical_errors": critical_errors,
                },
                "warnings": warnings,
                "balance_check": prep.get("balance_check", {}),
                "import_meta": prep.get("import_meta", {}),
                "rejected_lines": prep.get("rejected_lines", []),
                "discarded_lines": prep.get("discarded_lines", []),
                "rows": rows_preview,
            }
        ), 200
    except Exception as exc:
        logger.exception("Falha ao gerar preview do arquivo %s", p)
        try:
            if p.exists():
                p.unlink()
        except OSError:
            logger.warning("Falha ao remover upload temporario %s", p, exc_info=True)
        return jsonify(
            {"detail": f"{type(exc).__name__}: {exc}", "code": "PREVIEW_FAILED"}
        ), 422


@imports_bp.route("/api/v1/import/commit", methods=["POST"])
def import_commit():
    data = request.get_json(force=True) or {}
    preview_id = (data.get("preview_id") or "").strip()
    confirm_duplicates = bool(data.get("confirm_duplicates", True))
    competence_month = (data.get("competence_month") or "").strip()
    if competence_month and not re.match(r"^\d{4}/\d{2}$", competence_month):
        return jsonify(
            {
                "detail": "competence_month deve estar no formato YYYY/MM",
                "code": "VALIDATION_ERROR",
            }
        ), 400
    if not preview_id:
        return jsonify(
            {"detail": "preview_id obrigatorio", "code": "VALIDATION_ERROR"}
        ), 400

    with db_connect() as conn:
        row = conn.execute(
            "SELECT temp_path,account_id,filename FROM import_previews WHERE id=?",
            (preview_id,),
        ).fetchone()
        existing = conn.execute(
            "SELECT id,status FROM import_jobs WHERE preview_id=?", (preview_id,)
        ).fetchone()
    if not row:
        if existing:
            return jsonify({"job_id": existing[0], "status": existing[1]}), 200
        return jsonify(
            {"detail": "Preview nao encontrado", "code": "PREVIEW_NOT_FOUND"}
        ), 404

    temp_path = Path(row[0])
    if not temp_path.exists():
        with db_connect() as conn:
            conn.execute("DELETE FROM import_previews WHERE id=?", (preview_id,))
        return jsonify(
            {
                "detail": "Arquivo temporario nao encontrado",
                "code": "PREVIEW_FILE_MISSING",
            }
        ), 404

    if existing and existing[1] in {"queued", "running", "completed"}:
        return jsonify({"job_id": existing[0], "status": existing[1]}), 200

    job_id = existing[0] if existing else str(uuid.uuid4())
    now = dt.datetime.now().isoformat(timespec="seconds")
    with db_connect() as conn:
        if existing:
            conn.execute(
                """
                UPDATE import_jobs
                SET status='queued',phase='queued',processed=0,total=0,message='',logs_json='[]',
                    result_json='',error='',started_at='',finished_at=?,confirm_duplicates=?,competence_month=?
                WHERE id=?
                """,
                ("", int(confirm_duplicates), competence_month, job_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO import_jobs(id,preview_id,filename,status,created_at,confirm_duplicates,competence_month)
                VALUES (?,?,?,'queued',?,?,?)
                """,
                (
                    job_id,
                    preview_id,
                    row[2],
                    now,
                    int(confirm_duplicates),
                    competence_month,
                ),
            )
    if WORKER_MODE == "inline":
        threading.Thread(
            target=_run_import_job,
            args=(job_id, preview_id, confirm_duplicates, competence_month),
            daemon=True,
            name=f"document-import-{job_id[:8]}",
        ).start()
    return jsonify({"job_id": job_id, "status": "queued"}), 202


def _imported_file_result(imported_file_id: str) -> dict[str, Any] | None:
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,filename,account_name,total_parsed,total_inserted,total_duplicates,total_errors
            FROM imported_files WHERE id=?
            """,
            (imported_file_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "imported_file_id": row[0],
        "filename": row[1],
        "account_name": row[2],
        "total_parsed": int(row[3] or 0),
        "total_inserted": int(row[4] or 0),
        "total_duplicates": int(row[5] or 0),
        "total_errors": int(row[6] or 0),
        "transactions_preview": [],
        "recovered": True,
    }


def _run_import_job(
    job_id: str,
    preview_id: str,
    confirm_duplicates: bool,
    competence_month: str,
) -> None:
    temp_path: Path | None = None
    sqlite_import_transaction_active = False
    sqlite_deferred_progress: list[tuple[str, int, int, str]] = []

    def progress(phase: str, processed: int, total: int, message: str) -> None:
        # SQLite permite apenas um escritor. Durante a transacao financeira da
        # importacao, uma segunda conexao nao consegue atualizar a linha do job.
        # Preservamos os eventos em memoria e os descarregamos assim que o lote
        # atomico termina. PostgreSQL continua expondo o progresso em tempo real.
        if not IS_POSTGRES and sqlite_import_transaction_active:
            sqlite_deferred_progress.append((phase, processed, total, message))
            return
        try:
            timestamp = dt.datetime.now().strftime("%H:%M:%S")
            with db_connect(timeout_seconds=0.05) as conn:
                row = conn.execute(
                    "SELECT logs_json FROM import_jobs WHERE id=?", (job_id,)
                ).fetchone()
                logs = json.loads(row[0] or "[]") if row else []
                if not logs or logs[-1].get("message") != message:
                    logs = (logs + [{"time": timestamp, "message": message}])[-40:]
                conn.execute(
                    """
                    UPDATE import_jobs
                    SET phase=?,processed=?,total=?,message=?,logs_json=? WHERE id=?
                    """,
                    (
                        phase,
                        processed,
                        total,
                        message,
                        json.dumps(logs, ensure_ascii=False),
                        job_id,
                    ),
                )
        except Exception:
            # Log de progresso nunca pode abortar a transacao financeira.
            logger.warning(
                "Falha ao persistir progresso do job de importacao %s",
                job_id,
                exc_info=True,
            )

    try:
        with db_connect() as conn:
            preview = conn.execute(
                "SELECT temp_path,account_id FROM import_previews WHERE id=?",
                (preview_id,),
            ).fetchone()
            conn.execute(
                "UPDATE import_jobs SET status='running',phase='starting',message='Preparando importacao',started_at=? WHERE id=?",
                (dt.datetime.now().isoformat(timespec="seconds"), job_id),
            )
        progress("starting", 0, 0, "Preparando importacao")
        if not preview:
            raise RuntimeError("Preview nao encontrado para processar a importacao")
        temp_path = Path(preview[0])
        if not temp_path.exists():
            raise RuntimeError("Arquivo temporario nao encontrado")
        sqlite_import_transaction_active = True
        try:
            result, status = import_document(
                temp_path,
                preview[1],
                confirm_duplicates=confirm_duplicates,
                competence_month_override=competence_month,
                progress=progress,
            )
        finally:
            sqlite_import_transaction_active = False
            for deferred_event in sqlite_deferred_progress:
                progress(*deferred_event)
        if status == 409 and result.get("code") == "FILE_ALREADY_IMPORTED":
            recovered = _imported_file_result(str(result.get("imported_file_id") or ""))
            if recovered:
                result, status = recovered, 200
        completed = status < 400
        error = "" if completed else str(result.get("detail") or "Falha na importacao")
        with db_connect() as conn:
            conn.execute(
                """
                UPDATE import_jobs
                SET status=?,phase=?,message=?,result_json=?,error=?,finished_at=? WHERE id=?
                """,
                (
                    "completed" if completed else "failed",
                    "completed" if completed else "failed",
                    "Importacao concluida" if completed else error,
                    json.dumps(result, ensure_ascii=False),
                    error,
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )
            if completed:
                conn.execute("DELETE FROM import_previews WHERE id=?", (preview_id,))
        if completed and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                logger.warning(
                    "Falha ao remover arquivo temporario %s", temp_path, exc_info=True
                )
    except Exception as exc:
        logger.exception("Job de importacao %s falhou", job_id)
        with db_connect() as conn:
            error = f"{type(exc).__name__}: {exc}"[:1000]
            conn.execute(
                "UPDATE import_jobs SET status='failed',phase='failed',message=?,error=?,finished_at=? WHERE id=?",
                (
                    str(exc)[:500],
                    error,
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )


def _import_job_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "preview_id": row[1],
        "filename": row[2],
        "status": row[3],
        "phase": row[4] or "",
        "processed": int(row[5] or 0),
        "total": int(row[6] or 0),
        "message": row[7] or "",
        "logs": json.loads(row[8] or "[]"),
        "result": json.loads(row[9]) if row[9] else None,
        "error": row[10] or "",
        "created_at": row[11],
        "started_at": row[12] or "",
        "finished_at": row[13] or "",
    }


@imports_bp.route("/api/v1/import/jobs/<job_id>")
def import_job_status(job_id: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,preview_id,filename,status,phase,processed,total,message,logs_json,
                   result_json,error,created_at,started_at,finished_at
            FROM import_jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return jsonify(
            {"detail": "Importacao nao encontrada", "code": "NOT_FOUND"}
        ), 404
    return jsonify(_import_job_payload(row))


@imports_bp.route("/api/v1/import/history")
def import_history():
    with db_connect() as conn:
        rows = conn.execute(
            """
            SELECT id,filename,file_type,account_name,total_parsed,total_inserted,total_duplicates,imported_at,
                   year,month,source_kind,bank
            FROM imported_files ORDER BY imported_at DESC
            """
        ).fetchall()
    return jsonify(
        [
            {
                "id": r[0],
                "filename": r[1],
                "file_type": r[2],
                "account_name": r[3],
                "total_parsed": r[4],
                "total_inserted": r[5],
                "total_duplicates": r[6],
                "imported_at": r[7],
                "year": r[8],
                "month": r[9],
                "source_kind": r[10],
                "bank": r[11],
            }
            for r in rows
        ]
    )




@imports_bp.route("/api/v1/import/seed", methods=["POST"])
def import_seed():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(
            {"detail": "Arquivo obrigatorio", "code": "VALIDATION_ERROR"}
        ), 400
    invalid_file = validate_import_filename(f.filename)
    if invalid_file:
        return invalid_file
    replace_existing = (request.form.get("replace_existing") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    replace_confirmation = (request.form.get("replace_confirmation") or "").strip()
    with db_connect() as conn:
        active = conn.execute(
            "SELECT id,status,filename FROM seed_import_jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        existing_count = int(
            conn.execute(
                "SELECT COUNT(1) FROM classification_history WHERE source_file_id NOT LIKE 'manual:%'"
            ).fetchone()[0]
            or 0
        )
    if active:
        return jsonify(
            {
                "detail": f"Ja existe uma importacao em andamento: {active[2]}",
                "code": "SEED_IMPORT_IN_PROGRESS",
                "job_id": active[0],
                "status": active[1],
            }
        ), 409
    if existing_count and (
        not replace_existing or replace_confirmation != "SUBSTITUIR BASE HISTORICA"
    ):
        return jsonify(
            {
                "detail": (
                    f"Ja existe uma base historica ativa com {existing_count} registros. "
                    "Confirme a substituicao para continuar."
                ),
                "code": "SEED_REPLACE_CONFIRMATION_REQUIRED",
                "existing_records": existing_count,
            }
        ), 409
    safe_name = secure_filename(f.filename) or "base-historica.xlsx"
    p = UPLOADS / f"{int(dt.datetime.now().timestamp())}-seed-{safe_name}"
    f.save(p)
    job_id = str(uuid.uuid4())
    now = dt.datetime.now().isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO seed_import_jobs(id,status,filename,created_at,source_path,replace_existing) VALUES (?, 'queued', ?, ?, ?, ?)",
            (job_id, f.filename, now, str(p), int(replace_existing)),
        )
    if WORKER_MODE == "inline":
        threading.Thread(
            target=_run_seed_import_job,
            args=(job_id, p, replace_existing),
            daemon=True,
            name=f"seed-import-{job_id[:8]}",
        ).start()
    return jsonify({"job_id": job_id, "status": "queued", "filename": f.filename}), 202


def _run_seed_import_job(
    job_id: str, path: Path, replace_existing: bool = False
) -> None:
    replacement_committed = False

    def progress(phase: str, processed: int, total: int, message: str) -> None:
        timestamp = dt.datetime.now().strftime("%H:%M:%S")
        with db_connect() as conn:
            row = conn.execute(
                "SELECT logs_json FROM seed_import_jobs WHERE id=?", (job_id,)
            ).fetchone()
            logs = json.loads(row[0] or "[]") if row else []
            logs = (logs + [{"time": timestamp, "message": message}])[-30:]
            conn.execute(
                "UPDATE seed_import_jobs SET phase=?, processed=?, total=?, message=?, logs_json=? WHERE id=?",
                (
                    phase,
                    processed,
                    total,
                    message,
                    json.dumps(logs, ensure_ascii=False),
                    job_id,
                ),
            )

    try:
        with db_connect() as conn:
            conn.execute(
                "UPDATE seed_import_jobs SET status='running', phase='starting', message='Abrindo arquivo', started_at=? WHERE id=?",
                (dt.datetime.now().isoformat(timespec="seconds"), job_id),
            )
        if path.suffix.lower() == ".pdf":
            data, code = import_seed_pdf(
                path, progress=progress, imported_file_id=job_id
            )
        else:
            data, code = import_seed_workbook(
                path, progress=progress, imported_file_id=job_id
            )
        if code < 400 and int(data.get("total_inserted") or 0) == 0:
            data = {
                **data,
                "detail": "O arquivo nao produziu registros historicos validos; a base atual foi preservada.",
                "code": "EMPTY_SEED_IMPORT",
            }
            code = 422
        if code >= 400:
            with db_connect() as conn:
                conn.execute(
                    "DELETE FROM classification_history WHERE source_file_id=? OR source_file_id LIKE ?",
                    (job_id, f"{job_id}:sheet:%"),
                )
                conn.execute("DELETE FROM imported_files WHERE id=?", (job_id,))
        if code < 400 and replace_existing:
            with db_connect() as conn:
                old_filter = "source_file_id NOT LIKE 'manual:%' AND source_file_id<>? AND source_file_id NOT LIKE ?"
                old_params = (job_id, f"{job_id}:sheet:%")
                old_count = int(
                    conn.execute(
                        f"SELECT COUNT(1) FROM classification_history WHERE {old_filter}",
                        old_params,
                    ).fetchone()[0]
                    or 0
                )
                conn.execute(
                    f"""
                    UPDATE transactions
                    SET history_match_id=NULL,history_match_confirmed=0,identity_score=0,
                        match_probability=0,match_notes='',suggested_category_id=NULL,suggested_subcategory_id=NULL
                    WHERE history_match_id IN (SELECT id FROM classification_history WHERE {old_filter})
                    """,
                    old_params,
                )
                conn.execute(
                    f"UPDATE transactions SET history_match_rejected_id=NULL WHERE history_match_rejected_id IN "
                    f"(SELECT id FROM classification_history WHERE {old_filter})",
                    old_params,
                )
                conn.execute(
                    f"DELETE FROM classification_history WHERE {old_filter}", old_params
                )
                conn.execute(
                    "DELETE FROM imported_files WHERE file_type IN ('xlsx-seed','pdf-seed') AND id<>?",
                    (job_id,),
                )
                conn.execute("DELETE FROM transaction_suggestions")
                conn.execute("DELETE FROM transaction_suggestion_state")
                data["replaced_records"] = old_count
                data["replacement_mode"] = True
            replacement_committed = True
        status = "completed" if code < 400 else "failed"
        error = "" if code < 400 else str(data.get("detail") or "Falha na importacao")
        with db_connect() as conn:
            conn.execute(
                """
                UPDATE seed_import_jobs
                SET status=?, phase=?, result_json=?, error=?, message=?, finished_at=? WHERE id=?
                """,
                (
                    status,
                    status,
                    json.dumps(data, ensure_ascii=False),
                    error,
                    "Importacao concluida" if code < 400 else error,
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )
    except Exception as exc:
        logger.exception("Job historico %s falhou", job_id)
        with db_connect() as conn:
            if not replacement_committed:
                conn.execute(
                    "DELETE FROM classification_history WHERE source_file_id=? OR source_file_id LIKE ?",
                    (job_id, f"{job_id}:sheet:%"),
                )
                conn.execute("DELETE FROM imported_files WHERE id=?", (job_id,))
            conn.execute(
                "UPDATE seed_import_jobs SET status='failed', phase='failed', error=?, message=?, finished_at=? WHERE id=?",
                (
                    f"{type(exc).__name__}: {exc}"[:1000],
                    str(exc)[:500],
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )


@imports_bp.route("/api/v1/seed-import-jobs/<job_id>")
def seed_import_job_status(job_id: str):
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT id,status,filename,result_json,error,created_at,started_at,finished_at,
                   phase,processed,total,message,logs_json
            FROM seed_import_jobs WHERE id=?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return jsonify(
            {"detail": "Importacao nao encontrada", "code": "NOT_FOUND"}
        ), 404
    result = json.loads(row[3]) if row[3] else None
    return jsonify(
        {
            "id": row[0],
            "status": row[1],
            "filename": row[2],
            "result": result,
            "error": row[4],
            "created_at": row[5],
            "started_at": row[6],
            "finished_at": row[7],
            "phase": row[8],
            "processed": row[9],
            "total": row[10],
            "message": row[11],
            "logs": json.loads(row[12] or "[]"),
        }
    )


@imports_bp.route("/api/v1/seed-import-jobs-active")
def active_seed_import_job():
    with db_connect() as conn:
        row = conn.execute(
            "SELECT id FROM seed_import_jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return jsonify(
            {"detail": "Nenhuma importacao em andamento", "code": "NOT_FOUND"}
        ), 404
    return seed_import_job_status(row[0])


TAG_FILTER_ALIASES = {
    "investimento": ["investimento"],
    "tax": ["tax", "TAX"],
    "rendimento": ["rendimento"],
    "fatura": ["fatura", "CARD_PAYMENT"],
    "cartao_debito": ["cartao_debito"],
    "non_count": ["non_count"],
    "cashback": ["cashback", "CASHBACK"],
    "movimentacao_interna": ["INTER_ACCOUNT", "inter_account"],
}


def sanitize_transaction_flags(raw: Any) -> str:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = str(raw or "").split(",")
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        flag = norm_text(str(part)).strip().replace(" ", "_")
        flag = re.sub(r"[^a-z0-9_]+", "", flag)
        if not flag or flag in seen:
            continue
        seen.add(flag)
        cleaned.append(flag)
    return ",".join(cleaned)


def add_tag_filters(
    where: list[str], params: list[Any], raw_tags: str, tag_mode: str
) -> None:
    tags = [sanitize_transaction_flags(tag) for tag in (raw_tags or "").split(",")]
    tags = [tag for tag in tags if tag]
    if not tags:
        return

    tag_mode = (tag_mode or "include").strip().lower()
    flag_expr = "',' || LOWER(REPLACE(IFNULL(t.flags,''),' ','')) || ','"
    clauses: list[str] = []
    local_params: list[Any] = []
    for tag in tags:
        if tag in {"__empty__", "empty", "sem_tag", "vazia"}:
            clauses.append("TRIM(IFNULL(t.flags,''))=''")
            continue
        aliases = TAG_FILTER_ALIASES.get(tag, [tag])
        alias_clauses: list[str] = []
        for alias in aliases:
            alias_clauses.append(f"{flag_expr} LIKE ?")
            local_params.append(f"%,{alias.lower().replace(' ', '')},%")
        clauses.append("(" + " OR ".join(alias_clauses) + ")")
    if not clauses:
        return
    group = "(" + " OR ".join(clauses) + ")"
    if tag_mode == "exclude":
        group = f"NOT {group}"
    where.append(group)
    params.extend(local_params)


@transactions_bp.route("/api/v1/transactions")
def transactions():
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(500, max(1, int(request.args.get("page_size", 100))))
    where = ["1=1"]
    params: list[Any] = []

    status = (request.args.get("status") or "").strip()
    if status:
        where.append("t.status=?")
        params.append(status)
    tx_type = (request.args.get("type") or "").strip()
    if tx_type:
        where.append("t.type=?")
        params.append(tx_type)
    account_id = (request.args.get("account_id") or "").strip()
    if account_id:
        where.append("t.account_id=?")
        params.append(account_id)
    ledger_filter = (
        request.args.get("ledger_id") if "ledger_id" in request.args else "none"
    )
    ledger_filter = (ledger_filter or "").strip()
    if ledger_filter == "none":
        where.append("t.ledger_id IS NULL")
    elif ledger_filter and ledger_filter != "all":
        where.append("t.ledger_id=?")
        params.append(ledger_filter)
    category_id = (request.args.get("category_id") or "").strip()
    if category_id:
        where.append("t.category_id=?")
        params.append(category_id)
    subcategory_id = (request.args.get("subcategory_id") or "").strip()
    if subcategory_id:
        where.append("t.subcategory_id=?")
        params.append(subcategory_id)
    classification_queue = (
        (request.args.get("classification_queue") or "").strip().lower()
    )
    if classification_queue:
        where.append(
            "NOT EXISTS (SELECT 1 FROM transaction_reconciliations qr "
            "WHERE qr.expense_transaction_id=t.id OR qr.income_transaction_id=t.id)"
        )
    if classification_queue == "links":
        where.extend(
            [
                "t.category_id IS NULL",
                "t.locked=0",
                "t.history_match_id IS NOT NULL",
                "t.history_match_confirmed=0",
                "t.identity_score>=?",
            ]
        )
        params.append(HISTORY_LINK_CANDIDATE_THRESHOLD)
    elif classification_queue == "suggestions":
        where.extend(
            [
                "t.category_id IS NULL",
                "t.locked=0",
                "NOT (t.history_match_id IS NOT NULL AND t.history_match_confirmed=0 AND t.identity_score>=?)",
                "EXISTS (SELECT 1 FROM transaction_suggestion_state qs WHERE qs.transaction_id=t.id AND qs.status='completed' AND qs.dismissed=0 AND qs.suggestion_count>0)",
            ]
        )
        params.append(HISTORY_LINK_CANDIDATE_THRESHOLD)
    elif classification_queue == "none":
        where.extend(
            [
                "t.category_id IS NULL",
                "t.locked=0",
                "NOT (t.history_match_id IS NOT NULL AND t.history_match_confirmed=0 AND t.identity_score>=?)",
                "EXISTS (SELECT 1 FROM transaction_suggestion_state qn WHERE qn.transaction_id=t.id AND qn.status='completed' AND qn.dismissed=0 AND qn.suggestion_count=0)",
            ]
        )
        params.append(HISTORY_LINK_CANDIDATE_THRESHOLD)
    elif classification_queue == "waiting":
        where.extend(
            [
                "t.category_id IS NULL",
                "t.locked=0",
                "NOT (t.history_match_id IS NOT NULL AND t.history_match_confirmed=0 AND t.identity_score>=?)",
                "NOT EXISTS (SELECT 1 FROM transaction_suggestion_state qw WHERE qw.transaction_id=t.id AND qw.status='completed')",
            ]
        )
        params.append(HISTORY_LINK_CANDIDATE_THRESHOLD)
    elif classification_queue == "dismissed":
        where.extend(
            [
                "t.category_id IS NULL",
                "t.locked=0",
                "EXISTS (SELECT 1 FROM transaction_suggestion_state qd WHERE qd.transaction_id=t.id AND qd.dismissed=1)",
            ]
        )
    elif classification_queue == "classified":
        where.append("t.category_id IS NOT NULL")

    suggestion_strength = (
        (request.args.get("suggestion_strength") or "").strip().lower()
    )
    if suggestion_strength == "strong":
        where.append(
            "EXISTS (SELECT 1 FROM transaction_suggestion_state qf WHERE qf.transaction_id=t.id AND qf.best_confidence>=70)"
        )
    elif suggestion_strength == "weak":
        where.append(
            "EXISTS (SELECT 1 FROM transaction_suggestion_state qf WHERE qf.transaction_id=t.id AND qf.best_confidence>0 AND qf.best_confidence<70)"
        )
    reconciliation_status = (
        (request.args.get("reconciliation_status") or "").strip().lower()
    )
    if reconciliation_status == "matched":
        where.append(
            "EXISTS (SELECT 1 FROM transaction_reconciliations rf "
            "WHERE rf.expense_transaction_id=t.id OR rf.income_transaction_id=t.id)"
        )
    elif reconciliation_status == "unmatched":
        where.append(
            "NOT EXISTS (SELECT 1 FROM transaction_reconciliations rf "
            "WHERE rf.expense_transaction_id=t.id OR rf.income_transaction_id=t.id)"
        )
    is_installment = (request.args.get("is_installment") or "").strip().lower()
    if is_installment in {"1", "true", "yes", "sim"}:
        where.append(
            "t.installment_current IS NOT NULL AND t.installment_total IS NOT NULL"
        )
    elif is_installment in {"0", "false", "no", "nao", "nÃ£o"}:
        where.append("(t.installment_current IS NULL OR t.installment_total IS NULL)")
    competence_month = (request.args.get("competence_month") or "").strip()
    if competence_month:
        where.append("t.competence_month=?")
        params.append(competence_month)
    date_from = (request.args.get("date_from") or "").strip()
    if date_from:
        where.append("t.date>=?")
        params.append(parse_date(date_from) or date_from)
    date_to = (request.args.get("date_to") or "").strip()
    if date_to:
        where.append("t.date<=?")
        params.append(parse_date(date_to) or date_to)
    add_tag_filters(
        where,
        params,
        request.args.get("tags") or request.args.get("tag") or "",
        request.args.get("tag_mode") or "include",
    )
    search = (request.args.get("search") or "").strip()
    if search:
        s = f"%{escape_like(norm_text(search))}%"
        s_raw = f"%{escape_like(search)}%"
        where.append(
            "("
            "t.description_norm LIKE ? ESCAPE '\\' OR "
            "LOWER(a.name) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(c.name,'')) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(s.name,'')) LIKE ? ESCAPE '\\' OR "
            "LOWER(IFNULL(t.notes,'')) LIKE ? ESCAPE '\\' OR "
            "t.date LIKE ? ESCAPE '\\' OR "
            "t.competence_month LIKE ? ESCAPE '\\' OR "
            "CAST(t.amount AS TEXT) LIKE ? ESCAPE '\\' OR "
            "LOWER(t.status) LIKE ? ESCAPE '\\' OR "
            "LOWER(t.type) LIKE ? ESCAPE '\\'"
            ")"
        )
        params.extend(
            [s, s_raw, s_raw, s_raw, s_raw, s_raw, s_raw, s_raw, s_raw, s_raw]
        )

    sort_by = (request.args.get("sort_by") or "date").strip()
    sort_order = (request.args.get("sort_order") or "desc").strip().lower()
    order = "DESC" if sort_order != "asc" else "ASC"
    allowed = {
        "date": "t.date",
        "amount": "t.amount",
        "description": "t.description",
        "account": "a.name",
        "category": "c.name",
        "subcategory": "s.name",
        "notes": "t.notes",
        "status": "t.status",
        "type": "t.type",
        "match_probability": "t.match_probability",
        "identity_score": "t.identity_score",
        "suggestion_confidence": "COALESCE(tss.best_confidence,0)",
    }
    order_by = allowed.get(sort_by, "t.date")

    with db_connect() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(1)
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN subcategories s ON s.id=t.subcategory_id
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()[0]
        off = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT t.id,t.date,t.competence_month,t.description,t.amount,t.type,t.status,
                   t.account_id,a.name,a.color,
                   t.category_id,c.name,c.color,c.text_color,
                   t.subcategory_id,s.name,
                   t.notes,t.imported_file_id,
                   t.suggested_category_id,sc.name,
                   t.suggested_subcategory_id,ss.name,
                   t.installment_current,t.installment_total,t.flags,
                   t.match_probability,t.match_notes,
                   t.history_match_id,t.identity_score,
                   hm.date,hm.description,ABS(hm.amount),hm.type,
                   t.ledger_id,l.name,l.color,
                   t.locked,t.classified_by,t.classified_at,
                   t.installment_plan_id,p.installment_total,p.installment_amount,
                   (SELECT COUNT(1) FROM transactions tp WHERE tp.installment_plan_id=t.installment_plan_id),
                   t.history_match_confirmed,hm.source_file_id,ha.name,hc.name,hs.name,
                   t.merchant_norm,t.transaction_method,t.counterparty_name,t.bank_reference,
                   hm.category_id,hm.subcategory_id,
                   COALESCE(tss.status,'pending'),COALESCE(tss.suggestion_count,0),
                   COALESCE(tss.best_confidence,0),COALESCE(tss.dismissed,0),tss.calculated_at,
                   tr.id,rt.id,rt.date,rt.description,rt.amount,rt.type,ra.name,tr.created_by,tr.created_at
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            LEFT JOIN installment_plans p ON p.id=t.installment_plan_id
            LEFT JOIN ledgers l ON l.id=t.ledger_id
            LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN subcategories s ON s.id=t.subcategory_id
            LEFT JOIN categories sc ON sc.id=t.suggested_category_id
            LEFT JOIN subcategories ss ON ss.id=t.suggested_subcategory_id
            LEFT JOIN classification_history hm ON hm.id=t.history_match_id
            LEFT JOIN accounts ha ON ha.id=hm.account_id
            LEFT JOIN categories hc ON hc.id=hm.category_id
            LEFT JOIN subcategories hs ON hs.id=hm.subcategory_id
            LEFT JOIN transaction_suggestion_state tss ON tss.transaction_id=t.id
            LEFT JOIN transaction_reconciliations tr
              ON tr.expense_transaction_id=t.id OR tr.income_transaction_id=t.id
            LEFT JOIN transactions rt
              ON rt.id=CASE WHEN tr.expense_transaction_id=t.id
                            THEN tr.income_transaction_id ELSE tr.expense_transaction_id END
            LEFT JOIN accounts ra ON ra.id=rt.account_id
            WHERE {" AND ".join(where)}
            ORDER BY {order_by} {order}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, off],
        ).fetchall()

        sum_row = conn.execute(
            f"""
            SELECT IFNULL(SUM(CASE WHEN t.type='income' AND NOT EXISTS (
                                      SELECT 1 FROM transaction_reconciliations rx
                                      WHERE rx.expense_transaction_id=t.id OR rx.income_transaction_id=t.id
                                    ) THEN t.amount ELSE 0 END),0),
                   IFNULL(SUM(CASE WHEN t.type='expense' AND NOT EXISTS (
                                      SELECT 1 FROM transaction_reconciliations rx
                                      WHERE rx.expense_transaction_id=t.id OR rx.income_transaction_id=t.id
                                    ) THEN t.amount ELSE 0 END),0),
                   SUM(CASE WHEN t.status='pending' AND NOT EXISTS (
                                  SELECT 1 FROM transaction_reconciliations rx
                                  WHERE rx.expense_transaction_id=t.id OR rx.income_transaction_id=t.id
                                ) THEN 1 ELSE 0 END),
                   SUM(CASE WHEN t.status='reconciled' AND NOT EXISTS (
                                  SELECT 1 FROM transaction_reconciliations rx
                                  WHERE rx.expense_transaction_id=t.id OR rx.income_transaction_id=t.id
                                ) THEN 1 ELSE 0 END)
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            LEFT JOIN categories c ON c.id=t.category_id
            LEFT JOIN subcategories s ON s.id=t.subcategory_id
            WHERE {" AND ".join(where)}
            """,
            params,
        ).fetchone()

    items = []
    for r in rows:
        item = {
            "id": r[0],
            "date": r[1],
            "competence_month": r[2],
            "description": r[3],
            "amount": r[4],
            "type": r[5],
            "status": r[6],
            "account_id": r[7],
            "account_name": r[8],
            "account_color": r[9],
            "category_id": r[10],
            "category_name": r[11],
            "category_color": r[12],
            "category_text_color": r[13],
            "subcategory_id": r[14],
            "subcategory_name": r[15],
            "notes": r[16] or "",
            "imported_file_id": r[17],
            "suggested_category_id": r[18],
            "suggested_category_name": r[19],
            "suggested_subcategory_id": r[20],
            "suggested_subcategory_name": r[21],
            "installment_current": r[22],
            "installment_total": r[23],
            "installment_label": installment_label(r[22], r[23]),
            "is_installment": bool(r[22] and r[23]),
            "flags": r[24] or "",
            "flags_list": [flag for flag in (r[24] or "").split(",") if flag],
            "match_probability": float(r[25] or 0.0),
            "match_notes": r[26] or "",
            "history_match_id": r[27],
            "identity_score": float(r[28] or 0.0),
            "match_category_id": r[52],
            "match_category_name": r[46],
            "match_subcategory_id": r[53],
            "match_subcategory_name": r[47],
            "match_history_date": r[29],
            "match_history_description": r[30],
            "match_history_amount": float(r[31] or 0.0),
            "match_history_type": r[32],
            "ledger_id": r[33],
            "ledger_name": r[34],
            "ledger_color": r[35],
            "locked": bool(r[36]),
            "classified_by": r[37] or "",
            "classified_at": r[38] or "",
            "installment_plan_id": r[39],
            "installment_plan_total": r[40],
            "installment_plan_amount": float(r[41] or 0.0),
            "installment_plan_members": int(r[42] or 0),
            "classification_inherited": bool(r[39] and r[10]),
            "history_match_confirmed": bool(r[43]),
            "match_history_source": r[44] or "",
            "match_history_account_name": r[45] or "",
            "match_history_category_name": r[46] or "",
            "match_history_subcategory_name": r[47] or "",
            "merchant_norm": r[48] or "",
            "transaction_method": r[49] or "other",
            "counterparty_name": r[50] or "",
            "bank_reference": r[51] or "",
            "history_link_threshold": HISTORY_LINK_CANDIDATE_THRESHOLD,
            "suggestion_state": r[54],
            "suggestion_count": int(r[55] or 0),
            "suggestion_confidence": float(r[56] or 0.0),
            "suggestion_dismissed": bool(r[57]),
            "suggestion_calculated_at": r[58] or "",
            "reconciliation_id": r[59],
            "reconciliation_counterpart_id": r[60],
            "reconciliation_counterpart_date": r[61],
            "reconciliation_counterpart_description": r[62] or "",
            "reconciliation_counterpart_amount": float(r[63] or 0.0),
            "reconciliation_counterpart_type": r[64],
            "reconciliation_counterpart_account_name": r[65] or "",
            "reconciled_by": r[66] or "",
            "reconciled_at": r[67] or "",
        }
        item.update(
            historical_match_factors(
                r[1], r[4], r[3], r[29], r[31], r[30], r[22], r[23]
            )
        )
        items.append(item)
    total_pages = (total + page_size - 1) // page_size
    total_income = float(sum_row[0] or 0)
    total_expense = float(sum_row[1] or 0)
    pending_count = int(sum_row[2] or 0)
    rec_count = int(sum_row[3] or 0)
    return jsonify(
        {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "summary": {
                "total_income": total_income,
                "total_expense": total_expense,
                "balance": total_income + total_expense,
                "pending_count": pending_count,
                "reconciled_count": rec_count,
            },
        }
    )


@transactions_bp.route("/api/v1/transactions/<tx_id>/classify", methods=["PATCH"])
@allow_collab_write
def classify(tx_id: str):
    data = request.get_json(force=True)
    cat = (data.get("category_id") or "").strip()
    sub = (data.get("subcategory_id") or "").strip() or None
    notes = data.get("notes", "")
    source = data.get("classification_source", "manual")
    apply_to_installments = data.get("apply_to_installments", True) is not False
    if not cat:
        return jsonify(
            {"detail": "category_id obrigatorio", "code": "VALIDATION_ERROR"}
        ), 400
    if source == "auto":
        return jsonify(
            {
                "detail": "Autoclassificacao nao e permitida",
                "code": "AUTO_CLASSIFICATION_DISABLED",
            }
        ), 409
    status = "reconciled"
    user = current_user()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        tx = conn.execute(
            """
            SELECT id,account_id,date,description,description_norm,amount,type,
                   locked,category_id,subcategory_id,notes,status,
                   installment_plan_id,installment_current,installment_total,
                   history_match_id,history_match_confirmed,identity_score
            FROM transactions
            WHERE id=?
            """,
            (tx_id,),
        ).fetchone()
        if not tx:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        if int(tx[7] or 0) == 1:
            # Protegido: exige desbloqueio explicito (endpoint /unlock) antes de editar.
            return jsonify(
                {
                    "detail": "Lancamento protegido. Desbloqueie explicitamente para alterar.",
                    "code": "TX_LOCKED",
                }
            ), 423
        if (
            tx[15]
            and not bool(tx[16])
            and float(tx[17] or 0) >= HISTORY_LINK_CANDIDATE_THRESHOLD
        ):
            return jsonify(
                {
                    "detail": "Revise o vinculo historico antes de classificar este lancamento.",
                    "code": "HISTORY_LINK_REVIEW_REQUIRED",
                }
            ), 409
        validation_error, validation_status = validate_classification_selection(conn, cat, sub)
        if validation_error:
            return jsonify(validation_error), validation_status
        old_cat, old_sub, old_notes, old_status = tx[8], tx[9], tx[10] or "", tx[11]
        conn.execute(
            """
            UPDATE transactions
            SET category_id=?, subcategory_id=?, notes=?, status=?,
                locked=1, classified_by=?, classified_at=?
            WHERE id=?
            """,
            (cat, sub, notes, status, user.get("username") or "", now, tx_id),
        )
        if old_cat != cat:
            record_audit(
                user,
                "classify",
                "transaction",
                tx_id,
                "category_id",
                old_cat,
                cat,
                conn=conn,
            )
        if old_sub != sub:
            record_audit(
                user,
                "classify",
                "transaction",
                tx_id,
                "subcategory_id",
                old_sub,
                sub,
                conn=conn,
            )
        if (old_notes or "") != (notes or ""):
            record_audit(
                user,
                "classify",
                "transaction",
                tx_id,
                "notes",
                old_notes,
                notes,
                conn=conn,
            )
        if old_status != status:
            record_audit(
                user,
                "classify",
                "transaction",
                tx_id,
                "status",
                old_status,
                status,
                conn=conn,
            )
        affected_ids = [tx_id]
        installment_plan_id = tx[12]
        if apply_to_installments and installment_plan_id:
            plan = conn.execute(
                "SELECT category_id,subcategory_id FROM installment_plans WHERE id=?",
                (installment_plan_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE installment_plans
                SET category_id=?,subcategory_id=?,classified_by=?,classified_at=?,updated_at=?
                WHERE id=?
                """,
                (cat, sub, user.get("username") or "", now, now, installment_plan_id),
            )
            siblings = conn.execute(
                """
                SELECT id FROM transactions
                WHERE installment_plan_id=? AND id<>? AND locked=0
                  AND NOT (
                    history_match_id IS NOT NULL
                    AND history_match_confirmed=0
                    AND identity_score>=?
                  )
                """,
                (installment_plan_id, tx_id, HISTORY_LINK_CANDIDATE_THRESHOLD),
            ).fetchall()
            sibling_ids = [row[0] for row in siblings]
            for sibling_id in sibling_ids:
                conn.execute(
                    """
                    UPDATE transactions
                    SET category_id=?,subcategory_id=?,status=?,locked=1,
                        classified_by=?,classified_at=?
                    WHERE id=?
                    """,
                    (cat, sub, status, user.get("username") or "", now, sibling_id),
                )
            affected_ids.extend(sibling_ids)
            record_audit(
                user,
                "classify_installment_plan",
                "installment_plan",
                installment_plan_id,
                "classification",
                f"{(plan or ('', ''))[0] or ''}|{(plan or ('', ''))[1] or ''}",
                f"{cat}|{sub or ''}",
                detail=f"{len(affected_ids)} lancamento(s) atualizado(s)",
                conn=conn,
            )
        if source not in ("auto", "identity"):
            history_source = f"manual:{tx_id}"
            conn.execute(
                "DELETE FROM classification_history WHERE source_file_id=?",
                (history_source,),
            )
            conn.execute(
                """
                INSERT INTO classification_history(
                  id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    history_source,
                    tx[1],
                    tx[2],
                    tx[3],
                    tx[4],
                    abs(float(tx[5] or 0)),
                    tx[6],
                    cat,
                    sub,
                ),
            )
        for affected_id in affected_ids:
            conn.execute(
                "DELETE FROM transaction_suggestions WHERE transaction_id=?",
                (affected_id,),
            )
            conn.execute(
                "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                (affected_id,),
            )
    return jsonify(
        {
            "id": tx_id,
            "ok": True,
            "status": status,
            "locked": True,
            "classified_by": user.get("username") or "",
            "classified_at": now,
            "installment_plan_id": tx[12],
            "affected_ids": affected_ids,
            "affected_count": len(affected_ids),
        }
    )


@transactions_bp.route(
    "/api/v1/transactions/<tx_id>/unlock", methods=["POST", "OPTIONS"]
)
def unlock_transaction(tx_id: str):
    """Desbloqueio explicito de um lancamento protegido (somente admin, com auditoria)."""
    forbidden = require_admin()
    if forbidden:
        return forbidden
    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip()
    user = current_user()
    with db_connect() as conn:
        tx = conn.execute(
            "SELECT id, locked FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if not tx:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        if int(tx[1] or 0) == 0:
            return jsonify({"id": tx_id, "locked": False, "ok": True})
        conn.execute("UPDATE transactions SET locked=0 WHERE id=?", (tx_id,))
        record_audit(
            user,
            "unlock",
            "transaction",
            tx_id,
            "locked",
            1,
            0,
            detail=reason,
            conn=conn,
        )
    return jsonify({"id": tx_id, "locked": False, "ok": True})


@transactions_bp.route("/api/v1/transactions/<tx_id>/flags", methods=["PATCH"])
@allow_collab_write
def update_transaction_flags(tx_id: str):
    data = request.get_json(force=True) or {}
    flags_text = sanitize_transaction_flags(data.get("flags", ""))
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id, flags FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if not exists:
            return jsonify({"detail": "Nao encontrado", "code": "NOT_FOUND"}), 404
        conn.execute("UPDATE transactions SET flags=? WHERE id=?", (flags_text, tx_id))
        if (exists[1] or "") != flags_text:
            record_audit(
                current_user(),
                "update_flags",
                "transaction",
                tx_id,
                "flags",
                exists[1] or "",
                flags_text,
                conn=conn,
            )
    return jsonify(
        {
            "id": tx_id,
            "flags": flags_text,
            "flags_list": [flag for flag in flags_text.split(",") if flag],
        }
    )


def suggestion_fingerprint(row: Any) -> str:
    payload = "|".join(str(value or "") for value in row)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cached_suggestions(
    conn, tx_ids: list[str]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    items: dict[str, list[dict[str, Any]]] = {tx_id: [] for tx_id in tx_ids}
    states: dict[str, str] = {tx_id: "pending" for tx_id in tx_ids}
    if not tx_ids:
        return items, states
    placeholders = ",".join("?" for _ in tx_ids)
    state_rows = conn.execute(
        f"SELECT transaction_id,status FROM transaction_suggestion_state WHERE transaction_id IN ({placeholders})",
        tx_ids,
    ).fetchall()
    for row in state_rows:
        states[row[0]] = row[1] or "pending"
    rows = conn.execute(
        f"""
        SELECT ts.transaction_id,ts.category_id,c.name,ts.subcategory_id,IFNULL(s.name,''),
               ts.confidence,ts.category_probability,ts.subcategory_probability,
               ts.frequency,ts.history_evidence,ts.transaction_evidence,
               ts.justification,ts.subcategories_json,ts.rank
        FROM transaction_suggestions ts
        LEFT JOIN categories c ON c.id=ts.category_id
        LEFT JOIN subcategories s ON s.id=ts.subcategory_id
        WHERE ts.transaction_id IN ({placeholders})
        ORDER BY ts.transaction_id,ts.rank
        """,
        tx_ids,
    ).fetchall()
    for row in rows:
        items[row[0]].append(
            {
                "category_id": row[1],
                "category_name": row[2] or "",
                "subcategory_id": row[3],
                "subcategory_name": row[4] or "",
                "probability": float(row[6] or 0),
                "relative_score": float(row[6] or 0),
                "confidence": float(row[5] or 0),
                "category_probability": float(row[6] or 0),
                "subcategory_probability": float(row[7] or 0),
                "frequency": int(row[8] or 0),
                "history_evidence": int(row[9] or 0),
                "transaction_evidence": int(row[10] or 0),
                "justification": row[11] or "",
                "subcategories": json.loads(row[12] or "[]"),
                "rank": int(row[13] or 0),
            }
        )
    return items, states


def _append_suggestion_job_log(
    conn, job_id: str, message: str, processed: int | None = None
) -> None:
    row = conn.execute(
        "SELECT logs_json FROM suggestion_jobs WHERE id=?", (job_id,)
    ).fetchone()
    logs = json.loads(row[0] or "[]") if row else []
    logs = (
        logs + [{"time": dt.datetime.now().strftime("%H:%M:%S"), "message": message}]
    )[-40:]
    if processed is None:
        conn.execute(
            "UPDATE suggestion_jobs SET message=?,logs_json=? WHERE id=?",
            (message, json.dumps(logs, ensure_ascii=False), job_id),
        )
    else:
        conn.execute(
            "UPDATE suggestion_jobs SET processed=?,message=?,logs_json=? WHERE id=?",
            (processed, message, json.dumps(logs, ensure_ascii=False), job_id),
        )


def _run_suggestion_job(job_id: str, full: bool = False, batch_size: int = 20) -> None:
    try:
        with db_connect() as conn:
            conn.execute(
                "UPDATE suggestion_jobs SET status='running',started_at=?,message='Carregando evidencias' WHERE id=?",
                (dt.datetime.now().isoformat(timespec="seconds"), job_id),
            )
            _append_suggestion_job_log(
                conn, job_id, "Carregando base historica e classificacoes confirmadas"
            )
            evidence_by_type = load_suggestion_evidence(conn)
            rows = conn.execute(
                """
                SELECT t.id,t.date,t.description,t.description_norm,t.amount,t.type,t.account_id,
                       IFNULL(t.merchant_norm,''),IFNULL(t.transaction_method,'other'),
                       IFNULL(t.counterparty_name,''),IFNULL(t.bank_reference,''),
                       qs.fingerprint,qs.status
                FROM transactions t
                LEFT JOIN transaction_suggestion_state qs ON qs.transaction_id=t.id
                WHERE t.category_id IS NULL AND t.locked=0 AND t.status='pending'
                  AND NOT (t.history_match_id IS NOT NULL AND t.history_match_confirmed=0 AND t.identity_score>=?)
                  AND NOT EXISTS (SELECT 1 FROM transaction_reconciliations r
                                  WHERE r.expense_transaction_id=t.id OR r.income_transaction_id=t.id)
                ORDER BY t.date DESC,t.id
                """,
                (HISTORY_LINK_CANDIDATE_THRESHOLD,),
            ).fetchall()
            targets: list[tuple[Any, str]] = []
            for row in rows:
                fingerprint = suggestion_fingerprint(row[1:11])
                if not full and row[11] == fingerprint and row[12] == "completed":
                    continue
                targets.append((row, fingerprint))
            conn.execute(
                "UPDATE suggestion_jobs SET total=? WHERE id=?", (len(targets), job_id)
            )
            _append_suggestion_job_log(
                conn, job_id, f"{len(targets)} lancamento(s) aguardando calculo"
            )
            conn.commit()

            with_suggestions = 0
            without_suggestions = 0
            errors = 0
            for index, (row, fingerprint) in enumerate(targets, start=1):
                tx_id = row[0]
                try:
                    suggestions = (
                        build_suggestions_for_tx(
                            conn, tx_id, evidence_by_type=evidence_by_type
                        )
                        or []
                    )
                    suggestions = suggestions[:3]
                    dismissed_row = conn.execute(
                        "SELECT dismissed FROM transaction_suggestion_state WHERE transaction_id=?",
                        (tx_id,),
                    ).fetchone()
                    dismissed = int((dismissed_row or (0,))[0] or 0)
                    calculated_at = dt.datetime.now(dt.timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    conn.execute(
                        "DELETE FROM transaction_suggestions WHERE transaction_id=?",
                        (tx_id,),
                    )
                    for rank, suggestion in enumerate(suggestions, start=1):
                        conn.execute(
                            """
                            INSERT INTO transaction_suggestions(
                              transaction_id,rank,category_id,subcategory_id,confidence,
                              category_probability,subcategory_probability,frequency,
                              history_evidence,transaction_evidence,justification,
                              subcategories_json,calculated_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                tx_id,
                                rank,
                                suggestion["category_id"],
                                suggestion.get("subcategory_id"),
                                float(suggestion.get("confidence") or 0),
                                float(suggestion.get("category_probability") or 0),
                                float(suggestion.get("subcategory_probability") or 0),
                                int(suggestion.get("frequency") or 0),
                                int(suggestion.get("history_evidence") or 0),
                                int(suggestion.get("transaction_evidence") or 0),
                                suggestion.get("justification") or "",
                                json.dumps(
                                    suggestion.get("subcategories") or [],
                                    ensure_ascii=False,
                                ),
                                calculated_at,
                            ),
                        )
                    best_confidence = (
                        float(suggestions[0].get("confidence") or 0)
                        if suggestions
                        else 0.0
                    )
                    conn.execute(
                        """
                        INSERT INTO transaction_suggestion_state(
                          transaction_id,fingerprint,status,suggestion_count,best_confidence,
                          dismissed,calculated_at,error
                        ) VALUES (?,?, 'completed', ?,?,?,?,'')
                        ON CONFLICT(transaction_id) DO UPDATE SET
                          fingerprint=excluded.fingerprint,status='completed',
                          suggestion_count=excluded.suggestion_count,
                          best_confidence=excluded.best_confidence,
                          calculated_at=excluded.calculated_at,error=''
                        """,
                        (
                            tx_id,
                            fingerprint,
                            len(suggestions),
                            best_confidence,
                            dismissed,
                            calculated_at,
                        ),
                    )
                    if suggestions:
                        with_suggestions += 1
                    else:
                        without_suggestions += 1
                except Exception as exc:
                    logger.exception(
                        "Falha ao calcular sugestoes da transacao %s", tx_id
                    )
                    errors += 1
                    calculated_at = dt.datetime.now(dt.timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    conn.execute(
                        """
                        INSERT INTO transaction_suggestion_state(
                          transaction_id,fingerprint,status,suggestion_count,best_confidence,
                          dismissed,calculated_at,error
                        ) VALUES (?,?,'failed',0,0,0,?,?)
                        ON CONFLICT(transaction_id) DO UPDATE SET
                          fingerprint=excluded.fingerprint,status='failed',calculated_at=excluded.calculated_at,error=excluded.error
                        """,
                        (
                            tx_id,
                            fingerprint,
                            calculated_at,
                            f"{type(exc).__name__}: {exc}"[:500],
                        ),
                    )
                if index % batch_size == 0 or index == len(targets):
                    conn.execute(
                        """
                        UPDATE suggestion_jobs
                        SET processed=?,updated=?,with_suggestions=?,without_suggestions=?
                        WHERE id=?
                        """,
                        (
                            index,
                            index - errors,
                            with_suggestions,
                            without_suggestions,
                            job_id,
                        ),
                    )
                    _append_suggestion_job_log(
                        conn, job_id, f"{index} de {len(targets)} analisados", index
                    )
                    conn.commit()
            final_message = (
                f"Concluido: {with_suggestions} com sugestoes, {without_suggestions} sem evidencia"
                + (f", {errors} com erro" if errors else "")
            )
            conn.execute(
                """
                UPDATE suggestion_jobs
                SET status='completed',processed=?,updated=?,with_suggestions=?,without_suggestions=?,
                    message=?,error=?,finished_at=? WHERE id=?
                """,
                (
                    len(targets),
                    len(targets) - errors,
                    with_suggestions,
                    without_suggestions,
                    final_message,
                    f"{errors} lancamento(s) falharam" if errors else "",
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )
            _append_suggestion_job_log(conn, job_id, final_message, len(targets))
    except Exception as exc:
        logger.exception("Job de sugestoes %s falhou", job_id)
        with db_connect() as conn:
            conn.execute(
                """
                UPDATE suggestion_jobs SET status='failed',error=?,message='Falha no calculo',finished_at=? WHERE id=?
                """,
                (
                    f"{type(exc).__name__}: {exc}"[:1000],
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )


def enqueue_suggestion_job(full: bool = False) -> str:
    with db_connect() as conn:
        active = conn.execute(
            "SELECT id FROM suggestion_jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if active:
            return active[0]
        job_id = str(uuid.uuid4())
        try:
            conn.execute(
                """
                INSERT INTO suggestion_jobs(id,status,mode,message,created_at)
                VALUES (?,'queued',?,'Aguardando inicio',?)
                """,
                (
                    job_id,
                    "full" if full else "incremental",
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )
        except Exception:
            # Dois workers podem receber o clique ao mesmo tempo. O indice parcial
            # e esta releitura garantem um unico job ativo sem duplicar o trabalho.
            logger.info("Job de sugestoes concorrente detectado", exc_info=True)
            conn.rollback()
            active = conn.execute(
                "SELECT id FROM suggestion_jobs WHERE status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not active:
                raise
            return active[0]
    if WORKER_MODE == "inline":
        threading.Thread(
            target=_run_suggestion_job,
            args=(job_id, full),
            daemon=True,
            name=f"suggestions-{job_id[:8]}",
        ).start()
    return job_id


def suggestion_job_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "status": row[1],
        "mode": row[2],
        "processed": int(row[3] or 0),
        "total": int(row[4] or 0),
        "updated": int(row[5] or 0),
        "with_suggestions": int(row[6] or 0),
        "without_suggestions": int(row[7] or 0),
        "message": row[8] or "",
        "logs": json.loads(row[9] or "[]"),
        "error": row[10] or "",
        "created_at": row[11],
        "started_at": row[12],
        "finished_at": row[13],
    }


def _run_probability_recalculation_job(job_id: str) -> None:
    try:
        _recalculate_probabilities_impl(job_id=job_id)
    except Exception as exc:
        logger.exception("Job de recalculo %s falhou", job_id)
        with db_connect() as conn:
            conn.execute(
                "UPDATE recalculation_jobs SET status='failed', error=?, finished_at=? WHERE id=?",
                (
                    f"{type(exc).__name__}: {exc}"[:1000],
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )


def enqueue_probability_recalculation() -> str:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with db_connect() as conn:
        existing = conn.execute(
            """
            SELECT id FROM recalculation_jobs
            WHERE status IN ('queued','running')
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        if existing:
            return existing[0]
        job_id = str(uuid.uuid4())
        total = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE status IN ('pending','reconciled','auto_classified')"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO recalculation_jobs(id,status,processed,total,updated,error,created_at)
            VALUES (?, 'queued', 0, ?, 0, '', ?)
            """,
            (job_id, total, now),
        )
    if WORKER_MODE == "inline":
        threading.Thread(
            target=_run_probability_recalculation_job,
            args=(job_id,),
            daemon=True,
            name=f"history-recalc-{job_id[:8]}",
        ).start()
    return job_id


def _recalculate_probabilities_impl(job_id: str | None = None, batch_size: int = 100):
    updated = 0
    linked_classified = 0
    with db_connect() as conn:
        shadow_rows = conn.execute(
            """
            SELECT t.id,t.description,a.type,t.installment_current,t.installment_total
            FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
            WHERE IFNULL(t.merchant_norm,'')=''
            """
        ).fetchall()
        for index, row in enumerate(shadow_rows, start=1):
            store_shadow_metadata(
                conn, "transactions", row[0], row[1], row[2] or "", row[3], row[4]
            )
            if index % 200 == 0:
                conn.commit()
        shadow_history = conn.execute(
            """
            SELECT h.id,h.description,a.type
            FROM classification_history h LEFT JOIN accounts a ON a.id=h.account_id
            WHERE IFNULL(h.merchant_norm,'')=''
            """
        ).fetchall()
        for index, row in enumerate(shadow_history, start=1):
            store_shadow_metadata(
                conn, "classification_history", row[0], row[1], row[2] or ""
            )
            if index % 200 == 0:
                conn.commit()
        rows = conn.execute(
            """
            SELECT id,date,description,description_norm,amount,type,account_id,status,
                   history_match_id,history_match_confirmed,history_match_rejected_id,
                   installment_current,installment_total
            FROM transactions
            WHERE status IN ('pending','reconciled','auto_classified')
            """
        ).fetchall()
        if job_id:
            conn.execute(
                "UPDATE recalculation_jobs SET status='running', total=?, started_at=? WHERE id=?",
                (len(rows), dt.datetime.now().isoformat(timespec="seconds"), job_id),
            )
            conn.commit()
        hist_cache: dict[str, list[tuple[Any, ...]]] = {}
        for tx_type in ("expense", "income"):
            hist_cache[tx_type] = conn.execute(
                """
                SELECT id,date,description_norm,ABS(amount),account_id,category_id,subcategory_id
                FROM classification_history
                WHERE type=?
                """,
                (tx_type,),
            ).fetchall()
        for index, r in enumerate(rows, start=1):
            if job_id and index > 1 and (index - 1) % batch_size == 0:
                conn.execute(
                    "UPDATE recalculation_jobs SET processed=?, updated=? WHERE id=?",
                    (index - 1, updated, job_id),
                )
                conn.commit()
            tx = {
                "id": r[0],
                "date": r[1],
                "description": r[2],
                "description_norm": r[3],
                "amount": r[4],
                "type": r[5],
                "account_id": r[6],
                "installment_current": r[11],
                "installment_total": r[12],
            }
            status = r[7]
            confirmed_match_id = r[8] if bool(r[9]) else None
            rejected_match_id = r[10]
            if confirmed_match_id:
                continue
            identity = find_identity_match(conn, tx, hist_cache=hist_cache)
            if (
                not identity
                or float(identity.get("identity_score") or 0)
                < HISTORY_LINK_CANDIDATE_THRESHOLD
                or identity.get("history_match_id") == rejected_match_id
            ):
                conn.execute(
                    """
                    UPDATE transactions
                    SET match_probability=0,
                        match_notes='',
                        history_match_id=NULL,
                        history_match_confirmed=0,
                        identity_score=0,
                        suggested_category_id=NULL,
                        suggested_subcategory_id=NULL
                    WHERE id=?
                    """,
                    (r[0],),
                )
                continue
            if status == "pending":
                conn.execute(
                    """
                    UPDATE transactions
                    SET match_probability=?,
                        suggested_category_id=?,
                        suggested_subcategory_id=?,
                        match_notes=?,
                        history_match_id=?,
                        history_match_confirmed=0,
                        identity_score=?
                    WHERE id=?
                    """,
                    (
                        float(identity.get("identity_score") or 0),
                        identity.get("category_id"),
                        identity.get("subcategory_id"),
                        (
                            "Match pelo valor total parcelado na base historica"
                            if identity.get("match_basis") == "installment_total"
                            else "Match com base historica"
                        ),
                        identity.get("history_match_id"),
                        float(identity.get("identity_score") or 0),
                        r[0],
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE transactions
                    SET match_probability=?,
                        match_notes=?,
                        history_match_id=?,
                        history_match_confirmed=0,
                        identity_score=?
                    WHERE id=?
                    """,
                    (
                        float(identity.get("identity_score") or 0),
                        (
                            "Match pelo valor total parcelado na base historica"
                            if identity.get("match_basis") == "installment_total"
                            else "Match com base historica"
                        ),
                        identity.get("history_match_id"),
                        float(identity.get("identity_score") or 0),
                        r[0],
                    ),
                )
            conn.execute(
                "DELETE FROM transaction_suggestions WHERE transaction_id=?", (r[0],)
            )
            conn.execute(
                "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                (r[0],),
            )
            updated += 1
        if job_id:
            conn.execute(
                """
                UPDATE recalculation_jobs
                SET status='completed', processed=?, updated=?, finished_at=?
                WHERE id=?
                """,
                (
                    len(rows),
                    updated,
                    dt.datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )
    return {
        "updated": updated,
        "total": len(rows),
        "linked_classified": linked_classified,
    }


@transactions_bp.route("/api/v1/transactions/bulk-classify", methods=["PATCH"])
@allow_collab_write
def bulk_classify():
    data = request.get_json(force=True)
    ids = data.get("ids") or []
    cat = (data.get("category_id") or "").strip()
    sub = (data.get("subcategory_id") or "").strip() or None
    include_classified = bool(data.get("include_classified"))
    if not ids or not cat:
        return jsonify(
            {"detail": "ids e category_id obrigatorios", "code": "VALIDATION_ERROR"}
        ), 400
    user = current_user()
    if include_classified:
        forbidden = require_admin()
        if forbidden:
            return forbidden
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        qmarks = ",".join(["?"] * len(ids))
        validation_error, validation_status = validate_classification_selection(conn, cat, sub)
        if validation_error:
            return jsonify(validation_error), validation_status
        blocked_rows = conn.execute(
            f"""
            SELECT id,locked,category_id,history_match_id,history_match_confirmed,identity_score
            FROM transactions WHERE id IN ({qmarks})
            """,
            ids,
        ).fetchall()
        available_ids = {r[0] for r in blocked_rows}
        locked_ids = {r[0] for r in blocked_rows if int(r[1] or 0) == 1}
        classified_locked_ids = {
            r[0] for r in blocked_rows if int(r[1] or 0) == 1 and r[2]
        }
        link_ids = {
            r[0]
            for r in blocked_rows
            if r[3]
            and not bool(r[4])
            and float(r[5] or 0) >= HISTORY_LINK_CANDIDATE_THRESHOLD
        }
        protected_locked_ids = locked_ids - classified_locked_ids
        skipped_locked_ids = (
            protected_locked_ids
            if include_classified
            else locked_ids
        )
        target_ids = [
            i
            for i in ids
            if i in available_ids and i not in skipped_locked_ids and i not in link_ids
        ]
        overwritten_ids = [i for i in target_ids if i in classified_locked_ids]
        updated = 0
        if target_ids:
            qmarks2 = ",".join(["?"] * len(target_ids))
            cursor = conn.execute(
                f"""
                UPDATE transactions
                SET category_id=?, subcategory_id=?, status='reconciled',
                    locked=1, classified_by=?, classified_at=?
                WHERE id IN ({qmarks2})
                """,
                [cat, sub, user.get("username") or "", now] + target_ids,
            )
            updated = cursor.rowcount or 0
            for tid in target_ids:
                record_audit(
                    user,
                    "bulk_reclassify" if tid in classified_locked_ids else "bulk_classify",
                    "transaction",
                    tid,
                    "category_id",
                    "",
                    cat,
                    conn=conn,
                )
                conn.execute(
                    "DELETE FROM transaction_suggestions WHERE transaction_id=?", (tid,)
                )
                conn.execute(
                    "DELETE FROM transaction_suggestion_state WHERE transaction_id=?",
                    (tid,),
                )
    return jsonify(
        {
            "updated": updated,
            "updated_ids": target_ids if updated else [],
            "overwritten_classified": len(overwritten_ids),
            "overwritten_classified_ids": overwritten_ids,
            "skipped_locked": len(skipped_locked_ids),
            "skipped_locked_ids": sorted(skipped_locked_ids),
            "skipped_history_links": len(link_ids),
            "skipped_history_link_ids": sorted(link_ids),
            "skipped_missing": len(set(ids) - available_ids),
        }
    )




def _claim_queued_job(table: str, columns: str) -> Any | None:
    allowed_tables = {
        "import_jobs",
        "seed_import_jobs",
        "suggestion_jobs",
        "recalculation_jobs",
    }
    if table not in allowed_tables:
        raise ValueError(f"Fila desconhecida: {table}")
    with db_connect() as conn:
        row = conn.execute(
            f"SELECT {columns} FROM {table} WHERE status='queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        updated = conn.execute(
            f"UPDATE {table} SET status='claimed' WHERE id=? AND status='queued'",
            (row[0],),
        )
        return row if updated.rowcount == 1 else None


def process_next_queued_job() -> bool:
    imported = _claim_queued_job(
        "import_jobs", "id,preview_id,confirm_duplicates,competence_month"
    )
    if imported:
        _run_import_job(imported[0], imported[1], bool(imported[2]), imported[3] or "")
        return True
    seed_job = _claim_queued_job("seed_import_jobs", "id,source_path,replace_existing")
    if seed_job:
        _run_seed_import_job(seed_job[0], Path(seed_job[1]), bool(seed_job[2]))
        return True
    suggestion = _claim_queued_job("suggestion_jobs", "id,mode")
    if suggestion:
        _run_suggestion_job(suggestion[0], suggestion[1] == "full")
        return True
    recalculation = _claim_queued_job("recalculation_jobs", "id")
    if recalculation:
        _run_probability_recalculation_job(recalculation[0])
        return True
    return False


def recover_interrupted_process_jobs() -> int:
    """Refile jobs somente depois de o worker obter seu lease exclusivo.

    O processo web nunca chama esta funcao. Assim, durante um deploy, um worker
    novo nao altera jobs que ainda estejam sendo finalizados pelo worker antigo.
    """
    recovered = 0
    with db_connect() as conn:
        for table, extra_fields, message in (
            (
                "seed_import_jobs",
                "phase='interrupted',",
                "Processamento interrompido; retomando pela fila",
            ),
            ("suggestion_jobs", "", "Processamento interrompido; retomando pela fila"),
            (
                "import_jobs",
                "phase='interrupted',",
                "Processamento interrompido; retomando pela fila",
            ),
            (
                "recalculation_jobs",
                "",
                "Processamento interrompido; retomando pela fila",
            ),
        ):
            message_assignment = "message=?," if table != "recalculation_jobs" else ""
            params = (message,) if message_assignment else ()
            updated = conn.execute(
                f"""
                UPDATE {table}
                SET status='queued', {extra_fields} {message_assignment}
                    error='Processamento interrompido por reinicializacao do worker',
                    finished_at=''
                WHERE status IN ('running','claimed')
                """,
                params,
            )
            recovered += int(updated.rowcount or 0)
    return recovered


for blueprint in ALL_BLUEPRINTS:
    app.register_blueprint(blueprint)


def init_app() -> None:
    """Inicializacao completa (usada tanto no dev local quanto no gunicorn).

    No Postgres, um advisory lock serializa a criacao/migracao do schema quando
    varios workers do gunicorn sobem ao mesmo tempo.
    """
    lock_conn = None
    try:
        if IS_POSTGRES:
            lock_conn = db_connect(direct=True)
            lock_conn.execute("SELECT pg_advisory_lock(815501)")
        init_db()
        auth_mod.init_auth_db()
        auth_mod.bootstrap_admin()
        seed()
    finally:
        if lock_conn is not None:
            lock_conn.close()  # encerrar a sessao libera o advisory lock


# Executa na importacao para que `gunicorn app:app` ja suba com o banco pronto.
init_app()


if __name__ == "__main__":
    import os as _os

    _port = int(_os.environ.get("PORT") or "5061")
    app.run(
        host=_os.environ.get("HOST") or "127.0.0.1",
        port=_port,
        debug=False,
        use_reloader=False,
    )
