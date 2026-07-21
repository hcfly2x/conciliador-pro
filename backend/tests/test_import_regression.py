from __future__ import annotations

import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path

import app
import openpyxl
from pypdf import PdfWriter
from parsers.engine import run_import_pipeline


FIXTURES = Path(__file__).parent / "fixtures" / "imports"


class OfficialImportRegressionTests(unittest.TestCase):
    CASES = (
        ("santander_statement.pdf", "CONTA SANTANDER", "checking", 3, "2026/03", [-125.50, -10.00, 500.00]),
        ("xp_statement.csv", "CONTA XP", "checking", 3, "2026/03", [-200.50, -200.50, 1250.00]),
        ("nubank_statement.pdf", "CONTA NUBANK", "checking", 2, "2026/03", [-50.00, 200.00]),
        ("santander_card.pdf", "CARTAO SANTANDER", "credit_card", 12, "2026/04", [-(i * 10.0) for i in range(1, 13)]),
        ("xp_card.csv", "CARTAO XP", "credit_card", 3, "", [-125.90, -80.00, 25.00]),
        ("nubank_card.csv", "CARTAO NUBANK", "credit_card", 3, "", [-99.90, -45.67, 10.00]),
    )

    def test_six_official_document_types_have_exact_financial_results(self) -> None:
        for filename, account, account_type, count, competence, amounts in self.CASES:
            with self.subTest(filename=filename):
                path = FIXTURES / filename
                result = run_import_pipeline(path, account, account_type)
                detection = app.detect_document_identity(path)
                detected_competence = app.detect_competence(path, result.txs, account_type)

                self.assertEqual(len(result.txs), count)
                self.assertEqual(sorted(tx.amount_signed for tx in result.txs), sorted(amounts))
                self.assertEqual(detection["suggested_account_name"], account)
                self.assertEqual(detected_competence["month"], competence)
                self.assertTrue(all(tx.date.startswith("2026-03-") for tx in result.txs))

    def test_internal_duplicates_are_preserved_and_countable(self) -> None:
        result = run_import_pipeline(FIXTURES / "xp_statement.csv", "CONTA XP", "checking")
        signatures = [(tx.date, tx.description_norm, tx.amount_signed) for tx in result.txs]
        self.assertEqual(len(signatures), 3)
        self.assertEqual(len(set(signatures)), 2)

    def test_rejected_tabular_candidate_is_visible(self) -> None:
        result = run_import_pipeline(FIXTURES / "xp_statement.csv", "CONTA XP", "checking")
        self.assertEqual(len(result.rejected_lines), 1)
        self.assertIn("LINHA SEM VALOR", result.rejected_lines[0])

    def test_installments_and_card_credits_keep_their_meaning(self) -> None:
        xp = run_import_pipeline(FIXTURES / "xp_card.csv", "CARTAO XP", "credit_card")
        nubank = run_import_pipeline(FIXTURES / "nubank_card.csv", "CARTAO NUBANK", "credit_card")
        self.assertEqual((xp.txs[0].installment_current, xp.txs[0].installment_total), (2, 5))
        installment = next(tx for tx in nubank.txs if tx.is_installment)
        self.assertEqual((installment.installment_current, installment.installment_total), (3, 10))
        self.assertEqual(next(tx.amount_signed for tx in xp.txs if "ESTORNO" in tx.description), 25.0)
        self.assertEqual(next(tx.amount_signed for tx in nubank.txs if "CASHBACK" in tx.description), 10.0)

    def test_confirmed_empty_statements_are_not_parser_failures(self) -> None:
        cases = (
            ("xp_empty_statement.csv", "CONTA XP"),
            ("nubank_empty_statement.pdf", "CONTA NUBANK"),
        )
        for filename, account in cases:
            with self.subTest(filename=filename):
                result = run_import_pipeline(FIXTURES / filename, account, "checking")
                self.assertEqual(result.txs, [])
                self.assertTrue(result.empty_statement_confirmed)

    def test_corrupt_and_unexpected_pdfs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (("corrupt.pdf", b"not a pdf"), ("unexpected.pdf", b"%PDF-1.4\n%%EOF")):
                path = Path(tmp) / name
                path.write_bytes(content)
                with self.subTest(name=name), self.assertRaises(Exception):
                    run_import_pipeline(path, "CONTA NUBANK", "checking")

    def test_password_protected_pdf_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Extrato - 03-26 - Nubank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.encrypt("segredo")
            with path.open("wb") as output:
                writer.write(output)
            with self.assertRaises(Exception):
                run_import_pipeline(path, "CONTA NUBANK", "checking")

    def test_latin1_csv_and_xlsx_monetary_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "Extrato - 03-26 - XP.csv"
            csv_path.write_bytes(
                "Data;Descrição;Crédito;Débito\n01/03/2026;CRÉDITO TESTE;1.234,56;\n02/03/2026;DÉBITO TESTE;;(50,25)\n".encode("cp1252")
            )
            csv_result = run_import_pipeline(csv_path, "CONTA XP", "checking")
            self.assertEqual(sorted(tx.amount_signed for tx in csv_result.txs), [-50.25, 1234.56])

            xlsx_path = root / "Extrato - 04-26 - XP.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append(["Data", "Descrição", "Valor", "Tipo"])
            sheet.append(["03/04/2026", "RECEITA TESTE", 75.5, "entrada"])
            sheet.append(["04/04/2026", "DESPESA TESTE", "1.000,25", "saida"])
            workbook.save(xlsx_path)
            xlsx_result = run_import_pipeline(xlsx_path, "CONTA XP", "checking")
            self.assertEqual(sorted(tx.amount_signed for tx in xlsx_result.txs), [-1000.25, 75.5])


class DuplicateDatabaseRegressionTests(unittest.TestCase):
    def test_database_occurrences_only_block_the_same_number_of_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("CREATE TABLE transactions(account_id TEXT,date TEXT,amount REAL,description_norm TEXT,type TEXT,installment_current INTEGER,installment_total INTEGER,status TEXT)")
        conn.execute("INSERT INTO transactions VALUES ('acc','2026-03-02',-200.5,'pix enviado fornecedor teste','expense',0,0,'pending')")
        rows = [
            {"sig": "same", "date": "2026-03-02", "amount_signed": -200.5, "description_norm": "pix enviado fornecedor teste", "tx_type": "expense", "installment_current": 0, "installment_total": 0},
            {"sig": "same", "date": "2026-03-02", "amount_signed": -200.5, "description_norm": "pix enviado fornecedor teste", "tx_type": "expense", "installment_current": 0, "installment_total": 0},
        ]
        self.assertEqual(app.existing_db_duplicate_count_for_rows(conn, "acc", rows), 1)

    def test_same_file_is_rejected_even_when_duplicate_confirmation_is_true(self) -> None:
        conn = sqlite3.connect(":memory:")
        original_db_connect = app.db_connect
        original_docs = app.DOCS
        self.addCleanup(setattr, app, "db_connect", original_db_connect)
        self.addCleanup(setattr, app, "DOCS", original_docs)
        self.addCleanup(conn.close)
        app.db_connect = lambda *args, **kwargs: conn
        app.init_db()
        account_id = "account-xp"
        conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES (?,?,?,?,1,?)",
            (account_id, "CONTA XP", "checking", "#000000", "2026-03-01"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            app.DOCS = Path(tmp) / "documents"
            path = Path(tmp) / "Extrato - 03-26 - XP.csv"
            shutil.copyfile(FIXTURES / "xp_statement.csv", path)
            first, first_status = app.import_document(path, account_id, confirm_duplicates=True)
            shutil.copyfile(FIXTURES / "xp_statement.csv", path)
            second, second_status = app.import_document(path, account_id, confirm_duplicates=True)

        self.assertEqual(first_status, 201)
        self.assertEqual(first["total_inserted"], 3)
        self.assertEqual(second_status, 409)
        self.assertEqual(second["code"], "FILE_ALREADY_IMPORTED")
        self.assertEqual(conn.execute("SELECT COUNT(1) FROM transactions").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
