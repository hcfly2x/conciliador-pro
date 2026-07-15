from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import app
from parsers.engine import RawTx, _is_explicit_empty_nubank_text, enrich_transaction, run_import_pipeline


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


class ShadowMetadataTests(unittest.TestCase):
    def test_pix_metadata_preserves_method_and_cleans_merchant(self) -> None:
        result = app.extract_shadow_metadata("PIX ENVIADO MERCADO CENTRAL ID ABC123456")

        self.assertEqual(result["transaction_method"], "pix")
        self.assertEqual(result["merchant_norm"], "mercado central")
        self.assertEqual(result["bank_reference"], "abc123456")

    def test_credit_card_keeps_installment_as_structured_metadata(self) -> None:
        result = app.extract_shadow_metadata("COMPRA MERCADO CENTRAL 02/05", "credit_card", 2, 5)

        self.assertEqual(result["transaction_method"], "credit_card")
        self.assertEqual(result["merchant_norm"], "mercado central")
        self.assertEqual(result["shadow_installment_current"], 2)
        self.assertEqual(result["shadow_installment_total"], 5)


class HistoricalWorkbookNormalizationTests(unittest.TestCase):
    def test_degraded_sheet_and_header_labels_are_canonicalized(self) -> None:
        self.assertEqual(app.normalize_history_label("SA\ufffdDAS"), "saidas")
        self.assertEqual(app.normalize_history_label("H\ufffdLCIO-SMARTEK"), "helcio_smartek")
        self.assertEqual(app.history_sheet_key("SA\ufffdDAS"), "saidas")
        headers = app.map_headers(["DATA", "DESCRI\ufffd\ufffdO", "VALOR", "OBSERVA\ufffd\ufffdO", "\ufffd"])

        self.assertEqual(headers["data"], 0)
        self.assertEqual(headers["descricao"], 1)
        self.assertEqual(headers["valor"], 2)
        self.assertEqual(headers["observacao"], 3)
        self.assertNotIn("", headers)


class EmptyStatementTests(unittest.TestCase):
    def test_xp_header_only_csv_is_a_confirmed_empty_statement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Extrato - 02-26 - XP.csv"
            path.write_text("Data;Hora;Descricao;Valor;Saldo\n", encoding="utf-8")

            result = run_import_pipeline(path, "CONTA XP", "checking")

        self.assertEqual(result.txs, [])
        self.assertTrue(result.empty_statement_confirmed)
        self.assertTrue(any("sem movimentações" in warning for warning in result.warnings))

    def test_nubank_requires_explicit_empty_movement_evidence(self) -> None:
        self.assertTrue(_is_explicit_empty_nubank_text(
            "Saldo inicial R$ 0,00\nMovimentacoes\nNenhuma movimentacao\nSaldo final do periodo R$ 0,00"
        ))
        self.assertFalse(_is_explicit_empty_nubank_text(
            "Saldo inicial R$ 0,00\nMovimentacoes\nSaldo final do periodo R$ 0,00"
        ))


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


class HistoricalLinkCandidateTests(unittest.TestCase):
    def make_history_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE classification_history(
              id TEXT, date TEXT, description_norm TEXT, amount REAL,
              account_id TEXT, category_id TEXT, subcategory_id TEXT, type TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO classification_history VALUES (?,?,?,?,?,?,?,?)",
            ("hist-1", "2026-03-10", "mercado central", 150.0, "account-1", "cat-1", "sub-1", "expense"),
        )
        return conn

    def test_exact_history_identity_exceeds_review_threshold(self) -> None:
        conn = self.make_history_db()
        candidate = app.find_identity_match(conn, {
            "date": "2026-03-10", "description": "MERCADO CENTRAL",
            "description_norm": "mercado central", "amount": -150.0,
            "account_id": "account-1", "type": "expense",
        })

        self.assertIsNotNone(candidate)
        self.assertGreaterEqual(candidate["identity_score"], app.HISTORY_LINK_CANDIDATE_THRESHOLD)

    def test_different_amount_is_not_a_link_candidate(self) -> None:
        conn = self.make_history_db()
        candidate = app.find_identity_match(conn, {
            "date": "2026-03-10", "description": "MERCADO CENTRAL",
            "description_norm": "mercado central", "amount": -175.0,
            "account_id": "account-1", "type": "expense",
        })

        self.assertIsNone(candidate)

    def test_match_factors_explain_date_amount_and_description(self) -> None:
        factors = app.historical_match_factors(
            "2026-03-10", -150.50, "PIX MERCADO CENTRAL",
            "2026-03-11", 150.00, "MERCADO CENTRAL",
        )

        self.assertEqual(factors["match_date_difference_days"], 1)
        self.assertEqual(factors["match_amount_difference"], 0.50)
        self.assertGreater(factors["match_description_similarity"], 50)


class ClassificationValidationTests(unittest.TestCase):
    def make_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE categories(id TEXT, type TEXT)")
        conn.execute("CREATE TABLE subcategories(id TEXT)")
        conn.execute("INSERT INTO categories VALUES ('expense-cat','expense')")
        conn.execute("INSERT INTO categories VALUES ('income-cat','income')")
        conn.execute("INSERT INTO subcategories VALUES ('known-sub')")
        return conn

    def test_category_must_match_transaction_type(self) -> None:
        error, status = app.validate_classification_selection(
            self.make_db(), "income-cat", None, "expense"
        )

        self.assertEqual(status, 422)
        self.assertEqual(error["code"], "CATEGORY_TYPE_MISMATCH")

    def test_unknown_subcategory_is_rejected(self) -> None:
        error, status = app.validate_classification_selection(
            self.make_db(), "expense-cat", "missing-sub", "expense"
        )

        self.assertEqual(status, 404)
        self.assertEqual(error["code"], "SUBCATEGORY_NOT_FOUND")

    def test_valid_selection_is_accepted(self) -> None:
        error, status = app.validate_classification_selection(
            self.make_db(), "expense-cat", "known-sub", "expense"
        )

        self.assertIsNone(error)
        self.assertEqual(status, 200)


class SuggestionEvidenceTests(unittest.TestCase):
    def test_classified_transactions_are_used_as_evidence(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE categories(id TEXT, name TEXT)")
        conn.execute("CREATE TABLE subcategories(id TEXT, name TEXT)")
        conn.execute(
            """
            CREATE TABLE transactions(
              id TEXT,category_id TEXT,subcategory_id TEXT,date TEXT,
              description TEXT,description_norm TEXT,amount REAL,type TEXT,
              account_id TEXT,notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE classification_history(
              category_id TEXT,subcategory_id TEXT,date TEXT,description_norm TEXT,
              amount REAL,account_id TEXT,type TEXT,source_file_id TEXT
            )
            """
        )
        conn.execute("INSERT INTO categories VALUES ('food','ALIMENTACAO')")
        conn.execute("INSERT INTO subcategories VALUES ('market','MERCADO')")
        conn.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("source", "food", "market", "2026-02-10", "MERCADO CENTRAL", "mercado central", -100.0, "expense", "acc", ""),
        )
        conn.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("target", None, None, "2026-03-10", "MERCADO CENTRAL", "mercado central", -105.0, "expense", "acc", ""),
        )

        suggestions = app.build_suggestions_for_tx(conn, "target")

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["category_id"], "food")
        self.assertEqual(suggestions[0]["transaction_evidence"], 1)
        self.assertEqual(suggestions[0]["history_evidence"], 0)
        self.assertIn("lancamentos classificados", suggestions[0]["justification"])

    def test_imported_history_suggests_category_and_its_subcategory(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE categories(id TEXT, name TEXT)")
        conn.execute("CREATE TABLE subcategories(id TEXT, name TEXT)")
        conn.execute(
            """
            CREATE TABLE transactions(
              id TEXT,category_id TEXT,subcategory_id TEXT,date TEXT,
              description TEXT,description_norm TEXT,amount REAL,type TEXT,
              account_id TEXT,notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE classification_history(
              category_id TEXT,subcategory_id TEXT,date TEXT,description_norm TEXT,
              amount REAL,account_id TEXT,type TEXT,source_file_id TEXT
            )
            """
        )
        conn.execute("INSERT INTO categories VALUES ('fuel','COMBUSTIVEL')")
        conn.execute("INSERT INTO subcategories VALUES ('gas','POSTO')")
        conn.execute(
            "INSERT INTO classification_history VALUES (?,?,?,?,?,?,?,?)",
            ("fuel", "gas", "2025-12-19", "posto a1", 100.0, "acc", "expense", "seed:sheet:saidas"),
        )
        conn.execute(
            "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("target", None, None, "2025-12-19", "POSTO A1", "posto a1", -100.0, "expense", "acc", ""),
        )

        suggestions = app.build_suggestions_for_tx(conn, "target")

        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["category_id"], "fuel")
        self.assertEqual(suggestions[0]["subcategory_id"], "gas")
        self.assertGreaterEqual(suggestions[0]["category_probability"], 20.0)


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
