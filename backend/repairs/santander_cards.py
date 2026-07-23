from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from auth import record_audit


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "repair_manifests"
    / "santander_cards_20260723.json"
)
CONFIRMATION = "CORRIGIR_FATURAS_SANTANDER"
TYPE_ALIASES = {
    "Despesa": "expense",
    "Receita": "income",
    "expense": "expense",
    "income": "income",
}


class RepairConflict(RuntimeError):
    def __init__(self, conflicts: list[dict[str, Any]]):
        super().__init__("O estado atual diverge da auditoria usada no reparo")
        self.conflicts = conflicts


def load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if len(manifest.get("repairs") or []) != int(manifest.get("repair_count") or 0):
        raise RuntimeError("Manifesto Santander inconsistente")
    return manifest


def _same_money(left: Any, right: Any) -> bool:
    return abs(float(left or 0) - float(right or 0)) < 0.005


def _desired_tx_id(manifest_id: str, repair_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"conciliador:{manifest_id}:{repair_id}",
        )
    )


def _desired_tx_key(
    account_id: str,
    manifest_id: str,
    repair: dict[str, Any],
) -> str:
    return (
        f"{account_id}|{repair['date']}|{float(repair['amount_correct']):.2f}|"
        f"{repair['description_norm_correct']}|{repair['type_correct']}|"
        f"{int(repair.get('installment_current') or 0)}|"
        f"{int(repair.get('installment_total') or 0)}|"
        f"repair:{manifest_id}:{repair['repair_id']}"
    )


def _source_competence(conn, imported_file_id: str) -> str:
    row = conn.execute(
        """
        SELECT competence_month,COUNT(1) AS occurrences
        FROM transactions
        WHERE imported_file_id=? AND competence_month<>''
        GROUP BY competence_month
        ORDER BY occurrences DESC,competence_month
        LIMIT 1
        """,
        (imported_file_id,),
    ).fetchone()
    if row:
        return str(row[0])
    imported = conn.execute(
        "SELECT year,month FROM imported_files WHERE id=?",
        (imported_file_id,),
    ).fetchone()
    if imported and imported[0] and imported[1]:
        return f"{imported[0]}/{imported[1]}"
    raise RuntimeError(f"Competência não encontrada para o lote {imported_file_id}")


def _current_update_row(conn, transaction_id: str):
    return conn.execute(
        """
        SELECT id,date,description,description_norm,amount,type,account_id,
               imported_file_id,tx_key,competence_month
        FROM transactions
        WHERE id=?
        """,
        (transaction_id,),
    ).fetchone()


def _is_desired_update(row, repair: dict[str, Any], account_id: str) -> bool:
    return bool(
        row
        and row[1] == repair["date"]
        and row[2] == repair["description_correct"]
        and row[3] == repair["description_norm_correct"]
        and _same_money(row[4], repair["amount_correct"])
        and row[5] == repair["type_correct"]
        and row[6] == account_id
        and row[7] == repair["imported_file_id"]
    )


def _matches_update_precondition(
    row,
    repair: dict[str, Any],
    account_id: str,
) -> bool:
    return bool(
        row
        and row[1] == repair["date"]
        and row[2] == repair["description_current"]
        and _same_money(row[4], repair["amount_current"])
        and row[5] == TYPE_ALIASES.get(repair.get("type_current"))
        and row[6] == account_id
        and row[7] == repair["imported_file_id"]
    )


def _find_existing_insert(conn, repair: dict[str, Any], account_id: str):
    return conn.execute(
        """
        SELECT id,date,description,description_norm,amount,type,account_id,
               imported_file_id,tx_key,competence_month
        FROM transactions
        WHERE imported_file_id=? AND account_id=? AND date=?
          AND ABS(amount-?)<0.005 AND description_norm=? AND type=?
        ORDER BY id
        LIMIT 1
        """,
        (
            repair["imported_file_id"],
            account_id,
            repair["date"],
            repair["amount_correct"],
            repair["description_norm_correct"],
            repair["type_correct"],
        ),
    ).fetchone()


def _insert_row_is_desired(row, repair: dict[str, Any], account_id: str) -> bool:
    return bool(
        row
        and row[1] == repair["date"]
        and row[2] == repair["description_correct"]
        and row[3] == repair["description_norm_correct"]
        and _same_money(row[4], repair["amount_correct"])
        and row[5] == repair["type_correct"]
        and row[6] == account_id
        and row[7] == repair["imported_file_id"]
    )


def _build_plan(conn, manifest: dict[str, Any]) -> dict[str, Any]:
    account = conn.execute(
        "SELECT id,name,type FROM accounts WHERE name=? AND is_active=1",
        (manifest["account_name"],),
    ).fetchone()
    if not account:
        raise RuntimeError("Conta CARTAO SANTANDER não encontrada")
    account_id = str(account[0])

    source_cache: dict[str, Any] = {}
    competence_cache: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    states = Counter()

    for repair in manifest["repairs"]:
        imported_file_id = repair["imported_file_id"]
        source = source_cache.get(imported_file_id)
        if source is None:
            source = conn.execute(
                """
                SELECT id,file_hash,account_id,account_name
                FROM imported_files
                WHERE id=?
                """,
                (imported_file_id,),
            ).fetchone()
            source_cache[imported_file_id] = source
        if not source or (
            str(source[1]).lower() != str(repair["source_hash"]).lower()
            or source[2] != account_id
            or source[3] != manifest["account_name"]
        ):
            conflicts.append(
                {
                    "repair_id": repair["repair_id"],
                    "action": repair["action"],
                    "transaction_id": repair.get("transaction_id") or "",
                    "code": "SOURCE_CHANGED",
                    "document": repair["document"],
                }
            )
            continue

        if repair["action"] == "ATUALIZAR":
            row = _current_update_row(conn, repair["transaction_id"])
            if _is_desired_update(row, repair, account_id):
                states["already_applied"] += 1
                operations.append({"state": "already_applied", "repair": repair, "row": row})
            elif _matches_update_precondition(row, repair, account_id):
                states["update"] += 1
                operations.append({"state": "update", "repair": repair, "row": row})
            else:
                conflicts.append(
                    {
                        "repair_id": repair["repair_id"],
                        "action": repair["action"],
                        "transaction_id": repair["transaction_id"],
                        "code": "TRANSACTION_CHANGED",
                        "document": repair["document"],
                    }
                )
            continue

        if repair["action"] != "ADICIONAR":
            conflicts.append(
                {
                    "repair_id": repair["repair_id"],
                    "action": repair["action"],
                    "transaction_id": "",
                    "code": "UNKNOWN_ACTION",
                    "document": repair["document"],
                }
            )
            continue

        desired_id = _desired_tx_id(manifest["manifest_id"], repair["repair_id"])
        existing_by_id = _current_update_row(conn, desired_id)
        if _insert_row_is_desired(existing_by_id, repair, account_id):
            states["already_applied"] += 1
            operations.append(
                {
                    "state": "already_applied",
                    "repair": repair,
                    "row": existing_by_id,
                }
            )
            continue
        if existing_by_id:
            conflicts.append(
                {
                    "repair_id": repair["repair_id"],
                    "action": repair["action"],
                    "transaction_id": desired_id,
                    "code": "REPAIR_TRANSACTION_CHANGED",
                    "document": repair["document"],
                }
            )
            continue
        unexpected = _find_existing_insert(conn, repair, account_id)
        if unexpected:
            conflicts.append(
                {
                    "repair_id": repair["repair_id"],
                    "action": repair["action"],
                    "transaction_id": unexpected[0],
                    "code": "UNEXPECTED_EQUIVALENT_TRANSACTION",
                    "document": repair["document"],
                }
            )
            continue
        if imported_file_id not in competence_cache:
            competence_cache[imported_file_id] = _source_competence(
                conn, imported_file_id
            )
        states["insert"] += 1
        operations.append(
            {
                "state": "insert",
                "repair": repair,
                "competence_month": competence_cache[imported_file_id],
            }
        )

    if conflicts:
        raise RepairConflict(conflicts)
    return {
        "account_id": account_id,
        "operations": operations,
        "states": states,
        "affected_imports": sorted(source_cache),
    }


def _record_item_audit(
    conn,
    user: dict[str, Any] | None,
    manifest: dict[str, Any],
    repair: dict[str, Any],
    transaction_id: str,
    action: str,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any],
) -> None:
    record_audit(
        user,
        "santander_card_repair",
        "transaction",
        transaction_id,
        "financial_fields",
        json.dumps(old_value or {}, ensure_ascii=False, sort_keys=True),
        json.dumps(new_value, ensure_ascii=False, sort_keys=True),
        (
            f"manifest={manifest['manifest_id']};repair_id={repair['repair_id']};"
            f"action={action};reason={repair['reason']};document={repair['document']}"
        ),
        conn=conn,
    )


def repair_santander_cards(
    conn,
    application,
    user: dict[str, Any] | None,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    manifest = load_manifest()
    plan = _build_plan(conn, manifest)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "manifest_id": manifest["manifest_id"],
            "repair_count": manifest["repair_count"],
            "updates": plan["states"]["update"],
            "inserts": plan["states"]["insert"],
            "already_applied": plan["states"]["already_applied"],
            "conflicts": 0,
        }

    updated = 0
    inserted = 0
    account_id = plan["account_id"]
    for operation in plan["operations"]:
        if operation["state"] == "already_applied":
            continue
        repair = operation["repair"]
        desired = {
            "date": repair["date"],
            "description": repair["description_correct"],
            "description_norm": repair["description_norm_correct"],
            "amount": float(repair["amount_correct"]),
            "type": repair["type_correct"],
            "flags": repair["flags_correct"],
            "installment_current": repair.get("installment_current"),
            "installment_total": repair.get("installment_total"),
            "imported_file_id": repair["imported_file_id"],
        }
        tx_key = _desired_tx_key(
            account_id,
            manifest["manifest_id"],
            repair,
        )

        if operation["state"] == "update":
            old_row = operation["row"]
            cursor = conn.execute(
                """
                UPDATE transactions
                SET tx_key=?,description=?,description_norm=?,amount=?,type=?,
                    flags=?,installment_current=?,installment_total=?
                WHERE id=? AND date=? AND description=? AND ABS(amount-?)<0.005
                  AND type=? AND account_id=? AND imported_file_id=?
                """,
                (
                    tx_key,
                    desired["description"],
                    desired["description_norm"],
                    desired["amount"],
                    desired["type"],
                    desired["flags"],
                    desired["installment_current"],
                    desired["installment_total"],
                    repair["transaction_id"],
                    repair["date"],
                    repair["description_current"],
                    repair["amount_current"],
                    TYPE_ALIASES.get(repair.get("type_current")),
                    account_id,
                    repair["imported_file_id"],
                ),
            )
            if cursor.rowcount != 1:
                raise RepairConflict(
                    [
                        {
                            "repair_id": repair["repair_id"],
                            "action": repair["action"],
                            "transaction_id": repair["transaction_id"],
                            "code": "CONCURRENT_UPDATE",
                            "document": repair["document"],
                        }
                    ]
                )
            transaction_id = repair["transaction_id"]
            application.store_shadow_metadata(
                conn,
                "transactions",
                transaction_id,
                desired["description"],
                "credit_card",
                desired["installment_current"],
                desired["installment_total"],
            )
            _record_item_audit(
                conn,
                user,
                manifest,
                repair,
                transaction_id,
                "ATUALIZAR",
                {
                    "date": old_row[1],
                    "description": old_row[2],
                    "description_norm": old_row[3],
                    "amount": float(old_row[4]),
                    "type": old_row[5],
                    "imported_file_id": old_row[7],
                },
                desired,
            )
            updated += 1
            continue

        transaction_id = _desired_tx_id(
            manifest["manifest_id"],
            repair["repair_id"],
        )
        conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,
              amount,type,status,account_id,installment_current,installment_total,
              flags,imported_file_id,locked,classified_by,classified_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                transaction_id,
                tx_key,
                desired["date"],
                operation["competence_month"],
                desired["description"],
                desired["description_norm"],
                desired["amount"],
                desired["type"],
                "pending",
                account_id,
                desired["installment_current"],
                desired["installment_total"],
                desired["flags"],
                desired["imported_file_id"],
                0,
                "",
                "",
            ),
        )
        application.store_shadow_metadata(
            conn,
            "transactions",
            transaction_id,
            desired["description"],
            "credit_card",
            desired["installment_current"],
            desired["installment_total"],
        )
        _record_item_audit(
            conn,
            user,
            manifest,
            repair,
            transaction_id,
            "ADICIONAR",
            None,
            desired,
        )
        inserted += 1

    for imported_file_id in plan["affected_imports"]:
        conn.execute(
            """
            UPDATE imported_files
            SET total_parsed=(SELECT COUNT(1) FROM transactions WHERE imported_file_id=?),
                total_inserted=(SELECT COUNT(1) FROM transactions WHERE imported_file_id=?)
            WHERE id=?
            """,
            (imported_file_id, imported_file_id, imported_file_id),
        )

    record_audit(
        user,
        "santander_card_repair_complete",
        "repair_manifest",
        manifest["manifest_id"],
        "repair_count",
        "",
        manifest["repair_count"],
        (
            f"updated={updated};inserted={inserted};"
            f"already_applied={plan['states']['already_applied']}"
        ),
        conn=conn,
    )
    return {
        "ok": True,
        "dry_run": False,
        "manifest_id": manifest["manifest_id"],
        "repair_count": manifest["repair_count"],
        "updated": updated,
        "inserted": inserted,
        "already_applied": plan["states"]["already_applied"],
        "conflicts": 0,
    }
