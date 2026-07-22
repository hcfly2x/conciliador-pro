import datetime as dt
import io
import unittest

from openpyxl import load_workbook

from blueprints.system import AUDIT_COLUMNS, _audit_workbook


class AuditWorkbookTests(unittest.TestCase):
    def test_workbook_has_one_typed_row_per_transaction_and_source_links(self):
        row = {key: "" for _, key in AUDIT_COLUMNS}
        row.update(
            transaction_id="tx-1",
            tx_key="key-1",
            date="2026-07-22",
            competence_month="2026-07",
            description="Compra de teste",
            amount=-123.45,
            type="expense",
            status="pending",
            account_name="CARTAO TESTE",
            account_type="credit_card",
            category_name="Alimentação",
            installment_current=2,
            installment_total=3,
            history_match_id="hist-1",
            history_match_confirmed=1,
            imported_file_id="file-1",
            source_filename="fatura.pdf",
            source_file_hash="abc123",
            stored_document_id="doc-1",
            stored_document_filename="fatura.pdf",
        )

        output = _audit_workbook([row], "2026-07-22T12:00:00+00:00")
        workbook = load_workbook(io.BytesIO(output.getvalue()), data_only=False)
        transactions = workbook.worksheets[0]
        headers = [cell.value for cell in transactions[1]]

        self.assertEqual(workbook.sheetnames, ["Lançamentos", "Resumo", "Dicionário"])
        self.assertEqual(transactions.max_row, 2)
        self.assertEqual(transactions.max_column, len(AUDIT_COLUMNS))
        self.assertIsInstance(transactions.cell(2, headers.index("Data") + 1).value, dt.datetime)
        self.assertEqual(transactions.cell(2, headers.index("Valor") + 1).value, -123.45)
        self.assertEqual(
            transactions.cell(2, headers.index("Arquivo de origem") + 1).value,
            "fatura.pdf",
        )
        self.assertEqual(
            transactions.cell(2, headers.index("ID vínculo histórico") + 1).value,
            "hist-1",
        )
        self.assertIn("LancamentosAuditoria", transactions.tables)
        self.assertEqual(workbook["Resumo"]["B3"].value, 1)


if __name__ == "__main__":
    unittest.main()
