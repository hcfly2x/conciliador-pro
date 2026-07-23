from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from repairs.santander_cards import RepairConflict, repair_santander_cards


class SantanderCardRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE accounts(
              id TEXT PRIMARY KEY,name TEXT,type TEXT,is_active INTEGER
            );
            CREATE TABLE imported_files(
              id TEXT PRIMARY KEY,file_hash TEXT,account_id TEXT,account_name TEXT,
              year TEXT,month TEXT,total_parsed INTEGER,total_inserted INTEGER
            );
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY,tx_key TEXT NOT NULL UNIQUE,date TEXT NOT NULL,
              competence_month TEXT NOT NULL,description TEXT NOT NULL,
              description_norm TEXT NOT NULL,amount REAL NOT NULL,type TEXT NOT NULL,
              status TEXT NOT NULL,account_id TEXT NOT NULL,
              installment_current INTEGER,installment_total INTEGER,
              flags TEXT NOT NULL DEFAULT '',imported_file_id TEXT NOT NULL,
              locked INTEGER NOT NULL DEFAULT 0,classified_by TEXT NOT NULL DEFAULT '',
              classified_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE audit_log(
              id TEXT PRIMARY KEY,user_id TEXT,username TEXT,action TEXT,
              entity TEXT,entity_id TEXT,field TEXT,old_value TEXT,new_value TEXT,
              detail TEXT,created_at TEXT
            );
            INSERT INTO accounts VALUES
              ('card','CARTAO SANTANDER','credit_card',1);
            INSERT INTO imported_files VALUES
              ('batch','hash-1','card','CARTAO SANTANDER','2025','01',1,1);
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,
              amount,type,status,account_id,flags,imported_file_id
            ) VALUES (
              'tx-old','old-key','2025-01-05','2025/01','ESTORNO LOJA',
              'estorno loja',-10.0,'expense','pending','card','','batch'
            );
            """
        )
        self.application = SimpleNamespace(store_shadow_metadata=lambda *args: None)
        self.user = {"id": "admin", "username": "admin"}
        common = {
            "document": "Cartao - 01-25 - Santander.pdf",
            "source_hash": "hash-1",
            "imported_file_id": "batch",
            "installment_current": None,
            "installment_total": None,
        }
        self.manifest = {
            "manifest_id": "test-santander-repair-v1",
            "account_name": "CARTAO SANTANDER",
            "repair_count": 2,
            "repairs": [
                {
                    **common,
                    "repair_id": "update-1",
                    "action": "ATUALIZAR",
                    "reason": "Crédito com sinal invertido",
                    "transaction_id": "tx-old",
                    "date": "2025-01-05",
                    "description_current": "ESTORNO LOJA",
                    "description_correct": "ESTORNO LOJA",
                    "description_norm_correct": "estorno loja",
                    "amount_current": -10.0,
                    "amount_correct": 10.0,
                    "type_current": "Despesa",
                    "type_correct": "income",
                    "flags_correct": "",
                },
                {
                    **common,
                    "repair_id": "insert-1",
                    "action": "ADICIONAR",
                    "reason": "Pagamento de fatura ausente",
                    "transaction_id": "",
                    "date": "2025-01-10",
                    "description_current": "",
                    "description_correct": "PAGAMENTO DE FATURA",
                    "description_norm_correct": "pagamento de fatura",
                    "amount_current": 0.0,
                    "amount_correct": 100.0,
                    "type_current": "",
                    "type_correct": "income",
                    "flags_correct": "INTER_ACCOUNT,fatura",
                },
            ],
        }

    def execute(self, *, dry_run: bool):
        with patch(
            "repairs.santander_cards.load_manifest",
            return_value=self.manifest,
        ):
            return repair_santander_cards(
                self.conn,
                self.application,
                self.user,
                dry_run=dry_run,
            )

    def test_repair_is_transactional_and_idempotent(self) -> None:
        preview = self.execute(dry_run=True)
        self.assertEqual((preview["updates"], preview["inserts"]), (1, 1))

        result = self.execute(dry_run=False)
        self.assertEqual((result["updated"], result["inserted"]), (1, 1))
        rows = self.conn.execute(
            """
            SELECT date,description,amount,type,flags,competence_month
            FROM transactions ORDER BY date
            """
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("2025-01-05", "ESTORNO LOJA", 10.0, "income", "", "2025/01"),
                (
                    "2025-01-10",
                    "PAGAMENTO DE FATURA",
                    100.0,
                    "income",
                    "INTER_ACCOUNT,fatura",
                    "2025/01",
                ),
            ],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT total_parsed,total_inserted FROM imported_files WHERE id='batch'"
            ).fetchone(),
            (2, 2),
        )

        second = self.execute(dry_run=False)
        self.assertEqual((second["updated"], second["inserted"]), (0, 0))
        self.assertEqual(second["already_applied"], 2)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(1) FROM transactions").fetchone()[0],
            2,
        )

    def test_changed_transaction_blocks_the_whole_repair(self) -> None:
        self.conn.execute("UPDATE transactions SET amount=-11 WHERE id='tx-old'")

        with self.assertRaises(RepairConflict):
            self.execute(dry_run=False)

        self.assertEqual(
            self.conn.execute("SELECT COUNT(1) FROM transactions").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute("SELECT amount FROM transactions WHERE id='tx-old'").fetchone()[0],
            -11.0,
        )


if __name__ == "__main__":
    unittest.main()
