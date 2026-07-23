import hashlib
import sqlite3
import unittest

from blueprints.system import _backfill_document_content


class DocumentBackfillTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript(
            """
            CREATE TABLE imported_files(
              id TEXT PRIMARY KEY,
              filename TEXT,
              account_name TEXT,
              year TEXT,
              month TEXT,
              file_hash TEXT,
              imported_at TEXT
            );
            CREATE TABLE stored_documents(
              id TEXT PRIMARY KEY,
              account_name TEXT,
              year_month TEXT,
              filename TEXT,
              size INTEGER,
              content_b64 TEXT,
              created_at TEXT,
              imported_file_id TEXT
            );
            CREATE TABLE transactions(
              id TEXT PRIMARY KEY,
              imported_file_id TEXT,
              competence_month TEXT
            );
            """
        )
        self.content = b"%PDF-1.4\noriginal audit document\n%%EOF\n"
        self.sha1 = hashlib.sha1(self.content).hexdigest()
        self.conn.execute(
            """
            INSERT INTO imported_files
              (id,filename,account_name,year,month,file_hash,imported_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                "batch-1",
                "preview-original.pdf",
                "CONTA SANTANDER",
                "2025",
                "01",
                self.sha1,
                "2026-07-23T00:00:00",
            ),
        )
        self.conn.executemany(
            "INSERT INTO transactions VALUES (?,?,?)",
            [
                ("tx-1", "batch-1", "2025/01"),
                ("tx-2", "batch-1", "2025/01"),
            ],
        )

    def tearDown(self):
        self.conn.close()

    def test_backfill_links_original_without_touching_transactions(self):
        before = self.conn.execute(
            "SELECT id,imported_file_id,competence_month FROM transactions ORDER BY id"
        ).fetchall()

        result = _backfill_document_content(
            self.conn, "Extrato - 01-25 - Santander.pdf", self.content
        )

        after = self.conn.execute(
            "SELECT id,imported_file_id,competence_month FROM transactions ORDER BY id"
        ).fetchall()
        stored = self.conn.execute(
            """
            SELECT account_name,year_month,filename,size,imported_file_id
            FROM stored_documents
            """
        ).fetchone()
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["transactions"], 2)
        self.assertEqual(result["sha1"], self.sha1)
        self.assertEqual(
            stored,
            (
                "CONTA SANTANDER",
                "2025/01",
                "EXTRATO_01_25_SANTANDER.pdf",
                len(self.content),
                "batch-1",
            ),
        )

    def test_backfill_is_idempotent(self):
        first = _backfill_document_content(
            self.conn, "Extrato - 01-25 - Santander.pdf", self.content
        )
        second = _backfill_document_content(
            self.conn, "Extrato - 01-25 - Santander.pdf", self.content
        )

        self.assertEqual(second["status"], "already_present")
        self.assertEqual(second["document_id"], first["document_id"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(1) FROM stored_documents").fetchone()[0],
            1,
        )

    def test_backfill_rejects_unknown_content(self):
        with self.assertRaisesRegex(LookupError, "SHA-1"):
            _backfill_document_content(
                self.conn, "arquivo-diferente.pdf", b"conteudo desconhecido"
            )


if __name__ == "__main__":
    unittest.main()
