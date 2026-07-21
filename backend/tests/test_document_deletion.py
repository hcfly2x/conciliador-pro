from __future__ import annotations

import sqlite3
import unittest

import app


class DocumentDeletionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.original_db_connect = app.db_connect
        self.original_auth_disabled = app.auth_mod.AUTH_DISABLED
        app.db_connect = lambda *args, **kwargs: self.conn
        app.auth_mod.AUTH_DISABLED = True
        self.client = app.app.test_client()
        self.conn.executescript(
            """
            CREATE TABLE stored_documents(
              id TEXT PRIMARY KEY, filename TEXT, account_name TEXT,
              year_month TEXT, imported_file_id TEXT
            );
            CREATE TABLE imported_files(
              id TEXT PRIMARY KEY, filename TEXT, account_name TEXT, year TEXT, month TEXT
            );
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY, imported_file_id TEXT, installment_plan_id TEXT
            );
            CREATE TABLE transaction_reconciliations(
              expense_transaction_id TEXT, income_transaction_id TEXT
            );
            CREATE TABLE installment_plans(id TEXT PRIMARY KEY);
            CREATE TABLE audit_log(
              id TEXT, user_id TEXT, username TEXT, action TEXT, entity TEXT,
              entity_id TEXT, field TEXT, old_value TEXT, new_value TEXT,
              detail TEXT, created_at TEXT
            );
            INSERT INTO imported_files VALUES
              ('import-nubank','nubank-01-25.pdf','CARTAO NUBANK','2025','01');
            INSERT INTO stored_documents VALUES
              ('doc-nubank','nubank-01-25.pdf','CARTAO NUBANK','2024/12','import-nubank');
            INSERT INTO transactions VALUES
              ('tx-1','import-nubank',NULL),
              ('tx-2','import-nubank',NULL);
            """
        )

    def tearDown(self) -> None:
        app.db_connect = self.original_db_connect
        app.auth_mod.AUTH_DISABLED = self.original_auth_disabled
        self.conn.close()

    def test_direct_document_link_deletes_transactions_despite_month_mismatch(self) -> None:
        response = self.client.delete(
            "/api/v1/coverage/files",
            json={
                "path": "db://doc-nubank",
                "delete_transactions": True,
                "confirm_delete_transactions": "EXCLUIR LANCAMENTOS",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_transactions"], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM imported_files").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stored_documents").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
