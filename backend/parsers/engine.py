"""
parsers/engine.py
Motor de importação inteligente do Conciliador Financeiro.

Substitui os parsers dispersos em app.py por um pipeline estruturado:
  1. detect_format()       — identifica banco, tipo de documento, encoding
  2. parse_raw()           — extrai linhas brutas preservando metadados
  3. enrich_transaction()  — parcelas, flags, tipo (income/expense)
  4. validate_quality()    — saldo, integridade, linhas suspeitas
  5. ImportResult          — dataclass com tudo para o endpoint consumir

Regras de negócio:
  - Conta/cartão obrigatório (sem adivinhação automática)
  - Duplicata interna (mesmo arquivo) = permitida
  - Duplicata contra banco = nunca reinserida
  - Cartão: quase tudo expense; storno/cashback/reembolso = income
  - Parcelas: detectadas em coluna dedicada OU sufixo da descrição
  - Transferências entre contas próprias: flagadas como INTER_ACCOUNT
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import openpyxl
except ImportError:
    openpyxl = None  # type: ignore

try:
    import xlrd
except ImportError:
    xlrd = None  # type: ignore

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None  # type: ignore


# ─────────────────────────────────────────────────────────────
#  DATACLASSES
# ─────────────────────────────────────────────────────────────

@dataclass
class RawTx:
    """Linha extraída do arquivo, ainda sem enriquecimento."""
    date: str                           # ISO: 2025-11-01
    description_raw: str                # descrição original exatamente como no arquivo
    amount_raw: float                   # valor absoluto (sempre positivo)
    tx_type_raw: str                    # 'income' | 'expense' — sinal do arquivo
    installment_raw: str = ""           # conteúdo bruto da coluna Parcela (CSV) ou sufixo (PDF)
    source_line: str = ""               # linha original para debug


@dataclass
class EnrichedTx:
    """Transação após enriquecimento completo, pronta para persistência."""
    date: str
    description: str                    # descrição limpa (sem sufixo de parcela)
    description_norm: str               # norm_text(description)
    amount_signed: float                # negativo=expense, positivo=income
    tx_type: str                        # 'income' | 'expense'
    installment_current: int | None
    installment_total: int | None
    installment_label: str | None       # ex: "Parcela 3 de 12"
    is_installment: bool
    flags: list[str]                    # ['INTER_ACCOUNT', 'CASHBACK', 'TAX', ...]
    source_line: str = ""


@dataclass
class FormatDetection:
    bank: str                           # 'SANTANDER' | 'XP' | 'NUBANK' | 'GENERIC'
    doc_type: str                       # 'EXTRATO_CORRENTE' | 'FATURA_CARTAO' | 'COMPROVANTE'
    file_format: str                    # 'csv' | 'xlsx' | 'xls' | 'pdf'
    encoding: str                       # 'utf-8-sig' | 'latin-1' | ...
    confidence: float                   # 0.0 – 1.0


@dataclass
class BalanceCheck:
    saldo_anterior: float | None
    saldo_final_declarado: float | None
    saldo_calculado: float | None
    diferenca: float | None
    ok: bool
    message: str = ""


@dataclass
class ImportResult:
    """Resultado completo do pipeline — retornado pelo endpoint."""
    txs: list[EnrichedTx]
    format_detection: FormatDetection
    balance_check: BalanceCheck
    warnings: list[str]
    rejected_lines: list[str]           # linhas com data mas sem match (debug)
    discarded_lines: list[str]          # linhas reconhecidas mas descartadas por regra de produto
    total_parsed: int = 0
    total_installments: int = 0
    total_inter_account: int = 0
    total_cashback: int = 0
    empty_statement_confirmed: bool = False


# ─────────────────────────────────────────────────────────────
#  NORMALIZAÇÃO
# ─────────────────────────────────────────────────────────────

def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(c)
    )


def norm_text(text: str) -> str:
    """Normaliza para comparação: minúsculas, sem acento, sem pontuação, espaços simples."""
    cleaned = strip_accents((text or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def norm_text_keep_slash(text: str) -> str:
    """Como norm_text mas preserva barras (necessário para detectar parcelas 3/12)."""
    cleaned = strip_accents((text or "").lower())
    cleaned = re.sub(r"[^a-z0-9\s/]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# ─────────────────────────────────────────────────────────────
#  PARCELAS
# ─────────────────────────────────────────────────────────────

def parse_installment(raw: Any) -> tuple[int | None, int | None]:
    """
    Detecta parcela em string bruta (ANTES de norm_text).
    norm_text remove a barra: '3/12' → '3 12' → regex falha.
    Sempre chamar com o valor original.

    Suporta:
      3/12        → (3, 12)
      01/03       → (1, 3)
      2 de 5      → (2, 5)
      parcela 2 de 5  → (2, 5)
      (3/12)      → (3, 12)
    """
    raw_str = str(raw or "").strip()
    if not raw_str or raw_str in {"-", "--", ""}:
        return None, None

    # Normalizar preservando barras
    text = norm_text_keep_slash(raw_str)

    patterns = [
        r"parcela\s+(\d{1,2})\s+de\s+(\d{1,2})",  # parcela 2 de 5
        r"\((\d{1,2})\s*/\s*(\d{1,2})\)",           # (3/12)
        r"\b(\d{1,2})\s+de\s+(\d{1,2})\b",          # 2 de 5
        r"\b(\d{1,2})\s*/\s*(\d{1,2})\b",           # 3/12, 01/03
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            if 1 <= current <= total <= 99:
                return current, total
    return None, None


def is_likely_installment(current: int | None, total: int | None, account_type: str = "") -> bool:
    """
    Desambigua N/M entre parcela e data (ex: LOCALIZA 01/03 — é parcela 1/3 ou dia 1 de março?).
    Regra: se total > 12 → definitivamente parcela.
    Se total in [2..12] e é cartão de crédito → trata como parcela.
    """
    if current is None or total is None:
        return False
    if total > 12:
        return True
    if account_type == "credit_card":
        common = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 18, 24, 36, 48}
        return total in common
    return False


def clean_description_of_installment(desc: str, current: int | None, total: int | None) -> str:
    """Remove sufixo de parcela da descrição, deixando o nome do estabelecimento limpo."""
    if not (current and total):
        return desc
    # Remove: " 3/12", " 01/03", " (3/12)", " PARC 3/12" do final
    clean = re.sub(r"\s*\(?\d{1,2}\s*/\s*\d{1,2}\)?\s*$", "", desc).strip()
    clean = re.sub(
        r"\s+parcela\s+\d{1,2}\s+de\s+\d{1,2}\s*$", "", clean, flags=re.IGNORECASE
    ).strip()
    clean = re.sub(
        r"\s+parc\.?\s+\d{1,2}\s*/\s*\d{1,2}\s*$", "", clean, flags=re.IGNORECASE
    ).strip()
    return clean or desc


def installment_label(current: int | None, total: int | None) -> str | None:
    if current and total:
        return f"Parcela {current} de {total}"
    return None


# ─────────────────────────────────────────────────────────────
#  FLAGS DE TRANSAÇÃO
# ─────────────────────────────────────────────────────────────

# Transferências entre contas próprias — não são despesas reais, apenas movimentação
CARD_PAYMENT_MARKERS = (
    "debito aut fatura cartao",
    "debito automatico fatura",
    "debito aut fatura cartao visa",
    "pagamento de fatura",
    "pagamento fatura cartao",
    "pagamento cartao credito bce",
    "pag fatura",
    "deb autom de fatura",
)

INTER_ACCOUNT_MARKERS = (
    "debito aut fatura cartao",
    "debito automatico fatura",
    "debito aut fatura cartao visa",
    "pagamento de fatura",
    "pagamento fatura cartao",
    "pagamento cartao credito bce",
    "pag fatura",
    "deb autom de fatura",
    "transferencia entre contas",
    "ted conta propria",
    "pix propria titularidade",
    "aplicacao automatica",
    "resgate automatico",
    "resgate cdb",
    "resgate rdb",
    "aplicacao cdb",
    "aplicacao rdb",
    "aplicacao lci",
    "resgate lci",
)

INVESTMENT_MARKERS = (
    "aplicacao cdb",
    "aplicacao rdb",
    "resgate cdb",
    "resgate rdb",
)

YIELD_MARKERS = (
    "remuneracao aplicacao automatica",
)

DEBIT_CARD_MARKERS = (
    "debito visa electron brasil",
)

# Marcadores de receita para cartão de crédito
# Mais específicos que antes — "credito" isolado foi removido
CREDIT_CARD_INCOME_MARKERS = (
    # Estornos / devoluções
    "estorno",
    "reembolso",
    "devolucao",
    "devolução",
    "cancelamento",
    "chargeback",
    "extorno",
    # Créditos específicos (não o tipo de pagamento "pix crédito")
    "ajuste a credito",
    "ajuste credito",
    "credito em conta",
    "credito na fatura",
    "credito fatura",
    # Cashback e programas de benefício
    "cashback",
    "bonus",
    "bônus",
    "pontos resgatados",
    "rewards",
    "milhas",
    "beneficio",
    "benefício",
    "xp pontos",
    "nubank rewards",
    "livelo",
    "smiles",
    "esfera",
    "programa de pontos",
    "desconto do mes",
)

# Marcadores de IOF / taxas
TAX_MARKERS = (
    "iof imposto operacoes",
    "iof adicional",
    "iof de",
    "iof de rotativo",
    "juros de rotativo",
    "tarifa mensalidade",
    "debito contribuicao previdencia",
)


def detect_transaction_flags(description: str) -> list[str]:
    """
    Retorna lista de flags para a transação:
    - INTER_ACCOUNT: pagamento de fatura, transferência entre contas próprias
    - CASHBACK: cashback, bônus, rewards
    - TAX: IOF, tarifas
    - INSTALLMENT: parcela (adicionada pelo pipeline de parcelas)
    """
    flags: list[str] = []
    dn = norm_text(description)

    if any(m in dn for m in INTER_ACCOUNT_MARKERS):
        flags.append("INTER_ACCOUNT")

    if any(m in dn for m in INVESTMENT_MARKERS):
        flags.append("investimento")

    if any(m in dn for m in CARD_PAYMENT_MARKERS):
        flags.append("fatura")

    if any(m in dn for m in YIELD_MARKERS):
        flags.append("rendimento")

    if any(m in dn for m in DEBIT_CARD_MARKERS):
        flags.append("cartao_debito")

    if any(m in dn for m in ("cashback", "bonus", "rewards", "pontos resgatados", "livelo", "smiles", "esfera", "desconto do mes")):
        flags.append("CASHBACK")

    if any(m in dn for m in TAX_MARKERS):
        flags.append("tax")

    return flags


def classify_credit_card_type(description: str, raw_type: str, file_format: str) -> str:
    """
    Para cartão de crédito, determina se o lançamento é income ou expense.

    Regra: quase tudo é expense.
    Exceções (income):
      - Estornos, devoluções, cancelamentos
      - Cashback, bônus, rewards
      - Créditos específicos na fatura

    raw_type: tipo inferido pelo parser base pelo sinal do valor
    file_format: 'csv' | 'pdf' | 'xlsx'
    """
    dn = norm_text(description)

    # Para CSV: quando parser marca como expense (valor negativo), o sinal foi invertido
    # corretamente pelo banco — é de fato income (storno, devolução)
    inferred_from_sign = (file_format == "csv" and raw_type == "expense")

    is_income = inferred_from_sign or any(m in dn for m in CREDIT_CARD_INCOME_MARKERS)
    return "income" if is_income else "expense"


# ─────────────────────────────────────────────────────────────
#  PARSE DE DATAS E VALORES
# ─────────────────────────────────────────────────────────────

def parse_date(raw: Any) -> str:
    """Converte qualquer representação de data para ISO YYYY-MM-DD."""
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
        except Exception:
            return ""
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse_money(raw: Any) -> float | None:
    """
    Converte string de valor monetário para float.
    Suporta: R$ 1.800,00 / 1.800,00- / (1.800,00) / -1800.00
    Retorna valor com sinal original preservado.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    # Parenteses indicam negativo: (1.800,00)
    negative_parens = text.startswith("(") and text.endswith(")")
    if negative_parens:
        text = text[1:-1]
    # Trailing minus
    trailing_minus = text.endswith("-")
    if trailing_minus:
        text = text[:-1]
    # Normalizar separadores
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        val = float(text)
    except ValueError:
        return None
    if negative_parens or trailing_minus:
        val = -abs(val)
    return val


# ─────────────────────────────────────────────────────────────
#  DETECÇÃO DE FORMATO
# ─────────────────────────────────────────────────────────────

def detect_format(path: Path, account_name: str) -> FormatDetection:
    """
    Detecta banco, tipo de documento e encoding do arquivo.
    Usa: extensão, nome do arquivo, account_name fornecido.
    Lê até 4KB do conteúdo para confirmação.
    """
    ext = path.suffix.lower().replace(".", "")
    acc_upper = (account_name or "").upper()
    name_norm = norm_text(path.name)
    confidence = 0.5

    # Banco pelo nome da conta (obrigatório na importação)
    if "SANTANDER" in acc_upper:
        bank = "SANTANDER"
        confidence += 0.2
    elif "XP" in acc_upper:
        bank = "XP"
        confidence += 0.2
    elif "NUBANK" in acc_upper:
        bank = "NUBANK"
        confidence += 0.2
    else:
        bank = "GENERIC"

    # Tipo pelo nome da conta
    if "CARTAO" in acc_upper:
        doc_type = "FATURA_CARTAO"
        confidence += 0.1
    else:
        doc_type = "EXTRATO_CORRENTE"
        confidence += 0.1

    # Reforço pelo nome do arquivo
    if any(k in name_norm for k in ("comprovante", "comprovante de fatura")):
        doc_type = "COMPROVANTE"
    elif any(k in name_norm for k in ("fatura", "cartao")):
        doc_type = "FATURA_CARTAO"
        if doc_type != "FATURA_CARTAO":
            confidence -= 0.05
    elif "extrato" in name_norm:
        doc_type = "EXTRATO_CORRENTE"

    # Encoding detection para CSV
    encoding = "utf-8-sig"
    if ext == "csv":
        encoding = _detect_csv_encoding(path)

    return FormatDetection(
        bank=bank,
        doc_type=doc_type,
        file_format=ext,
        encoding=encoding,
        confidence=min(0.99, confidence),
    )


def _detect_csv_encoding(path: Path) -> str:
    """Tenta múltiplos encodings e retorna o que funciona."""
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]
    for enc in encodings:
        try:
            sample = path.read_bytes()[:4096].decode(enc)
            # Heurística: presença de caracteres acentuados típicos do PT-BR
            if any(c in sample for c in "ãçêáéíóúâêôõü"):
                return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


# ─────────────────────────────────────────────────────────────
#  PARSERS
# ─────────────────────────────────────────────────────────────

def _row_display(row: list[Any]) -> str:
    return " | ".join(str(c).strip() for c in row if c is not None and str(c).strip())


def _looks_like_transaction_row(row: list[Any]) -> bool:
    values = [str(c).strip() for c in row if c is not None and str(c).strip()]
    if not values:
        return False
    has_date = any(parse_date(v) for v in values)
    has_amount = any(parse_money(v) is not None for v in values)
    has_text = any(
        re.search(r"[^\W\d_]{3,}", v, re.UNICODE)
        and parse_date(v) == ""
        and parse_money(v) is None
        for v in values
    )
    return has_date and has_amount and has_text


def _tabular_rejected_candidates(path: Path, file_format: str, encoding: str, parsed: list[RawTx]) -> list[str]:
    parsed_lines = {tx.source_line for tx in parsed if tx.source_line}
    rows: list[list[Any]] = []
    if file_format == "csv":
        with path.open("r", encoding=encoding, newline="", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            delim = ";" if sample.count(";") >= sample.count(",") else ","
            rows = [list(r) for r in csv.reader(f, delimiter=delim)]
    elif file_format == "xlsx" and openpyxl is not None:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif file_format == "xls" and xlrd is not None:
        book = xlrd.open_workbook(str(path))
        sh = book.sheet_by_index(0)
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    else:
        return []

    rejected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        line = _row_display(row)
        if not line or line in parsed_lines or line in seen:
            continue
        if _looks_like_transaction_row(row):
            rejected.append(line[:220])
            seen.add(line)
    return rejected


def parse_csv(path: Path, encoding: str = "utf-8-sig") -> list[RawTx]:
    """
    Parser genérico de CSV.
    Detecta delimitador, mapeia headers flexíveis.
    Lê coluna Parcela se existir.
    """
    out: list[RawTx] = []
    try:
        with path.open("r", encoding=encoding, newline="", errors="replace") as f:
            sample = f.read(4096)
            f.seek(0)
            delim = ";" if sample.count(";") >= sample.count(",") else ","
            reader = csv.DictReader(f, delimiter=delim)
            headers = {
                norm_text(h).replace(" ", "_"): h
                for h in (reader.fieldnames or [])
            }

            h_date = (
                headers.get("data")
                or headers.get("data_de_compra")
                or headers.get("date")
                or headers.get("dia")
            )
            h_desc = (
                headers.get("descricao")
                or headers.get("historico")
                or headers.get("estabelecimento")
                or headers.get("nome_no_extrato")
                or headers.get("lancamento")
                or headers.get("title")
            )
            h_val = headers.get("valor") or headers.get("value") or headers.get("amount")
            h_type = headers.get("tipo")
            h_cred = headers.get("credito")
            h_deb = headers.get("debito")
            h_inst = (
                headers.get("parcela")
                or headers.get("parcelas")
                or headers.get("parcelamento")
                or headers.get("parc")
            )

            for row in reader:
                source_line = _row_display([row.get(h, "") for h in (reader.fieldnames or [])])
                d = parse_date(row.get(h_date, "")) if h_date else ""
                desc = (row.get(h_desc, "") or "").strip() if h_desc else ""
                if not (d and desc):
                    continue

                # Coluna Parcela bruta — NÃO normalizar
                inst_raw = (row.get(h_inst, "") or "").strip() if h_inst else ""

                # Colunas separadas crédito/débito
                if h_cred or h_deb:
                    cred = parse_money(row.get(h_cred, "")) if h_cred else None
                    deb = parse_money(row.get(h_deb, "")) if h_deb else None
                    if cred not in (None, 0.0):
                        out.append(RawTx(d, desc, abs(cred), "income", inst_raw, source_line))
                    if deb not in (None, 0.0):
                        out.append(RawTx(d, desc, abs(deb), "expense", inst_raw, source_line))
                    continue

                v = parse_money(row.get(h_val, "")) if h_val else None
                if v is None:
                    continue

                rt = (row.get(h_type, "") or "").strip().lower() if h_type else ""
                if rt in {"entrada", "income", "credito", "crédito"}:
                    t = "income"
                elif rt in {"saida", "saída", "expense", "debito", "débito"}:
                    t = "expense"
                else:
                    t = "income" if v >= 0 else "expense"

                out.append(RawTx(d, desc, abs(v), t, inst_raw, source_line))
    except Exception as exc:
        raise RuntimeError(f"Erro ao ler CSV: {exc}") from exc
    return out


def parse_xlsx(path: Path) -> list[RawTx]:
    if openpyxl is None:
        raise RuntimeError("openpyxl não encontrado. Instale: pip install openpyxl")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return _parse_tabular_rows(rows)


def parse_xls(path: Path) -> list[RawTx]:
    if xlrd is None:
        raise RuntimeError("xlrd não encontrado. Instale: pip install xlrd")
    book = xlrd.open_workbook(str(path))
    sh = book.sheet_by_index(0)
    rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    return _parse_tabular_rows(rows)


def _parse_tabular_rows(rows: list[list[Any]]) -> list[RawTx]:
    """Parser compartilhado para XLSX e XLS."""
    if not rows:
        return []
    keys = {
        "data", "dia", "date", "descricao", "historico", "estabelecimento",
        "lancamento", "valor", "credito", "debito", "tipo",
        "parcela", "parcelas", "parcelamento", "parc",
    }
    # Encontrar linha de header
    best, score = 0, -1
    for i, row in enumerate(rows[:20]):
        rk = {norm_text(str(c)).replace(" ", "_") for c in row if str(c).strip()}
        s = len(rk.intersection(keys))
        if s > score:
            best, score = i, s
    header = [norm_text(str(c)).replace(" ", "_") for c in rows[best]]
    idx = {h: i for i, h in enumerate(header) if h}

    def get(row: list[Any], *keys_: str) -> Any:
        for k in keys_:
            i = idx.get(k)
            if i is not None and i < len(row):
                v = row[i]
                if v is not None and str(v).strip():
                    return v
        return None

    out: list[RawTx] = []
    for row in rows[best + 1:]:
        source_line = _row_display(row)
        d = parse_date(get(row, "data", "dia", "date"))
        desc = str(get(row, "descricao", "historico", "estabelecimento", "lancamento") or "").strip()
        if not (d and desc):
            continue

        # Parcela bruta — NÃO normalizar
        inst_raw = str(get(row, "parcela", "parcelas", "parcelamento", "parc") or "").strip()

        # Crédito/débito separados
        cred = parse_money(get(row, "credito"))
        deb = parse_money(get(row, "debito"))
        if cred not in (None, 0.0):
            out.append(RawTx(d, desc, abs(cred), "income", inst_raw, source_line))
        if deb not in (None, 0.0):
            out.append(RawTx(d, desc, abs(deb), "expense", inst_raw, source_line))
        if cred not in (None, 0.0) or deb not in (None, 0.0):
            continue

        v = parse_money(get(row, "valor", "value"))
        if v is None:
            continue
        rt = str(get(row, "tipo") or "").strip().lower()
        if rt in {"entrada", "income", "credito", "crédito"}:
            t = "income"
        elif rt in {"saida", "saída", "expense", "debito", "débito"}:
            t = "expense"
        else:
            t = "income" if v >= 0 else "expense"
        out.append(RawTx(d, desc, abs(v), t, inst_raw, source_line))
    return out


def parse_pdf_statement(path: Path, account_name: str = "") -> tuple[list[RawTx], BalanceCheck]:
    """
    Parser de extrato corrente (Santander e genérico).
    Formato: DD/MM  DESCRIÇÃO  VALOR
    Extrai saldo anterior e saldo final para validação de integridade.
    Remove lançamentos espelhados (comprovantes no final do PDF Santander).
    """
    if PdfReader is None:
        raise RuntimeError("pypdf não encontrado. Instale: pip install pypdf")

    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for pg in reader.pages:
        try:
            page_texts.append(pg.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(page_texts)
    if not text.strip():
        return [], BalanceCheck(None, None, None, None, False, "PDF sem texto extraível")

    if "SANTANDER" in account_name.upper():
        santander = _parse_santander_movement_statement(text, path.name)
        if santander is not None:
            return santander
    if "NUBANK" in account_name.upper():
        nubank = _parse_nubank_statement(text, path.name)
        if nubank is not None:
            return nubank

    # Inferir ano do documento
    ref_year = _infer_statement_year(text, path.name)
    ref_month = _infer_statement_month(text, path.name)

    # Extrair saldos para validação
    saldo_anterior = _extract_saldo(text, "anterior")
    saldo_final = _extract_saldo(text, "final")

    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    out: list[RawTx] = []
    rejected: list[str] = []
    amount_re = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")

    # Linhas de seção/cabeçalho que não são transações
    SKIP_PATTERNS = (
        "comprovantes de lancamento",
        "comprovante de lancamento",
        "saldo anterior",
        "saldo final",
        "saldo em",
        "data descricao",
        "data historico",
        "total do periodo",
        "subtotal",
        "extrato de conta",
    )

    pending_date = ""
    pending_parts: list[str] = []

    def commit():
        nonlocal pending_date, pending_parts
        if not pending_date or not pending_parts:
            return
        joined = " ".join(pending_parts).strip()
        vals = amount_re.findall(joined)
        if not vals:
            pending_date = ""
            pending_parts = []
            return
        # Pegar o segundo-a-último valor (o último pode ser o saldo)
        mov_txt = vals[-2] if len(vals) >= 2 else vals[-1]
        pos = joined.find(mov_txt)
        if pos <= 0:
            pending_date = ""
            pending_parts = []
            return
        desc = joined[:pos].strip(" -")
        v = parse_money(mov_txt)
        if not desc or v is None:
            pending_date = ""
            pending_parts = []
            return
        day_month = pending_date
        try:
            day = int(day_month[:2])
            month = int(day_month[3:5])
        except ValueError:
            pending_date = ""
            pending_parts = []
            return
        year = ref_year if month <= ref_month else ref_year - 1
        d = parse_date(f"{day:02d}/{month:02d}/{year}")
        if d:
            t = "income" if v > 0 else "expense"
            out.append(RawTx(d, desc, abs(v), t, source_line=joined))
        pending_date = ""
        pending_parts = []

    for ln in lines:
        ln_norm = norm_text(ln)

        # Parar no bloco de comprovantes (Santander)
        if "comprovantes de lancamento" in ln_norm or "comprovante de lancamento" in ln_norm:
            commit()
            break

        # Pular linhas de seção
        if any(skip in ln_norm for skip in SKIP_PATTERNS):
            commit()
            continue

        m = re.match(r"^(\d{2}/\d{2})\s+(.*)$", ln)
        if m:
            commit()
            pending_date = m.group(1)
            rest = m.group(2).strip()
            pending_parts = [rest] if rest else []
            commit()
            continue

        if pending_date:
            pending_parts.append(ln)
            commit()
            if len(pending_parts) > 4:
                pending_date = ""
                pending_parts = []

    commit()

    # Fallback: se parser principal não extraiu nada, tenta padrão DD/MM/YYYY
    if not out:
        for ln in lines:
            m = re.search(r"(\d{2}/\d{2}/\d{4}).*?(-?\d{1,3}(?:\.\d{3})*,\d{2}-?)", ln)
            if not m:
                if re.search(r"\d{2}/\d{2}", ln):
                    rejected.append(ln[:150])
                continue
            d = parse_date(m.group(1))
            v = parse_money(m.group(2))
            if not d or v is None:
                continue
            desc = ln.replace(m.group(1), "").replace(m.group(2), "").strip(" -")
            if not desc:
                desc = "LANCAMENTO PDF"
            out.append(RawTx(d, desc, abs(v), "income" if v > 0 else "expense", source_line=ln))

    # Remover espelhos (Santander)
    if "SANTANDER" in account_name.upper():
        out = _remove_statement_mirrors(out)

    # Validação de saldo
    balance = _validate_balance(out, saldo_anterior, saldo_final)

    return out, balance


def parse_pdf_credit_card(path: Path, account_name: str = "") -> list[RawTx]:
    """
    Parser de fatura de cartão de crédito.
    Suporta: Santander (parser dedicado) e genérico.
    Detecta parcelas NO string bruto ANTES de limpar a descrição.
    """
    if PdfReader is None:
        raise RuntimeError("pypdf não encontrado. Instale: pip install pypdf")

    reader = PdfReader(str(path))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    if not text.strip():
        return []

    # Inferir mês/ano de referência pelo nome do arquivo: "Cartao - 03-26"
    ref_year = _infer_statement_year(text, path.name)
    ref_month = _infer_statement_month(text, path.name)
    due = re.search(r"vencimento\s+(\d{2})/(\d{2})/(20\d{2})", re.sub(r"\s+", " ", strip_accents(text).lower()))
    if due:
        ref_month = int(due.group(2))
        ref_year = int(due.group(3))

    amount_re = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")
    out: list[RawTx] = []

    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    # Linhas de seção que não são transações
    SECTION_KEYWORDS = (
        "detalhamento da fatura",
        "pagamento e demais creditos",
        "parcelamentos",
        "despesas",
        "valor total",
        "compra data descricao",
        "santander",
        "vencimento",
        "limite",
        "fatura",
        "total a pagar",
    )

    for ln in lines:
        ln_norm = norm_text(ln)
        if any(k in ln_norm for k in SECTION_KEYWORDS):
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
        v = parse_money(val_txt)
        if v is None:
            continue

        pos = rest.rfind(val_txt)
        raw_desc_with_installment = rest[:pos].strip(" -")
        if not raw_desc_with_installment:
            continue

        # Detectar parcela NO STRING BRUTO antes de qualquer limpeza
        inst_raw = raw_desc_with_installment

        day = int(ddmm[:2])
        month = int(ddmm[3:5])
        year = ref_year if month <= ref_month else ref_year - 1
        d = parse_date(f"{day:02d}/{month:02d}/{year}")
        if not d:
            continue

        t = "income" if v > 0 else "expense"
        out.append(RawTx(d, raw_desc_with_installment, abs(v), t, inst_raw, source_line=ln))

    return out


# ─────────────────────────────────────────────────────────────
#  ENRIQUECIMENTO
# ─────────────────────────────────────────────────────────────

def enrich_transaction(
    raw: RawTx,
    account_type: str,
    file_format: str,
) -> EnrichedTx:
    """
    Converte RawTx em EnrichedTx:
    - Detecta parcela (coluna ou sufixo da descrição)
    - Classifica income/expense para cartão
    - Limpa descrição (remove sufixo de parcela)
    - Detecta flags (INTER_ACCOUNT, CASHBACK, TAX)
    """
    # 1. Detectar parcela — usar string bruto (preserva barras)
    # Prioridade: coluna Parcela explícita > sufixo na descrição
    inst_current, inst_total = parse_installment(raw.installment_raw)

    # Se coluna não tinha parcela, tentar na descrição
    if not (inst_current and inst_total):
        inst_current, inst_total = parse_installment(raw.description_raw)

    # Verificar se é realmente parcela (desambiguar de datas)
    if not is_likely_installment(inst_current, inst_total, account_type):
        inst_current = None
        inst_total = None

    # 2. Limpar descrição — remover sufixo de parcela
    desc_clean = clean_description_of_installment(raw.description_raw, inst_current, inst_total)

    # 3. Classificar tipo para cartão de crédito
    if account_type == "credit_card":
        tx_type = classify_credit_card_type(raw.description_raw, raw.tx_type_raw, file_format)
    else:
        tx_type = raw.tx_type_raw

    # 4. Calcular valor com sinal. Cada linha representa exatamente a parcela
    # cobrada nesta fatura; nunca multiplicar pelo total de parcelas.
    raw_amount = raw.amount_raw
    amount_signed = round(
        raw_amount if tx_type == "income" else -raw_amount, 2
    )

    # 5. Detectar flags
    flags = detect_transaction_flags(raw.description_raw)
    if inst_current and inst_total:
        flags.append("INSTALLMENT")

    # 6. Label de parcela
    label = installment_label(inst_current, inst_total)

    return EnrichedTx(
        date=raw.date,
        description=desc_clean,
        description_norm=norm_text(desc_clean),
        amount_signed=amount_signed,
        tx_type=tx_type,
        installment_current=inst_current,
        installment_total=inst_total,
        installment_label=label,
        is_installment=bool(inst_current and inst_total),
        flags=flags,
        source_line=raw.source_line,
    )


# ─────────────────────────────────────────────────────────────
#  VALIDAÇÃO DE QUALIDADE
# ─────────────────────────────────────────────────────────────

def _validate_balance(
    txs: list[RawTx],
    saldo_anterior: float | None,
    saldo_final: float | None,
) -> BalanceCheck:
    if saldo_anterior is None or saldo_final is None:
        return BalanceCheck(None, None, None, None, True, "Saldo não extraído do PDF")

    total = sum(
        t.amount_raw if t.tx_type_raw == "income" else -t.amount_raw
        for t in txs
    )
    calculated = round(saldo_anterior + total, 2)
    diff = abs(calculated - saldo_final)
    ok = diff < 0.10  # tolerância de R$ 0,10

    msg = "OK" if ok else (
        f"Diferença de R$ {diff:.2f} entre saldo calculado ({calculated:.2f}) "
        f"e declarado ({saldo_final:.2f}). Verifique se há lançamentos perdidos."
    )
    return BalanceCheck(saldo_anterior, saldo_final, calculated, round(diff, 2), ok, msg)


def _extract_saldo(text: str, tipo: str) -> float | None:
    """Extrai saldo anterior ou final de texto de extrato."""
    patterns = {
        "anterior": [
            r"saldo\s+anterior\s+R?\$?\s*([\d.,]+)",
            r"saldo\s+em\s+\d{2}/\d{2}/\d{4}\s+R?\$?\s*([\d.,]+)",
            r"saldo\s+de\s+conta\s+corrente\s+em\s+\d{2}/\d{2}\s+([\d.,]+)",
            r"saldo\s+em\s+\d{2}/\d{2}\s+([\d.,]+)",
        ],
        "final": [
            r"saldo\s+final\s+R?\$?\s*([\d.,]+)",
            r"saldo\s+atual\s+R?\$?\s*([\d.,]+)",
            r"saldo\s+de\s+conta\s+corrente\s+em\s+\d{2}/\d{2}\s+([\d.,]+)",
            r"saldo\s+em\s+\d{2}/\d{2}\s+([\d.,]+)",
        ],
    }
    search_text = text
    if tipo == "final":
        search_text = "\n".join(reversed(text.splitlines()))
    for pat in patterns.get(tipo, []):
        m = re.search(pat, search_text, re.IGNORECASE)
        if m:
            v = parse_money(m.group(1))
            if v is not None:
                return v
    return None


def _statement_month_year_from_filename(filename: str) -> tuple[int, int] | None:
    """
    Extrai competencia de nomes como "Extrato - 10-25 - Santander.pdf".

    Arquivos arquivados podem ganhar prefixos com UUID (PREVIEW_..._13C9_...),
    entao nao podemos usar o primeiro par NN-NN encontrado.
    """
    clean = strip_accents(filename).lower()
    matches = re.findall(r"(?<!\d)(\d{1,2})\s*[-_/]\s*(\d{2})(?!\d)", clean)
    valid: list[tuple[int, int]] = []
    for month_raw, year_raw in matches:
        month = int(month_raw)
        year_suffix = int(year_raw)
        if 1 <= month <= 12 and 20 <= year_suffix <= 40:
            valid.append((month, 2000 + year_suffix))
    return valid[-1] if valid else None


def _infer_statement_year(text: str, filename: str) -> int:
    """
    Infere o ano do extrato.
    Estratégia: busca todos os anos YYYY no texto, usa o mais frequente.
    Fallback: ano atual.
    """
    from_name = _statement_month_year_from_filename(filename)
    if from_name:
        return from_name[1]
    title = re.search(
        r"(janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s*/\s*(20\d{2})",
        strip_accents(text).lower(),
    )
    if title:
        return int(title.group(2))
    years = re.findall(r"\b(20[0-9]{2})\b", text)
    if years:
        from collections import Counter
        return int(Counter(years).most_common(1)[0][0])
    return dt.datetime.now().year


def _infer_statement_month(text: str, filename: str = "") -> int:
    """Infere o mês de referência do extrato."""
    from_name = _statement_month_year_from_filename(filename)
    if from_name:
        return from_name[0]
    month_names = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "março": 3,
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
        r"(janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s*/\s*20\d{2}",
        strip_accents(text).lower(),
    )
    if title:
        return month_names[title.group(1)]
    # Mês mais frequente nas datas DD/MM encontradas
    months = re.findall(r"\d{2}/(\d{2})(?:/\d{4})?", text[:5000])
    if months:
        from collections import Counter
        return int(Counter(months).most_common(1)[0][0])
    return dt.datetime.now().month


PT_MONTH_ABBR = {
    "JAN": 1,
    "FEV": 2,
    "MAR": 3,
    "ABR": 4,
    "MAI": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SET": 9,
    "OUT": 10,
    "NOV": 11,
    "DEZ": 12,
}


def _nubank_summary_value(text: str, label: str) -> float | None:
    compact = re.sub(r"\s+", " ", strip_accents(text))
    m = re.search(
        label + r"\s*(?:R\$\s*)?([+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2})",
        compact,
        re.IGNORECASE,
    )
    if m:
        return parse_money(m.group(1))
    return None


def _nubank_summary_values_from_header(text: str) -> tuple[float | None, float | None, float | None]:
    header = text.split("Movimentações", 1)[0].split("Movimentacoes", 1)[0]
    values = re.findall(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2}", header)
    parsed = [parse_money(v) for v in values]
    parsed = [v for v in parsed if v is not None]
    if len(parsed) >= 6:
        # Nubank coloca um card-resumo duplicando o saldo final:
        # saldo_final, saldo_inicial, rendimento, entradas, saidas, saldo_final.
        return parsed[1], parsed[2], parsed[-1]
    return None, None, None


def _nubank_type_for_description(description: str) -> str:
    dn = norm_text(description)
    income_markers = (
        "transferencia recebida",
        "pix recebido",
        "deposito",
        "rendimento",
        "resgate",
        "recebida pelo pix",
    )
    expense_markers = (
        "compra no debito",
        "pagamento de fatura",
        "transferencia enviada",
        "pix enviado",
        "boleto pago",
        "pagamento",
    )
    if any(marker in dn for marker in income_markers):
        return "income"
    if any(marker in dn for marker in expense_markers):
        return "expense"
    return "expense"


def _parse_nubank_statement(text: str, filename: str) -> tuple[list[RawTx], BalanceCheck] | None:
    if "movimentacoes" not in norm_text(text):
        return None

    saldo_inicial = _nubank_summary_value(text, "Saldo inicial")
    saldo_final = _nubank_summary_value(text, "Saldo final do periodo") or _nubank_summary_value(text, "Saldo final")
    rendimento = _nubank_summary_value(text, "Rendimento liquido")
    if saldo_inicial is None or saldo_final is None or rendimento is None:
        header_saldo_inicial, header_rendimento, header_saldo_final = _nubank_summary_values_from_header(text)
        saldo_inicial = saldo_inicial if saldo_inicial is not None else header_saldo_inicial
        saldo_final = saldo_final if saldo_final is not None else header_saldo_final
        rendimento = rendimento if rendimento is not None else header_rendimento

    lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]

    out: list[RawTx] = []
    in_movements = False
    current_date = ""
    pending_desc: list[str] = []
    amount_re = re.compile(r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2})$")

    def add_tx(date: str, desc: str, amount_text: str, source_line: str) -> None:
        value = parse_money(amount_text)
        clean_desc = re.sub(r"\s+", " ", desc).strip(" -")
        if not date or not clean_desc or value is None:
            return
        if norm_text(clean_desc).startswith("total de "):
            return
        out.append(RawTx(date, clean_desc, abs(value), _nubank_type_for_description(clean_desc), source_line=source_line))

    for ln in lines:
        ln_norm = norm_text(ln)
        if "movimentacoes" in ln_norm:
            in_movements = True
            continue
        if not in_movements:
            continue
        if (
            "saldo liquido corresponde" in ln_norm
            or "nao nos responsabilizamos" in ln_norm
            or "asseguramos a autenticidade" in ln_norm
            or "tem alguma duvida" in ln_norm
            or "ouvidoria" in ln_norm
            or "extrato gerado" in ln_norm
            or "cnpj" in ln_norm
        ):
            break

        date_match = re.match(r"^(\d{2})\s+([A-Z]{3})\s+(20\d{2})\b", strip_accents(ln).upper())
        if date_match:
            day = int(date_match.group(1))
            month = PT_MONTH_ABBR.get(date_match.group(2)[:3])
            year = int(date_match.group(3))
            current_date = parse_date(f"{day:02d}/{month:02d}/{year}") if month else ""
            pending_desc = []
            continue

        if not current_date:
            continue
        if ln_norm.startswith("total de "):
            pending_desc = []
            continue

        if re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2}", ln):
            if pending_desc:
                desc = " ".join(pending_desc)
                add_tx(current_date, desc, ln, f"{desc} {ln}")
                pending_desc = []
            continue

        m = amount_re.search(ln)
        if m:
            amount_text = m.group(1)
            desc = ln[:m.start()].strip()
            if pending_desc:
                desc = " ".join(pending_desc + [desc])
            add_tx(current_date, desc, amount_text, ln)
            pending_desc = []
            continue

        pending_desc.append(ln)
        if len(pending_desc) > 6:
            pending_desc = pending_desc[-6:]

    if rendimento not in (None, 0.0):
        ref = _statement_month_year_from_filename(filename)
        if ref:
            month, year = ref
        else:
            month, year = _infer_statement_month(text, filename), _infer_statement_year(text, filename)
        out.append(RawTx(f"{year:04d}-{month:02d}-01", "Rendimento liquido", abs(float(rendimento)), "income", source_line="Rendimento liquido"))

    balance = _validate_balance(out, saldo_inicial, saldo_final)
    return out, balance


def _statement_date_from_ddmm(ddmm: str, ref_year: int, ref_month: int) -> str | None:
    try:
        day = int(ddmm[:2])
        month = int(ddmm[3:5])
    except ValueError:
        return None
    year = ref_year if month <= ref_month else ref_year - 1
    return parse_date(f"{day:02d}/{month:02d}/{year}")


def _santander_statement_type(description: str, amount_text: str) -> str:
    desc = norm_text(description)
    if desc.startswith("pix devolvido"):
        return "expense" if amount_text.strip().endswith("-") or amount_text.strip().startswith("-") else "income"
    if desc.startswith("pix recebido") or desc.startswith("remuneracao"):
        return "income"
    if desc.startswith("resgate cdb") or desc.startswith("resgate rdb"):
        return "income"
    if desc.startswith("aplicacao cdb") or desc.startswith("aplicacao rdb"):
        return "expense"
    positive = ("recebido", "devolvido", "remuneracao", "credito")
    if re.search(r"\b(enviado|pagamento|pgto|debito|tarifa|iof|contribuicao|juros|aplicacao)\b", desc):
        return "expense"
    if "visa electron" in desc or "cartao credito" in desc:
        return "expense"
    if any(word in desc for word in positive):
        return "income"
    return "expense" if amount_text.strip().endswith("-") or amount_text.strip().startswith("-") else "income"


def _clean_santander_statement_desc(description: str) -> str:
    desc = re.sub(r"\s+", " ", description or "").strip(" -")
    starter = re.search(r"\b(PIX|IOF|TARIFA|DEBITO|CREDITO|PAGAMENTO|PGTO|REMUNERACAO|JUROS|APLICACAO|RESGATE)\b", desc, re.IGNORECASE)
    if starter:
        desc = desc[starter.start():]
    # Remove numero de documento no fim da descricao, preservando datas internas
    # como "07/01 01:11 CARTAO VISA".
    desc = re.sub(r"\s+\d{5,12}$", "", desc).strip(" -")
    return desc


def _parse_santander_movement_statement(text: str, filename: str) -> tuple[list[RawTx], BalanceCheck] | None:
    """
    Extrai o bloco canonico de movimentacao do extrato Santander.

    Esse PDF tambem possui secoes de comprovantes e resumos, que sao
    incompletas. A fonte primaria e o bloco entre SALDO EM dd/mm inicial
    e SALDO EM dd/mm final.
    """
    raw_lines = [re.sub(r"\s+", " ", (ln or "").strip()) for ln in text.splitlines()]
    lines = [ln for ln in raw_lines if ln]
    saldo_re = r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?"
    start_re = re.compile(rf"^SALDO EM \d{{2}}/\d{{2}}\s+{saldo_re}$", re.IGNORECASE)
    end_re = re.compile(rf"^SALDO EM \d{{2}}/\d{{2}}\s+{saldo_re}$", re.IGNORECASE)

    start_idx = None
    for idx, line in enumerate(lines):
        if start_re.match(line):
            start_idx = idx
            break
    if start_idx is None:
        return None

    saldo_anterior = parse_money(lines[start_idx].split()[-1])
    block: list[str] = []
    saldo_final = None
    for line in lines[start_idx + 1:]:
        line_norm = norm_text(line)
        if end_re.match(line):
            saldo_final = parse_money(line.split()[-1])
            break
        if "data descricao" in line_norm or "pagina" in line_norm:
            continue
        if line_norm.startswith("extrato consolidado") or line_norm.startswith("conta corrente"):
            continue
        block.append(line)

    if not block:
        return None

    ref_year = _infer_statement_year(text, filename)
    ref_month = _infer_statement_month(text, filename)
    amount_re = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")
    date_re = re.compile(r"^(\d{2}/\d{2})\s+(.*)$")
    tx_starters = (
        "PIX ",
        "IOF ",
        "TARIFA ",
        "DEBITO ",
        "CREDITO ",
        "PAGAMENTO ",
        "PGTO ",
        "REMUNERACAO ",
        "JUROS ",
        "APLICACAO ",
        "RESGATE ",
    )

    out: list[RawTx] = []
    current_date = ""
    group_parts: list[str] = []

    def flush_group() -> None:
        nonlocal group_parts
        if not current_date or not group_parts:
            group_parts = []
            return
        tx_date = _statement_date_from_ddmm(current_date, ref_year, ref_month)
        if not tx_date:
            group_parts = []
            return
        joined = " ".join(group_parts).strip()
        matches = list(amount_re.finditer(joined))
        if not matches:
            group_parts = []
            return

        cursor = 0
        skip_next = False
        for idx, match in enumerate(matches):
            if skip_next:
                skip_next = False
                cursor = match.end()
                continue
            next_match = matches[idx + 1] if idx + 1 < len(matches) else None
            if next_match and not joined[match.end():next_match.start()].strip():
                skip_next = True

            segment = joined[cursor:match.start()]
            cursor = match.end()
            if next_match and skip_next:
                cursor = next_match.end()
            desc = _clean_santander_statement_desc(segment)
            if not desc:
                continue
            if not any(norm_text(desc).startswith(norm_text(s)) for s in tx_starters):
                # Fragmentos como cabecalhos ou sobra de saldo nao sao lancamentos.
                continue
            amount = parse_money(match.group(0))
            if amount is None:
                continue
            tx_type = _santander_statement_type(desc, match.group(0))
            out.append(RawTx(tx_date, desc, abs(amount), tx_type, source_line=segment.strip()))
        group_parts = []

    for line in block:
        m = date_re.match(line)
        starts_transaction = False
        if m:
            rest_norm = norm_text(m.group(2))
            starts_transaction = any(rest_norm.startswith(norm_text(s)) for s in tx_starters)
        if m and starts_transaction:
            flush_group()
            current_date = m.group(1)
            rest = m.group(2).strip()
            group_parts = [rest] if rest else []
        else:
            if current_date:
                group_parts.append(line)
    flush_group()

    if not out:
        return None
    return out, _validate_balance(out, saldo_anterior, saldo_final)


def _remove_statement_mirrors(txs: list[RawTx]) -> list[RawTx]:
    """
    Remove lançamentos espelhados nos comprovantes do extrato Santander.
    Lógica: se há um income "INTERNET BANKING PIX" com mesmo valor que
    um expense "PIX ENVIADO" na mesma data (±1 dia), remove o income.
    """
    incomes = [(i, t) for i, t in enumerate(txs) if t.tx_type_raw == "income"]
    expenses = [(i, t) for i, t in enumerate(txs) if t.tx_type_raw == "expense"]

    remove_idx: set[int] = set()
    for i_idx, inc in incomes:
        inc_desc = norm_text(inc.description_raw)
        inc_amt = round(abs(inc.amount_raw), 2)
        try:
            inc_date = dt.date.fromisoformat(inc.date)
        except ValueError:
            continue

        is_proof = (
            inc_desc.startswith("internet banking pix")
            or inc_desc.startswith("cartao de credito")
        )
        if not is_proof:
            continue

        for _, exp in expenses:
            if round(abs(exp.amount_raw), 2) != inc_amt:
                continue
            try:
                exp_date = dt.date.fromisoformat(exp.date)
            except ValueError:
                continue
            if abs((inc_date - exp_date).days) > 1:
                continue
            exp_desc = norm_text(exp.description_raw)
            pix_pair = "internet banking pix" in inc_desc and "pix enviado" in exp_desc
            card_pair = "cartao de credito" in inc_desc and "fatura cartao" in exp_desc
            if pix_pair or card_pair:
                remove_idx.add(i_idx)
                break

    return [t for idx, t in enumerate(txs) if idx not in remove_idx]


# ─────────────────────────────────────────────────────────────
#  PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────

def _is_explicit_empty_nubank_text(text: str) -> bool:
    normalized = norm_text(text)
    return (
        "nenhuma movimentacao" in normalized
        and "saldo inicial" in normalized
        and "saldo final" in normalized
    )


def is_explicit_empty_statement(
    path: Path,
    fmt: FormatDetection,
    account_type: str,
) -> bool:
    """Aceita vazio apenas quando o proprio documento fornece evidencia forte."""
    if account_type == "credit_card":
        return False

    if fmt.file_format == "pdf" and fmt.bank == "NUBANK" and PdfReader is not None:
        try:
            text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        except Exception:
            return False
        return _is_explicit_empty_nubank_text(text)

    if fmt.file_format == "csv" and fmt.bank == "XP":
        try:
            text = path.read_text(encoding=fmt.encoding or "utf-8-sig", errors="replace")
            non_empty_lines = [line for line in text.splitlines() if line.strip()]
            if len(non_empty_lines) != 1:
                return False
            dialect = csv.Sniffer().sniff(non_empty_lines[0], delimiters=",;\t|")
            headers = {norm_text(cell) for cell in next(csv.reader(non_empty_lines, dialect))}
        except Exception:
            return False
        return {"data", "descricao", "valor", "saldo"}.issubset(headers)

    return False


def run_import_pipeline(path: Path, account_name: str, account_type: str) -> ImportResult:
    """
    Pipeline completo de importação.
    Entrada: arquivo + nome da conta + tipo (checking | credit_card)
    Saída: ImportResult com tudo para o endpoint consumir.

    Fluxo:
      1. detect_format
      2. parse (raw) de acordo com o formato
      3. enrich (parcelas, flags, tipo)
      4. validar qualidade
      5. montar ImportResult
    """
    fmt = detect_format(path, account_name)
    warnings: list[str] = []
    rejected: list[str] = []
    balance = BalanceCheck(None, None, None, None, True)

    # Parse — escolher parser pelo formato
    raw_txs: list[RawTx] = []

    if fmt.file_format == "csv":
        raw_txs = parse_csv(path, fmt.encoding)

    elif fmt.file_format == "xlsx":
        raw_txs = parse_xlsx(path)

    elif fmt.file_format == "xls":
        raw_txs = parse_xls(path)

    elif fmt.file_format == "pdf":
        if account_type == "credit_card":
            raw_txs = parse_pdf_credit_card(path, account_name)
            # Comprovante Santander — rejeitar se poucos lançamentos
            if fmt.bank == "SANTANDER" and len(raw_txs) < 12:
                raise ValueError(
                    "PDF de cartão Santander com menos de 12 lançamentos. "
                    "Use o CSV da fatura para melhor qualidade."
                )
        else:
            raw_txs, balance = parse_pdf_statement(path, account_name)
    else:
        raise ValueError(f"Formato não suportado: {fmt.file_format}")

    if fmt.file_format in {"csv", "xlsx", "xls"}:
        rejected.extend(_tabular_rejected_candidates(path, fmt.file_format, fmt.encoding, raw_txs))

    empty_statement_confirmed = False
    if not raw_txs:
        empty_statement_confirmed = is_explicit_empty_statement(path, fmt, account_type)

    if not raw_txs and not empty_statement_confirmed:
        raise ValueError(
            "Nenhum lançamento identificado. "
            "Verifique se o arquivo é um extrato ou fatura válido com texto extraível."
        )
    if empty_statement_confirmed:
        warnings.append(
            "Extrato válido sem movimentações. O documento será registrado no cofre sem criar lançamentos."
        )

    # Enriquecimento
    enriched: list[EnrichedTx] = []
    discarded: list[str] = []
    for raw in raw_txs:
        try:
            tx = enrich_transaction(raw, account_type, fmt.file_format)
            enriched.append(tx)
        except Exception:
            rejected.append(raw.source_line[:150])
            continue

    # Filtrar linhas de seção contaminadas (ex: "TOTAL DO PERÍODO R$ 5.000,00")
    enriched = _filter_contamination(enriched)

    # Validação de volume
    if account_type != "credit_card" and len(enriched) < 5 and not empty_statement_confirmed:
        warnings.append(
            f"Arquivo com apenas {len(enriched)} lançamentos. "
            "Extratos normalmente têm mais de 15 lançamentos. Verifique se importou o arquivo correto."
        )

    if balance and not balance.ok:
        warnings.append(f"⚠️ Integridade do saldo: {balance.message}")

    if rejected:
        warnings.append(
            f"{len(rejected)} linha(s) candidata(s) a lancamento nao foram reconhecidas. "
            "Revise a lista de linhas rejeitadas antes de confirmar a importacao."
        )

    # Estatísticas
    total_installments = sum(1 for t in enriched if t.is_installment)
    total_inter_account = sum(1 for t in enriched if "INTER_ACCOUNT" in t.flags)
    total_cashback = sum(1 for t in enriched if "CASHBACK" in t.flags)

    if total_inter_account > 0:
        warnings.append(
            f"{total_inter_account} lançamento(s) com tag de movimentação interna "
            "(fatura, aplicação/resgate ou transferência). Eles serão importados normalmente."
        )

    return ImportResult(
        txs=enriched,
        format_detection=fmt,
        balance_check=balance,
        warnings=warnings,
        rejected_lines=rejected,
        discarded_lines=discarded,
        total_parsed=len(enriched),
        total_installments=total_installments,
        total_inter_account=total_inter_account,
        total_cashback=total_cashback,
        empty_statement_confirmed=empty_statement_confirmed,
    )


def _filter_contamination(txs: list[EnrichedTx]) -> list[EnrichedTx]:
    """Remove linhas que claramente não são transações (seções, subtotais)."""
    CONTAMINATION = (
        "total do periodo",
        "subtotal",
        "total fatura",
        "total a pagar",
        "saldo devedor",
    )
    return [
        t for t in txs
        if not any(c in t.description_norm for c in CONTAMINATION)
    ]
