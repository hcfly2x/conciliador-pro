from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import app
from parsers.engine import RawTx, enrich_transaction


class DocumentDetectionTests(unittest.TestCase):
    def test_card_identity_uses_filename_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cartao - 03-26 - XP.csv"
            path.write_text("Data de compra,Nome no extrato,Valor\n01/03/2026,LOJA,10.00\n", encoding="utf-8")

            result = app.detect_document_identity(path)

        self.assertEqual(result["suggested_account_name"], "CARTAO XP")
        self.assertGreaterEqual(result["confidence"], 70)
        self.assertTrue(result["evidence"])

    def test_statement_identity_uses_statement_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Extrato - 03-26 - Santander.csv"
            path.write_text("Extrato consolidado\nConta corrente\nSaldo em 31/03\n", encoding="utf-8")

            result = app.detect_document_identity(path)

        self.assertEqual(result["suggested_account_name"], "CONTA SANTANDER")
        self.assertEqual(result["account_type"], "checking")


class CompetenceDetectionTests(unittest.TestCase):
    def test_card_uses_latest_transaction_month(self) -> None:
        txs = [
            SimpleNamespace(date="2025-12-03"),
            SimpleNamespace(date="2025-12-29"),
            SimpleNamespace(date="2025-11-28"),
        ]
        result = app.detect_competence(Path("Cartao - 01-26 - XP.csv"), txs, "credit_card")

        self.assertEqual(result["month"], "2025/12")
        self.assertEqual(result["strategy"], "latest_card_transaction")
        self.assertTrue(result["warning"])

    def test_statement_uses_filename_when_dates_confirm_it(self) -> None:
        txs = [SimpleNamespace(date=f"2026-03-{day:02d}") for day in range(1, 10)]
        result = app.detect_competence(Path("Extrato - 03-26 - XP.csv"), txs, "checking")

        self.assertEqual(result["month"], "2026/03")
        self.assertEqual(result["strategy"], "statement_filename_and_transactions")
        self.assertEqual(result["warning"], "")

    def test_statement_prefers_declared_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extrato.csv"
            path.write_text("Periodo de 01/04/2026 a 30/04/2026\n", encoding="utf-8")
            txs = [SimpleNamespace(date="2026-04-10"), SimpleNamespace(date="2026-04-20")]

            result = app.detect_competence(path, txs, "checking")

        self.assertEqual(result["month"], "2026/04")
        self.assertEqual(result["strategy"], "statement_declared_period")


class InstallmentTests(unittest.TestCase):
    def test_installment_keeps_statement_amount(self) -> None:
        # CSV de cartao usa valor positivo para compra; o parser base chama isso
        # de income antes da regra especifica de cartao converte-lo em despesa.
        raw = RawTx("2026-03-10", "LOJA TESTE", 100.0, "income", "03/10", "linha")

        result = enrich_transaction(raw, "credit_card", "csv")

        self.assertEqual(result.installment_current, 3)
        self.assertEqual(result.installment_total, 10)
        self.assertEqual(result.amount_signed, -100.0)

    def test_negative_card_value_becomes_credit(self) -> None:
        raw = RawTx("2026-03-10", "ESTORNO LOJA", 25.0, "expense", "", "linha")

        result = enrich_transaction(raw, "credit_card", "csv")

        self.assertEqual(result.tx_type, "income")
        self.assertEqual(result.amount_signed, 25.0)

    def make_plan_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE installment_plans(
              id TEXT PRIMARY KEY, account_id TEXT, description TEXT, description_norm TEXT,
              installment_total INTEGER, installment_amount REAL, first_seen_date TEXT,
              category_id TEXT, subcategory_id TEXT, classified_by TEXT, classified_at TEXT,
              created_at TEXT, updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY, date TEXT, installment_current INTEGER,
              installment_plan_id TEXT
            )
            """
        )
        return conn

    def installment_row(self, date: str, current: int) -> dict[str, object]:
        return {
            "date": date,
            "description": "LOJA TESTE",
            "description_norm": "loja teste",
            "amount_signed": -100.0,
            "installment_current": current,
            "installment_total": 10,
        }

    def test_successive_installments_share_a_plan(self) -> None:
        conn = self.make_plan_db()
        first_id, _ = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-01-10", 1))
        conn.execute(
            "INSERT INTO transactions(id,date,installment_current,installment_plan_id) VALUES (?,?,?,?)",
            ("tx-1", "2026-01-10", 1, first_id),
        )

        second_id, _ = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-02-10", 2))

        self.assertEqual(second_id, first_id)
        self.assertEqual(conn.execute("SELECT COUNT(1) FROM installment_plans").fetchone()[0], 1)

    def test_same_installment_number_starts_a_separate_plan(self) -> None:
        conn = self.make_plan_db()
        first_id, _ = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-01-10", 1))
        conn.execute(
            "INSERT INTO transactions(id,date,installment_current,installment_plan_id) VALUES (?,?,?,?)",
            ("tx-1", "2026-01-10", 1, first_id),
        )

        other_id, _ = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-01-10", 1))

        self.assertNotEqual(other_id, first_id)
        self.assertEqual(conn.execute("SELECT COUNT(1) FROM installment_plans").fetchone()[0], 2)

    def test_existing_plan_returns_classification_for_inheritance(self) -> None:
        conn = self.make_plan_db()
        first_id, _ = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-01-10", 1))
        conn.execute(
            "UPDATE installment_plans SET category_id=?,subcategory_id=?,classified_by=? WHERE id=?",
            ("cat", "sub", "helcio", first_id),
        )
        conn.execute(
            "INSERT INTO transactions(id,date,installment_current,installment_plan_id) VALUES (?,?,?,?)",
            ("tx-1", "2026-01-10", 1, first_id),
        )

        second_id, plan = app.find_or_create_installment_plan(conn, "card", self.installment_row("2026-02-10", 2))

        self.assertEqual(second_id, first_id)
        self.assertIsNotNone(plan)
        self.assertEqual(plan[1:4], ("cat", "sub", "helcio"))

    def test_original_purchase_date_can_repeat_across_installments(self) -> None:
        self.assertTrue(app.installment_members_are_compatible("2026-01-10", 1, "2026-01-10", 2))

    def test_unrelated_installment_dates_do_not_match(self) -> None:
        self.assertFalse(app.installment_members_are_compatible("2026-01-10", 1, "2026-04-25", 2))


if __name__ == "__main__":
    unittest.main()
