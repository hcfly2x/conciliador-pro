from __future__ import annotations

import sqlite3
import unittest

import app


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.original_db_connect = app.db_connect
        self.original_auth_disabled = app.auth_mod.AUTH_DISABLED
        app.db_connect = lambda *args, **kwargs: self.conn
        app.auth_mod.AUTH_DISABLED = True
        self.client = app.app.test_client()
        self.conn.executescript(
            """
            CREATE TABLE categories(id TEXT PRIMARY KEY, type TEXT);
            CREATE TABLE subcategories(id TEXT PRIMARY KEY);
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY, account_id TEXT, date TEXT, description TEXT,
              description_norm TEXT, amount REAL, type TEXT, locked INTEGER,
              category_id TEXT, subcategory_id TEXT, notes TEXT, status TEXT,
              installment_plan_id TEXT, installment_current INTEGER, installment_total INTEGER,
              classified_by TEXT, classified_at TEXT,
              history_match_id TEXT, identity_score REAL, history_match_confirmed INTEGER,
              history_match_rejected_id TEXT, match_probability REAL, match_notes TEXT
            );
            CREATE TABLE installment_plans(
              id TEXT PRIMARY KEY, category_id TEXT, subcategory_id TEXT,
              classified_by TEXT, classified_at TEXT, updated_at TEXT
            );
            CREATE TABLE classification_history(
              id TEXT, source_file_id TEXT, account_id TEXT, date TEXT,
              description TEXT, description_norm TEXT, amount REAL, type TEXT,
              category_id TEXT, subcategory_id TEXT
            );
            CREATE TABLE audit_log(
              id TEXT, user_id TEXT, username TEXT, action TEXT, entity TEXT,
              entity_id TEXT, field TEXT, old_value TEXT, new_value TEXT,
              detail TEXT, created_at TEXT
            );
            INSERT INTO categories VALUES ('cat-expense','expense');
            INSERT INTO subcategories VALUES ('sub-market');
            INSERT INTO installment_plans VALUES ('plan-1',NULL,NULL,'','','');
            INSERT INTO transactions VALUES
              ('tx-1','acc','2026-01-10','LOJA','loja',-100,'expense',0,NULL,NULL,'','pending','plan-1',1,3,'','',NULL,0,0,NULL,0,''),
              ('tx-2','acc','2026-02-10','LOJA','loja',-100,'expense',0,NULL,NULL,'nota individual','pending','plan-1',2,3,'','',NULL,0,0,NULL,0,''),
              ('tx-link','acc','2026-03-10','MERCADO','mercado',-50,'expense',0,NULL,NULL,'','pending',NULL,NULL,NULL,'','','hist-1',98,0,NULL,98,'');
            """
        )

    def tearDown(self) -> None:
        app.db_connect = self.original_db_connect
        app.auth_mod.AUTH_DISABLED = self.original_auth_disabled
        self.conn.close()

    def test_classification_locks_and_propagates_only_category_fields(self) -> None:
        response = self.client.patch("/api/v1/transactions/tx-1/classify", json={
            "category_id": "cat-expense", "subcategory_id": "sub-market",
            "notes": "nota da primeira parcela", "apply_to_installments": True,
        })

        self.assertEqual(response.status_code, 200)
        first = self.conn.execute("SELECT category_id,subcategory_id,notes,locked FROM transactions WHERE id='tx-1'").fetchone()
        sibling = self.conn.execute("SELECT category_id,subcategory_id,notes,locked FROM transactions WHERE id='tx-2'").fetchone()
        self.assertEqual(first, ("cat-expense", "sub-market", "nota da primeira parcela", 1))
        self.assertEqual(sibling, ("cat-expense", "sub-market", "nota individual", 1))

    def test_locked_transaction_requires_explicit_unlock(self) -> None:
        self.conn.execute("UPDATE transactions SET locked=1 WHERE id='tx-1'")
        blocked = self.client.patch("/api/v1/transactions/tx-1/classify", json={"category_id": "cat-expense"})
        unlocked = self.client.post("/api/v1/transactions/tx-1/unlock", json={"reason": "correcao"})

        self.assertEqual(blocked.status_code, 423)
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(self.conn.execute("SELECT locked FROM transactions WHERE id='tx-1'").fetchone()[0], 0)

    def test_history_link_confirm_and_reject_are_persisted(self) -> None:
        confirmed = self.client.post("/api/v1/transactions/tx-link/history-link", json={"action": "confirm"})
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(self.conn.execute("SELECT history_match_confirmed FROM transactions WHERE id='tx-link'").fetchone()[0], 1)

        rejected = self.client.post("/api/v1/transactions/tx-link/history-link", json={"action": "reject"})
        self.assertEqual(rejected.status_code, 200)
        row = self.conn.execute("SELECT history_match_id,history_match_rejected_id FROM transactions WHERE id='tx-link'").fetchone()
        self.assertEqual(row, (None, "hist-1"))

    def test_document_transaction_deletion_requires_confirmation(self) -> None:
        response = self.client.delete("/api/v1/coverage/files", json={
            "path": "db://document-1", "delete_transactions": True,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "DELETE_TRANSACTIONS_CONFIRMATION_REQUIRED")


if __name__ == "__main__":
    unittest.main()
