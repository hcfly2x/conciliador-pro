from __future__ import annotations

import sqlite3
import unittest

import app


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.original_db_connect = app.db_connect
        self.original_auth_disabled = app.auth_mod.AUTH_DISABLED
        self.original_user_for_token = app.auth_mod.user_for_token
        app.db_connect = lambda *args, **kwargs: self.conn
        app.auth_mod.AUTH_DISABLED = True
        self.client = app.app.test_client()
        self.conn.executescript(
            """
            CREATE TABLE categories(id TEXT PRIMARY KEY, name TEXT, type TEXT);
            CREATE TABLE subcategories(id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY, account_id TEXT, date TEXT, description TEXT,
              description_norm TEXT, amount REAL, type TEXT, locked INTEGER,
              category_id TEXT, subcategory_id TEXT, notes TEXT, status TEXT,
              installment_plan_id TEXT, installment_current INTEGER, installment_total INTEGER,
              classified_by TEXT, classified_at TEXT,
              history_match_id TEXT, identity_score REAL, history_match_confirmed INTEGER,
              history_match_rejected_id TEXT, match_probability REAL, match_notes TEXT,
              suggested_category_id TEXT, suggested_subcategory_id TEXT
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
            CREATE TABLE transaction_suggestion_state(
              transaction_id TEXT PRIMARY KEY, fingerprint TEXT, status TEXT,
              suggestion_count INTEGER, best_confidence REAL, dismissed INTEGER,
              calculated_at TEXT, error TEXT
            );
            CREATE TABLE transaction_suggestions(
              transaction_id TEXT, rank INTEGER, category_id TEXT, subcategory_id TEXT,
              confidence REAL, category_probability REAL, subcategory_probability REAL,
              frequency INTEGER, history_evidence INTEGER, transaction_evidence INTEGER,
              justification TEXT, subcategories_json TEXT, calculated_at TEXT,
              PRIMARY KEY(transaction_id, rank)
            );
            INSERT INTO categories VALUES ('cat-expense','DESPESA','expense');
            INSERT INTO subcategories VALUES ('sub-market','MERCADO');
            INSERT INTO installment_plans VALUES ('plan-1',NULL,NULL,'','','');
            INSERT INTO transactions VALUES
              ('tx-1','acc','2026-01-10','LOJA','loja',-100,'expense',0,NULL,NULL,'','pending','plan-1',1,3,'','',NULL,0,0,NULL,0,'',NULL,NULL),
              ('tx-2','acc','2026-02-10','LOJA','loja',-100,'expense',0,NULL,NULL,'nota individual','pending','plan-1',2,3,'','',NULL,0,0,NULL,0,'',NULL,NULL),
              ('tx-link','acc','2026-03-10','MERCADO','mercado',-50,'expense',0,NULL,NULL,'','pending',NULL,NULL,NULL,'','','hist-1',98,0,NULL,98,'','cat-expense','sub-market');
            INSERT INTO classification_history VALUES
              ('hist-1','seed:sheet:saidas','acc','2026-03-10','MERCADO','mercado',50,'expense','cat-expense','sub-market');
            """
        )

    def tearDown(self) -> None:
        app.db_connect = self.original_db_connect
        app.auth_mod.AUTH_DISABLED = self.original_auth_disabled
        app.auth_mod.user_for_token = self.original_user_for_token
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
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,category_id,subcategory_id,status,locked FROM transactions WHERE id='tx-link'"
            ).fetchone(),
            (1, "cat-expense", "sub-market", "reconciled", 1),
        )
        self.assertEqual(confirmed.get_json()["category_id"], "cat-expense")
        self.assertEqual(confirmed.get_json()["subcategory_id"], "sub-market")

        rejected = self.client.post("/api/v1/transactions/tx-link/history-link", json={"action": "reject"})
        self.assertEqual(rejected.status_code, 200)
        row = self.conn.execute(
            "SELECT history_match_id,history_match_rejected_id,suggested_category_id,suggested_subcategory_id "
            "FROM transactions WHERE id='tx-link'"
        ).fetchone()
        self.assertEqual(row, (None, "hist-1", None, None))

    def test_document_transaction_deletion_requires_confirmation(self) -> None:
        response = self.client.delete("/api/v1/coverage/files", json={
            "path": "db://document-1", "delete_transactions": True,
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "DELETE_TRANSACTIONS_CONFIRMATION_REQUIRED")

    def test_historical_references_block_category_and_subcategory_deletion(self) -> None:
        category = self.client.delete("/api/v1/categories/cat-expense")
        subcategory = self.client.delete("/api/v1/subcategories/sub-market")

        self.assertEqual(category.status_code, 400)
        self.assertEqual(category.get_json()["code"], "CATEGORY_IN_USE")
        self.assertGreater(category.get_json()["references"]["historico"], 0)
        self.assertEqual(subcategory.status_code, 400)
        self.assertEqual(subcategory.get_json()["code"], "SUBCATEGORY_IN_USE")

    def test_collaborator_can_read_cached_suggestions_through_batch_post(self) -> None:
        app.auth_mod.AUTH_DISABLED = False
        app.auth_mod.user_for_token = lambda _token: {
            "id": "collab", "username": "collab", "role": app.auth_mod.ROLE_COLLAB,
        }

        response = self.client.post(
            "/api/v1/transactions/suggestions/batch",
            json={"transaction_ids": ["tx-1"]},
            headers={"Authorization": "Bearer valid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["states"]["tx-1"], "pending")


class ClassificationQueueIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.original_db_connect = app.db_connect
        self.original_auth_disabled = app.auth_mod.AUTH_DISABLED
        app.db_connect = lambda *args, **kwargs: self.conn
        app.auth_mod.AUTH_DISABLED = True
        app.init_db()
        self.client = app.app.test_client()
        self.conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES ('acc','CONTA','checking','#000',1,'2026-01-01')"
        )
        self.conn.execute(
            "INSERT INTO categories(id,name,color,text_color,type) VALUES ('food','ALIMENTACAO','#000','#fff','expense')"
        )
        self.conn.execute("INSERT INTO subcategories(id,name) VALUES ('market','MERCADO')")
        self.conn.execute(
            """
            INSERT INTO classification_history(
              id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
            ) VALUES ('hist','seed:sheet:saidas','acc','2026-01-01','MERCADO','mercado',100,'expense','food','market')
            """
        )
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,amount,type,status,
              account_id,imported_file_id,locked
            ) VALUES ('target','key','2026-02-01','2026/02','MERCADO','mercado',-100,'expense','pending','acc','file',0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,amount,type,status,
              account_id,imported_file_id,locked,history_match_id,history_match_confirmed,identity_score
            ) VALUES (
              'link-target','link-key','2026-02-02','2026/02','MERCADO','mercado',-100,'expense',
              'pending','acc','file',0,'hist',0,99
            )
            """
        )
        self.conn.execute(
            "INSERT INTO suggestion_jobs(id,status,mode,created_at) VALUES ('queue-job','queued','incremental','2026-01-01')"
        )

    def tearDown(self) -> None:
        app.db_connect = self.original_db_connect
        app.auth_mod.AUTH_DISABLED = self.original_auth_disabled
        self.conn.close()

    def test_calculated_suggestion_appears_in_classification_queue(self) -> None:
        app._run_suggestion_job("queue-job")

        response = self.client.get(
            "/api/v1/transactions?classification_queue=suggestions&ledger_id=all&sort_by=suggestion_confidence"
        )
        summary = self.client.get("/api/v1/transactions/suggestions/summary")
        batch = self.client.post(
            "/api/v1/transactions/suggestions/batch", json={"transaction_ids": ["target"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["id"], "target")
        self.assertEqual(response.get_json()["items"][0]["suggestion_state"], "completed")
        self.assertEqual(summary.get_json()["strong"], 1)
        self.assertEqual(summary.get_json()["links"], 1)
        self.assertEqual(summary.get_json()["waiting"], 0)
        self.assertEqual(batch.get_json()["items"]["target"][0]["category_id"], "food")


class ReconciliationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.original_db_connect = app.db_connect
        self.original_auth_disabled = app.auth_mod.AUTH_DISABLED
        app.db_connect = lambda *args, **kwargs: self.conn
        app.auth_mod.AUTH_DISABLED = True
        app.init_db()
        self.conn.execute(
            """
            CREATE TABLE audit_log(
              id TEXT, user_id TEXT, username TEXT, action TEXT, entity TEXT,
              entity_id TEXT, field TEXT, old_value TEXT, new_value TEXT,
              detail TEXT, created_at TEXT
            )
            """
        )
        self.client = app.app.test_client()
        self.conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES ('bank-a','BANCO A','checking','#000',1,'2026-01-01')"
        )
        self.conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES ('bank-b','BANCO B','checking','#111',1,'2026-01-01')"
        )
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,amount,type,status,
              account_id,imported_file_id,locked
            ) VALUES
              ('expense','expense-key','2026-01-10','2026/01','TRANSFERENCIA ENVIADA','transferencia enviada',-250,'expense','pending','bank-a','file-a',0),
              ('income','income-key','2026-01-11','2026/01','TRANSFERENCIA RECEBIDA','transferencia recebida',250,'income','pending','bank-b','file-b',0),
              ('other-income','other-key','2026-01-12','2026/01','OUTRA ENTRADA','outra entrada',200,'income','pending','bank-b','file-b',0)
            """
        )

    def tearDown(self) -> None:
        app.db_connect = self.original_db_connect
        app.auth_mod.AUTH_DISABLED = self.original_auth_disabled
        self.conn.close()

    def test_manual_pair_is_excluded_from_reports_and_can_be_undone(self) -> None:
        candidates = self.client.get("/api/v1/reconciliations?view=candidates")
        created = self.client.post("/api/v1/reconciliations", json={
            "expense_transaction_id": "expense", "income_transaction_id": "income",
        })
        report_after = self.client.get("/api/v1/reports/summary?competence_month=2026/01")
        transactions_after = self.client.get("/api/v1/transactions?ledger_id=all")
        duplicate = self.client.post("/api/v1/reconciliations", json={
            "expense_transaction_id": "expense", "income_transaction_id": "income",
        })
        reconciliation_id = created.get_json()["id"]
        undone = self.client.post(f"/api/v1/reconciliations/{reconciliation_id}/undo", json={})
        report_restored = self.client.get("/api/v1/reports/summary?competence_month=2026/01")

        self.assertEqual(candidates.status_code, 200)
        self.assertEqual(len(candidates.get_json()["items"]), 1)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(report_after.get_json()["total_income"], 200)
        self.assertEqual(report_after.get_json()["total_expense"], 0)
        paired_items = {
            item["id"]: item for item in transactions_after.get_json()["items"]
            if item["id"] in {"expense", "income"}
        }
        self.assertEqual(paired_items["expense"]["reconciliation_id"], reconciliation_id)
        self.assertEqual(paired_items["expense"]["reconciliation_counterpart_id"], "income")
        self.assertEqual(paired_items["income"]["reconciliation_counterpart_id"], "expense")
        self.assertEqual(transactions_after.get_json()["summary"]["total_income"], 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(report_restored.get_json()["total_income"], 450)
        self.assertEqual(report_restored.get_json()["total_expense"], -250)

    def test_reconciliation_requires_opposite_types_and_equal_amounts(self) -> None:
        mismatch = self.client.post("/api/v1/reconciliations", json={
            "expense_transaction_id": "expense", "income_transaction_id": "other-income",
        })
        inverted = self.client.post("/api/v1/reconciliations", json={
            "expense_transaction_id": "income", "income_transaction_id": "expense",
        })

        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch.get_json()["code"], "AMOUNT_MISMATCH")
        self.assertEqual(inverted.status_code, 400)
        self.assertEqual(inverted.get_json()["code"], "TYPE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
