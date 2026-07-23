from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from parsers.engine import norm_text, run_import_pipeline  # noqa: E402


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def infer_context(relative: Path) -> tuple[str, str, str]:
    parts_upper = [part.upper() for part in relative.parts]
    filename_upper = relative.name.upper()
    if "DOCUMENTOS_EMPRESA" in parts_upper:
        return "", "", "supporting_document"
    account_type = "credit_card" if "CARTOES" in parts_upper else "checking"
    bank = next(
        (name for name in ("SANTANDER", "NUBANK", "XP") if name in filename_upper),
        "GENERIC",
    )
    account = f"{'CARTAO' if account_type == 'credit_card' else 'CONTA'} {bank}"
    return account, account_type, "financial"


def infer_year_month(relative: Path) -> str:
    parts = relative.parts
    if not parts or not re.fullmatch(r"\d{4}", parts[0]):
        return ""
    if len(parts) < 2:
        return ""
    match = re.match(r"^(\d{2})-", parts[1])
    return f"{parts[0]}/{match.group(1)}" if match else ""


def audit_signature(row: dict) -> tuple[str, float, str, str]:
    type_map = {"Despesa": "expense", "Receita": "income"}
    return (
        row["date"],
        round(float(row["amount"]), 2),
        norm_text(row["description"]),
        type_map.get(row["type"], row["type"].lower()),
    )


def parser_signature(tx) -> tuple[str, float, str, str]:
    return (
        tx.date,
        round(float(tx.amount_signed), 2),
        norm_text(tx.description),
        tx.tx_type,
    )


def identity_signature(signature: tuple[str, float, str, str]) -> tuple[str, float, str]:
    return signature[:3]


def date_amount_signature(signature: tuple[str, float, str, str]) -> tuple[str, float]:
    return signature[:2]


def pdf_facts(path: Path) -> dict:
    reader = PdfReader(str(path))
    text_chars = 0
    pages_with_text = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        text_chars += len(text)
        pages_with_text += bool(text.strip())
    return {
        "pdf_pages": len(reader.pages),
        "pdf_pages_with_text": pages_with_text,
        "pdf_text_chars": text_chars,
        "pdf_encrypted": bool(reader.is_encrypted),
    }


def scan(root: Path, audit_path: Path) -> dict:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit_documents = audit["documents"]
    audit_transactions_by_hash: dict[str, list[dict]] = {}
    for row in audit["transactions"]:
        audit_transactions_by_hash.setdefault(row["source_hash"], []).append(row)

    results = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        account, account_type, role = infer_context(relative)
        item = {
            "relative_path": str(relative),
            "filename": path.name,
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
            "sha1": "",
            "year_month": infer_year_month(relative),
            "account_inferred": account,
            "role": role,
            "file_valid": False,
            "parse_status": "not_applicable" if role != "financial" else "pending",
            "parse_error": "",
            "parsed_transactions": None,
            "parsed_min_date": "",
            "parsed_max_date": "",
            "parsed_income": None,
            "parsed_expense": None,
            "warnings": [],
            "audit_hash_match": False,
            "audit_transactions": 0,
            "audit_stored_transactions": 0,
            "transaction_matches": None,
            "identity_matches": None,
            "date_amount_matches": None,
            "missing_in_audit": None,
            "extra_in_audit": None,
        }
        try:
            item["sha1"] = sha1_file(path)
            item["file_valid"] = path.stat().st_size > 0
            if path.suffix.lower() == ".pdf":
                item.update(pdf_facts(path))
            elif path.suffix.lower() == ".csv":
                with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as source:
                    item["tabular_rows"] = sum(1 for _ in csv.reader(source))
            elif path.suffix.lower() == ".xls":
                item["tabular_rows"] = None
        except Exception as exc:
            item["parse_status"] = "invalid_file"
            item["parse_error"] = f"{type(exc).__name__}: {exc}"

        document = audit_documents.get(item["sha1"])
        if document:
            item["audit_hash_match"] = True
            item["audit_transactions"] = int(document["transaction_count"])
            item["audit_stored_transactions"] = int(
                document["stored_transaction_count"]
            )

        if role == "financial" and item["parse_status"] != "invalid_file":
            try:
                parsed = run_import_pipeline(path, account, account_type)
                item["parse_status"] = "parsed"
                item["parsed_transactions"] = len(parsed.txs)
                dates = [tx.date for tx in parsed.txs]
                item["parsed_min_date"] = min(dates) if dates else ""
                item["parsed_max_date"] = max(dates) if dates else ""
                item["parsed_income"] = round(
                    sum(tx.amount_signed for tx in parsed.txs if tx.tx_type == "income"),
                    2,
                )
                item["parsed_expense"] = round(
                    sum(tx.amount_signed for tx in parsed.txs if tx.tx_type == "expense"),
                    2,
                )
                item["warnings"] = parsed.warnings
                if document:
                    parsed_counter = Counter(parser_signature(tx) for tx in parsed.txs)
                    audit_counter = Counter(
                        audit_signature(row)
                        for row in audit_transactions_by_hash[item["sha1"]]
                    )
                    matches = sum((parsed_counter & audit_counter).values())
                    parsed_identity = Counter(
                        identity_signature(value)
                        for value in parsed_counter.elements()
                    )
                    audit_identity = Counter(
                        identity_signature(value) for value in audit_counter.elements()
                    )
                    parsed_date_amount = Counter(
                        date_amount_signature(value)
                        for value in parsed_counter.elements()
                    )
                    audit_date_amount = Counter(
                        date_amount_signature(value)
                        for value in audit_counter.elements()
                    )
                    item["transaction_matches"] = matches
                    item["identity_matches"] = sum(
                        (parsed_identity & audit_identity).values()
                    )
                    item["date_amount_matches"] = sum(
                        (parsed_date_amount & audit_date_amount).values()
                    )
                    item["missing_in_audit"] = sum(
                        (parsed_counter - audit_counter).values()
                    )
                    item["extra_in_audit"] = sum(
                        (audit_counter - parsed_counter).values()
                    )
            except Exception as exc:
                item["parse_status"] = "parse_error"
                item["parse_error"] = f"{type(exc).__name__}: {exc}"
        results.append(item)

    matched_hashes = {row["sha1"] for row in results if row["audit_hash_match"]}
    audit_hashes = set(audit_documents)
    financial = [row for row in results if row["role"] == "financial"]
    exact = [
        row
        for row in financial
        if row["audit_hash_match"]
        and row["parse_status"] == "parsed"
        and row["missing_in_audit"] == 0
        and row["extra_in_audit"] == 0
    ]
    return {
        "root": str(root),
        "audit_source": str(audit_path),
        "summary": {
            "total_files": len(results),
            "financial_files": len(financial),
            "supporting_documents": sum(
                row["role"] == "supporting_document" for row in results
            ),
            "valid_files": sum(row["file_valid"] for row in results),
            "invalid_files": sum(not row["file_valid"] for row in results),
            "parsed_financial_files": sum(
                row["parse_status"] == "parsed" for row in financial
            ),
            "parse_errors": sum(
                row["parse_status"] == "parse_error" for row in financial
            ),
            "local_files_matching_audit_hash": sum(
                row["audit_hash_match"] for row in results
            ),
            "distinct_local_hashes_matching_audit": len(matched_hashes),
            "audit_distinct_hashes": len(audit_hashes),
            "audit_hashes_without_local_file": len(audit_hashes - matched_hashes),
            "financial_files_exact_transaction_match": len(exact),
        },
        "audit_hashes_without_local_file": sorted(audit_hashes - matched_hashes),
        "files": results,
    }


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "Uso: scan_financeiro_organizado.py <raiz> <auditoria.json> <saida.json>"
        )
    root = Path(sys.argv[1]).resolve()
    audit = Path(sys.argv[2]).resolve()
    output = Path(sys.argv[3]).resolve()
    report = scan(root, audit)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
