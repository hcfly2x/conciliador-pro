from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from parsers.engine import norm_text, run_import_pipeline


SUPPORTED = {".pdf", ".csv", ".xlsx", ".xls"}
csv.field_size_limit(100 * 1024 * 1024)


def read_csv(bundle: zipfile.ZipFile, entry: str) -> list[dict[str, str]]:
    with bundle.open(entry) as raw:
        stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(stream))


def load_snapshot(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        imported = read_csv(bundle, "tables/imported_files.csv")
        transactions = read_csv(bundle, "tables/transactions.csv")
        stored = read_csv(bundle, "tables/stored_documents.csv")
    for row in stored:
        if not row.get("content_sha1") and row.get("content_b64"):
            row["content_sha1"] = hashlib.sha1(
                base64.b64decode(row["content_b64"])
            ).hexdigest()
    return {
        "manifest": manifest,
        "imported_files": imported,
        "transactions": transactions,
        "stored_documents": stored,
    }


def sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_zero_transaction_statement(path: Path) -> bool:
    if path.suffix.lower() != ".pdf":
        return False
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception:
        return False
    normalized = norm_text(text)
    return "nao ha lancamentos para o periodo" in normalized


def account_for_path(path: Path) -> tuple[str, str]:
    upper = str(path).upper()
    bank = next((name for name in ("SANTANDER", "NUBANK", "XP", "SMARTEK") if name in upper), "GENERICA")
    if "CARTOES" in upper or "CARTAO" in upper:
        return f"CARTAO {bank}", "credit_card"
    return f"CONTA {bank}", "checking"


def is_financial_file(path: Path) -> bool:
    return "DOCUMENTOS_EMPRESA" not in (part.upper() for part in path.parts)


def parser_key(row: Any) -> tuple[Any, ...]:
    return (
        row.date,
        norm_text(row.description),
        round(float(row.amount_signed), 2),
        row.tx_type,
        int(row.installment_current or 0),
        int(row.installment_total or 0),
    )


def database_key(row: dict[str, str]) -> tuple[Any, ...]:
    return (
        row["date"],
        norm_text(row["description"]),
        round(float(row["amount"]), 2),
        row["type"],
        int(row.get("installment_current") or 0),
        int(row.get("installment_total") or 0),
    )


def parser_financial_key(row: Any) -> tuple[Any, ...]:
    return (
        row.date,
        round(float(row.amount_signed), 2),
        row.tx_type,
        int(row.installment_current or 0),
        int(row.installment_total or 0),
    )


def database_financial_key(row: dict[str, str]) -> tuple[Any, ...]:
    return (
        row["date"],
        round(float(row["amount"]), 2),
        row["type"],
        int(row.get("installment_current") or 0),
        int(row.get("installment_total") or 0),
    )


def audit(snapshot_path: Path, organized_root: Path) -> dict[str, Any]:
    snapshot = load_snapshot(snapshot_path)
    imported = snapshot["imported_files"]
    transactions = snapshot["transactions"]
    stored = snapshot["stored_documents"]
    local_files = sorted(
        path for path in organized_root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )
    local_rows: list[dict[str, Any]] = []
    local_by_hash: dict[str, list[Path]] = {}
    for path in local_files:
        digest = sha1(path)
        local_by_hash.setdefault(digest, []).append(path)
        account_name, account_type = account_for_path(path)
        row: dict[str, Any] = {
            "path": str(path),
            "sha1": digest,
            "account_name": account_name,
            "account_type": account_type,
            "declared_incomplete": "INCOMPLETO" in path.name.upper(),
        }
        if not is_financial_file(path):
            row.update({"parse_status": "not_applicable", "reason": "documento societario, nao financeiro"})
            local_rows.append(row)
            continue
        try:
            parsed = run_import_pipeline(path, account_name, account_type)
            row.update(
                {
                    "parse_status": "ok",
                    "transactions": len(parsed.txs),
                    "net": round(sum(item.amount_signed for item in parsed.txs), 2),
                    "warnings": list(parsed.warnings),
                    "balance_ok": parsed.balance_check.ok,
                    "balance_difference": parsed.balance_check.diferenca,
                }
            )
        except Exception as exc:
            if is_zero_transaction_statement(path):
                row.update({"parse_status": "valid_zero", "transactions": 0, "net": 0.0})
            else:
                row.update({"parse_status": "error", "error": f"{type(exc).__name__}: {exc}"})
        local_rows.append(row)

    by_import: dict[str, list[dict[str, str]]] = {}
    for row in transactions:
        by_import.setdefault(row.get("imported_file_id") or "", []).append(row)

    batch_rows: list[dict[str, Any]] = []
    matched_hashes: set[str] = set()
    for imported_file in imported:
        if not imported_file.get("source_kind"):
            continue
        digest = imported_file.get("file_hash") or ""
        paths = local_by_hash.get(digest, [])
        batch: dict[str, Any] = {
            "imported_file_id": imported_file["id"],
            "filename": imported_file["filename"],
            "account_name": imported_file["account_name"],
            "competence": f"{imported_file['year']}/{imported_file['month']}",
            "file_hash": digest,
            "local_paths": [str(path) for path in paths],
            "database_count": len(by_import.get(imported_file["id"], [])),
        }
        if not paths:
            batch["status"] = "document_missing_locally"
            batch_rows.append(batch)
            continue
        matched_hashes.add(digest)
        path = paths[0]
        account_type = "credit_card" if imported_file["account_name"].startswith("CARTAO") else "checking"
        try:
            parsed = run_import_pipeline(path, imported_file["account_name"], account_type)
            database_counter = Counter(map(database_key, by_import.get(imported_file["id"], [])))
            parser_counter = Counter(map(parser_key, parsed.txs))
            database_financial = Counter(map(database_financial_key, by_import.get(imported_file["id"], [])))
            parser_financial = Counter(map(parser_financial_key, parsed.txs))
            exact = database_counter & parser_counter
            missing = parser_counter - database_counter
            extra = database_counter - parser_counter
            batch.update(
                {
                    "parser_count": len(parsed.txs),
                    "parser_net": round(sum(item.amount_signed for item in parsed.txs), 2),
                    "database_net": round(sum(float(item["amount"]) for item in by_import.get(imported_file["id"], [])), 2),
                    "exact_count": sum(exact.values()),
                    "missing_count": sum(missing.values()),
                    "extra_count": sum(extra.values()),
                    "missing_samples": [list(key) + [count] for key, count in list(missing.items())[:12]],
                    "extra_samples": [list(key) + [count] for key, count in list(extra.items())[:12]],
                    "warnings": list(parsed.warnings),
                    "balance_ok": parsed.balance_check.ok,
                    "balance_difference": parsed.balance_check.diferenca,
                }
            )
            if not missing and not extra:
                batch["status"] = "exact"
            elif database_financial == parser_financial:
                batch["status"] = "structural_only"
            else:
                batch["status"] = "financial_divergence"
        except Exception as exc:
            batch.update({"status": "parse_error", "error": f"{type(exc).__name__}: {exc}"})
        batch_rows.append(batch)

    document_hashes = Counter(row.get("content_sha1") or "" for row in stored)
    signature_batches: dict[tuple[Any, ...], set[str]] = {}
    for row in transactions:
        signature = (row.get("account_id") or "",) + database_key(row)
        signature_batches.setdefault(signature, set()).add(row.get("imported_file_id") or "")
    return {
        "snapshot": snapshot["manifest"],
        "summary": {
            "local_files": len(local_rows),
            "local_financial_files": sum(row["parse_status"] != "not_applicable" for row in local_rows),
            "local_not_applicable": sum(row["parse_status"] == "not_applicable" for row in local_rows),
            "local_parse_errors": sum(row["parse_status"] == "error" for row in local_rows),
            "production_files": len(batch_rows),
            "production_transactions": len(transactions),
            "production_documents": len(stored),
            "exact_batches": sum(row.get("status") == "exact" for row in batch_rows),
            "structural_only_batches": sum(row.get("status") == "structural_only" for row in batch_rows),
            "financial_divergent_batches": sum(row.get("status") == "financial_divergence" for row in batch_rows),
            "missing_local_documents": sum(row.get("status") == "document_missing_locally" for row in batch_rows),
            "unimported_local_files": sum(
                row["parse_status"] != "not_applicable" and row["sha1"] not in matched_hashes
                for row in local_rows
            ),
            "duplicate_document_hashes": sum(count > 1 for digest, count in document_hashes.items() if digest),
            "cross_batch_duplicate_signatures": sum(
                len(batch_ids) > 1 for batch_ids in signature_batches.values()
            ),
        },
        "batches": batch_rows,
        "local_files": local_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--organized-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.snapshot, args.organized_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
