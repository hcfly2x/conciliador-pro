from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import app

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = {".csv", ".xls", ".xlsx", ".pdf"}


def expected_account_from_path(path: Path) -> str:
    normalized = app.norm_text(str(path))
    if "santander" in normalized:
        bank = "SANTANDER"
    elif "nubank" in normalized:
        bank = "NUBANK"
    elif "xp" in normalized:
        bank = "XP"
    else:
        return ""
    kind = (
        "CARTAO"
        if any(token in normalized for token in ("cartao", "cartoes", "card"))
        else "CONTA"
    )
    return f"{kind} {bank}"


def audit_file(path: Path) -> dict[str, object]:
    detection = app.detect_document_identity(path)
    account_name = str(detection.get("suggested_account_name") or "")
    account_type = str(detection.get("account_type") or "")
    expected = expected_account_from_path(path)
    row: dict[str, object] = {
        "file": str(path),
        "expected_account": expected,
        "detected_account": account_name,
        "detection_confidence": detection.get("confidence", 0),
        "account_ok": bool(expected and expected == account_name),
        "transactions": 0,
        "competence": "",
        "warnings": [],
        "error": "",
    }
    if not account_name or account_type not in {"checking", "credit_card"}:
        row["error"] = "Conta ou tipo nao detectado"
        return row
    try:
        result = app.run_import_pipeline(path, account_name, account_type)
        competence = app.detect_competence(path, result.txs, account_type)
        warnings = list(result.warnings)
        if account_type == "checking" and len(result.txs) < 15:
            warnings.append(f"Extrato abaixo do minimo esperado: {len(result.txs)}")
        row.update({
            "transactions": len(result.txs),
            "competence": competence.get("month", ""),
            "competence_strategy": competence.get("strategy", ""),
            "warnings": warnings,
            "error": "",
        })
    except Exception as exc:
        logger.exception("Falha ao auditar amostra de importacao %s", path)
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita parsers sem importar dados no banco.")
    parser.add_argument("root", type=Path, help="Pasta com extratos e faturas")
    parser.add_argument("--json", action="store_true", help="Exibe resultado completo em JSON")
    args = parser.parse_args()

    files = [
        path for path in sorted(args.root.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
        and expected_account_from_path(path)
    ]
    rows = [audit_file(path) for path in files]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            status = "OK" if row["account_ok"] and not row["error"] and not row["warnings"] else "REVISAR"
            print(
                f"{status:7} | {row['detected_account'] or '-':18} | "
                f"{int(row['transactions']):4d} itens | {row['competence'] or '-':7} | {Path(str(row['file'])).name}"
            )
            if row["error"]:
                print(f"          ERRO: {row['error']}")
            for warning in row["warnings"]:
                print(f"          AVISO: {warning}")

    errors = sum(1 for row in rows if row["error"] or not row["account_ok"])
    warnings = sum(1 for row in rows if row["warnings"])
    print(f"\nArquivos: {len(rows)} | erros: {errors} | com avisos: {warnings}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
