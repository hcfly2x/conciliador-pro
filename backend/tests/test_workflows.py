from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app
import db as db_module


def setup_real_test_database(owner: unittest.TestCase, filename: str) -> None:
    owner.tmp = tempfile.TemporaryDirectory()
    owner.db_path = Path(owner.tmp.name) / filename
    owner.original_db_connect = app.db_connect
    owner.original_auth_db_connect = app.auth_mod.db_connect
    owner.original_auth_disabled = app.auth_mod.AUTH_DISABLED

    def test_db_connect(*_args, **_kwargs):
        return sqlite3.connect(owner.db_path, factory=db_module._SqliteConnection)

    app.db_connect = test_db_connect
    app.auth_mod.db_connect = test_db_connect
    app.auth_mod.AUTH_DISABLED = True
    app.init_db()
    app.auth_mod.init_auth_db()
    owner.conn = sqlite3.connect(owner.db_path, isolation_level=None)


def teardown_real_test_database(owner: unittest.TestCase) -> None:
    owner.conn.close()
    app.db_connect = owner.original_db_connect
    app.auth_mod.db_connect = owner.original_auth_db_connect
    app.auth_mod.AUTH_DISABLED = owner.original_auth_disabled
    owner.tmp.cleanup()


class WorkerQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "worker.db")
        self.original_worker_mode = app.WORKER_MODE
        app.WORKER_MODE = "process"

    def tearDown(self) -> None:
        app.WORKER_MODE = self.original_worker_mode
        teardown_real_test_database(self)

    def test_worker_claims_each_persisted_job_only_once(self) -> None:
        self.conn.execute(
            "INSERT INTO suggestion_jobs(id,status,mode,created_at) VALUES ('job-1','queued','full','2026-01-01')"
        )
        with mock.patch.object(app, "_run_suggestion_job") as run_job:
            self.assertTrue(app.process_next_queued_job())
            self.assertFalse(app.process_next_queued_job())

        run_job.assert_called_once_with("job-1", True)
        self.assertEqual(
            self.conn.execute(
                "SELECT status FROM suggestion_jobs WHERE id='job-1'"
            ).fetchone()[0],
            "claimed",
        )


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "workflow.db")
        self.original_user_for_token = app.auth_mod.user_for_token
        self.client = app.app.test_client()
        self.conn.executescript(
            """
            INSERT INTO categories(id,name,color,text_color,type)
              VALUES ('cat-expense','DESPESA','#000','#fff','expense');
            INSERT INTO subcategories(id,name) VALUES ('sub-market','MERCADO');
            INSERT INTO installment_plans(
              id,account_id,description,description_norm,installment_total,installment_amount,
              first_seen_date,category_id,subcategory_id,classified_by,classified_at,created_at,updated_at
            ) VALUES ('plan-1','acc','LOJA','loja',3,100,'2026-01-10',NULL,NULL,'','','2026-01-01','2026-01-01');
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,
              locked,category_id,subcategory_id,notes,status,installment_plan_id,installment_current,
              installment_total,classified_by,classified_at,history_match_id,identity_score,
              history_match_confirmed,history_match_rejected_id,match_probability,match_notes,
              suggested_category_id,suggested_subcategory_id,imported_file_id
            ) VALUES
              ('tx-1','key-1','acc','2026-01-10','2026/01','LOJA','loja',-100,'expense',0,NULL,NULL,'','pending','plan-1',1,3,'','',NULL,0,0,NULL,0,'',NULL,NULL,'file'),
              ('tx-2','key-2','acc','2026-02-10','2026/02','LOJA','loja',-100,'expense',0,NULL,NULL,'nota individual','pending','plan-1',2,3,'','',NULL,0,0,NULL,0,'',NULL,NULL,'file'),
              ('tx-link','key-link','acc','2026-03-10','2026/03','MERCADO','mercado',-50,'expense',0,NULL,NULL,'','pending',NULL,NULL,NULL,'','','hist-1',98,0,NULL,98,'','cat-expense','sub-market','file');
            INSERT INTO classification_history(
              id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
            ) VALUES ('hist-1','seed:sheet:saidas','acc','2026-03-10','MERCADO','mercado',50,'expense','cat-expense','sub-market');
            """
        )

    def tearDown(self) -> None:
        app.auth_mod.user_for_token = self.original_user_for_token
        teardown_real_test_database(self)

    def test_classification_locks_and_propagates_only_category_fields(self) -> None:
        response = self.client.patch(
            "/api/v1/transactions/tx-1/classify",
            json={
                "category_id": "cat-expense",
                "subcategory_id": "sub-market",
                "notes": "nota da primeira parcela",
                "apply_to_installments": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        first = self.conn.execute(
            "SELECT category_id,subcategory_id,notes,locked FROM transactions WHERE id='tx-1'"
        ).fetchone()
        sibling = self.conn.execute(
            "SELECT category_id,subcategory_id,notes,locked FROM transactions WHERE id='tx-2'"
        ).fetchone()
        self.assertEqual(
            first, ("cat-expense", "sub-market", "nota da primeira parcela", 1)
        )
        self.assertEqual(sibling, ("cat-expense", "sub-market", "nota individual", 1))

    def test_locked_transaction_requires_explicit_unlock(self) -> None:
        self.conn.execute("UPDATE transactions SET locked=1 WHERE id='tx-1'")
        blocked = self.client.patch(
            "/api/v1/transactions/tx-1/classify", json={"category_id": "cat-expense"}
        )
        unlocked = self.client.post(
            "/api/v1/transactions/tx-1/unlock", json={"reason": "correcao"}
        )

        self.assertEqual(blocked.status_code, 423)
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(
            self.conn.execute(
                "SELECT locked FROM transactions WHERE id='tx-1'"
            ).fetchone()[0],
            0,
        )

    def test_history_link_confirm_and_reject_are_persisted(self) -> None:
        confirmed = self.client.post(
            "/api/v1/transactions/tx-link/history-link", json={"action": "confirm"}
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,category_id,subcategory_id,status,locked,account_id FROM transactions WHERE id='tx-link'"
            ).fetchone(),
            (1, "cat-expense", "sub-market", "reconciled", 1, "acc"),
        )
        self.assertEqual(confirmed.get_json()["category_id"], "cat-expense")
        self.assertEqual(confirmed.get_json()["subcategory_id"], "sub-market")

        rejected = self.client.post(
            "/api/v1/transactions/tx-link/history-link", json={"action": "reject"}
        )
        self.assertEqual(rejected.status_code, 200)
        row = self.conn.execute(
            "SELECT history_match_id,history_match_rejected_id,suggested_category_id,suggested_subcategory_id "
            "FROM transactions WHERE id='tx-link'"
        ).fetchone()
        self.assertEqual(row, (None, "hist-1", None, None))

    def test_batch_prepares_installment_total_link_without_changing_amount(
        self,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO classification_history(
              id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
            ) VALUES
              ('hist-plan','seed:sheet:saidas','acc','2026-01-10','LOJA','loja',300,'expense','cat-expense','sub-market')
            """
        )

        response = self.client.post(
            "/api/v1/transactions/history-links/batch", json={"ids": ["tx-1"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["matched_ids"], ["tx-1"])
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_id,history_match_confirmed,amount,category_id,subcategory_id,locked "
                "FROM transactions WHERE id='tx-1'"
            ).fetchone(),
            ("hist-plan", 1, -100.0, "cat-expense", "sub-market", 1),
        )

    def test_batch_confirms_installment_total_with_one_real_tolerance_and_half_description(
        self,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,installment_current,installment_total,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "tx-installment-tolerance",
                "key-installment-tolerance",
                "acc",
                "2026-03-10",
                "2026/03",
                "COMERCIO ALFA (Parcela 3 de 3)",
                "comercio alfa parcela 3 de 3",
                -370.0,
                "expense",
                0,
                "pending",
                0,
                0,
                3,
                3,
                "file",
            ),
        )
        self.conn.execute(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "hist-installment-tolerance",
                "seed:sheet:saidas",
                None,
                "2026-01-10",
                "COMERCIO ALFA SERVICO",
                "comercio alfa servico",
                1111.0,
                "expense",
                "cat-expense",
                "sub-market",
            ),
        )
        similarity = (
            app.description_similarity(
                "COMERCIO ALFA (Parcela 3 de 3)",
                "COMERCIO ALFA SERVICO",
            )
            * 100
        )
        self.assertGreaterEqual(similarity, 50.0)
        self.assertLess(similarity, 95.0)

        response = self.client.post(
            "/api/v1/transactions/history-links/batch",
            json={"ids": ["tx-installment-tolerance"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["matched_ids"], ["tx-installment-tolerance"]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,amount,category_id,subcategory_id,locked "
                "FROM transactions WHERE id='tx-installment-tolerance'"
            ).fetchone(),
            (1, -370.0, "cat-expense", "sub-market", 1),
        )

    def test_batch_does_not_auto_confirm_installment_above_one_real_difference(
        self,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,installment_current,installment_total,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "tx-installment-over-limit",
                "key-installment-over-limit",
                "acc",
                "2026-03-10",
                "2026/03",
                "COMERCIO ALFA (Parcela 3 de 3)",
                "comercio alfa parcela 3 de 3",
                -370.0,
                "expense",
                0,
                "pending",
                0,
                0,
                3,
                3,
                "file",
            ),
        )
        self.conn.execute(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "hist-installment-over-limit",
                "seed:sheet:saidas",
                None,
                "2026-01-10",
                "COMERCIO ALFA SERVICO",
                "comercio alfa servico",
                1111.01,
                "expense",
                "cat-expense",
                "sub-market",
            ),
        )

        response = self.client.post(
            "/api/v1/transactions/history-links/batch",
            json={"ids": ["tx-installment-over-limit"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["matched_ids"], [])
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,locked FROM transactions "
                "WHERE id='tx-installment-over-limit'"
            ).fetchone(),
            (0, 0),
        )

    def test_batch_sends_ambiguous_installment_candidates_to_manual_review(
        self,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,installment_current,installment_total,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "tx-installment-ambiguous",
                "key-installment-ambiguous",
                "acc",
                "2026-03-10",
                "2026/03",
                "COMERCIO ALFA (Parcela 3 de 3)",
                "comercio alfa parcela 3 de 3",
                -370.0,
                "expense",
                0,
                "pending",
                0,
                0,
                3,
                3,
                "file",
            ),
        )
        self.conn.executemany(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "hist-installment-secondary",
                    "seed:sheet:saidas",
                    None,
                    "2026-01-10",
                    "COMERCIO ALFA SERVICO",
                    "comercio alfa servico",
                    1111.0,
                    "expense",
                    "cat-expense",
                    "sub-market",
                ),
                (
                    "hist-installment-best",
                    "seed:sheet:saidas",
                    None,
                    "2026-01-10",
                    "COMERCIO ALFA (01/03)",
                    "comercio alfa 01 03",
                    1110.5,
                    "expense",
                    "cat-expense",
                    "sub-market",
                ),
            ],
        )

        response = self.client.post(
            "/api/v1/transactions/history-links/batch",
            json={"ids": ["tx-installment-ambiguous"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["matched_ids"], [])
        self.assertEqual(payload["manual_review_ids"], ["tx-installment-ambiguous"])
        self.assertTrue(
            any(
                "2 candidatos parcelados" in entry["message"]
                for entry in payload["logs"]
            )
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_id,history_match_confirmed,locked,match_notes "
                "FROM transactions WHERE id='tx-installment-ambiguous'"
            ).fetchone(),
            (
                "hist-installment-best",
                0,
                0,
                "Revisao manual: 2 candidatos parcelados validos",
            ),
        )

        confirmation = self.client.post(
            "/api/v1/transactions/tx-installment-ambiguous/history-link",
            json={"action": "confirm"},
        )
        self.assertEqual(confirmation.status_code, 200)
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,locked FROM transactions "
                "WHERE id='tx-installment-ambiguous'"
            ).fetchone(),
            (1, 1),
        )

    def test_batch_only_prepares_exact_date_amount_and_description_above_95(
        self,
    ) -> None:
        self.conn.executemany(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "tx-date-near",
                    "key-date-near",
                    "acc",
                    "2026-03-11",
                    "2026/03",
                    "MERCADO",
                    "mercado",
                    -50,
                    "expense",
                    0,
                    "pending",
                    0,
                    0,
                    "file",
                ),
                (
                    "tx-amount-near",
                    "key-amount-near",
                    "acc",
                    "2026-03-10",
                    "2026/03",
                    "MERCADO",
                    "mercado",
                    -50.50,
                    "expense",
                    0,
                    "pending",
                    0,
                    0,
                    "file",
                ),
                (
                    "tx-desc-near",
                    "key-desc-near",
                    "acc",
                    "2026-03-10",
                    "2026/03",
                    "MERCADO CENTRAL LOJA",
                    "mercado central loja",
                    -50,
                    "expense",
                    0,
                    "pending",
                    0,
                    0,
                    "file",
                ),
                (
                    "tx-no-candidate",
                    "key-no-candidate",
                    "acc",
                    "2026-08-25",
                    "2026/08",
                    "ASSINATURA DISTINTA",
                    "assinatura distinta",
                    -987.65,
                    "expense",
                    0,
                    "pending",
                    0,
                    0,
                    "file",
                ),
            ],
        )
        # As tolerancias gerais continuam encontrando estes candidatos; a regra
        # exata deve ser aplicada somente pela operacao em lote.
        near_candidate = app.find_identity_match(
            self.conn,
            {
                "date": "2026-03-11",
                "description_norm": "mercado",
                "amount": -50,
                "type": "expense",
                "account_id": "acc",
            },
        )
        self.assertIsNotNone(near_candidate)

        response = self.client.post(
            "/api/v1/transactions/history-links/batch",
            json={
                "ids": [
                    "tx-link",
                    "tx-date-near",
                    "tx-amount-near",
                    "tx-desc-near",
                    "tx-no-candidate",
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["matched_ids"], ["tx-link"])
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(
            set(payload["manual_review_ids"]),
            {"tx-date-near", "tx-amount-near", "tx-desc-near"},
        )
        self.assertEqual(payload["without_match_ids"], ["tx-no-candidate"])
        self.assertEqual(
            self.conn.execute(
                "SELECT history_match_confirmed,category_id,subcategory_id,locked FROM transactions WHERE id='tx-link'"
            ).fetchone(),
            (1, "cat-expense", "sub-market", 1),
        )
        manual_rows = self.conn.execute(
            "SELECT id,history_match_id,history_match_confirmed,locked FROM transactions "
            "WHERE id IN ('tx-date-near','tx-amount-near','tx-desc-near') ORDER BY id"
        ).fetchall()
        self.assertEqual(
            manual_rows,
            [
                ("tx-amount-near", "hist-1", 0, 0),
                ("tx-date-near", "hist-1", 0, 0),
                ("tx-desc-near", "hist-1", 0, 0),
            ],
        )

    def test_batch_treats_equivalent_installment_descriptions_as_exact(self) -> None:
        self.conn.execute(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "tx-installment-format",
                "key-installment-format",
                "acc",
                "2024-12-12",
                "2024/12",
                "PB*UBIQUITI (Parcela 1 de 3)",
                "pb ubiquiti parcela 1 de 3",
                -1578.02,
                "expense",
                0,
                "pending",
                0,
                0,
                "file",
            ),
        )
        self.conn.execute(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "hist-installment-format",
                "seed:sheet:saidas",
                None,
                "2024-12-12",
                "PB*Ubiquiti (01/03)",
                "pb ubiquiti 01 03",
                1578.02,
                "expense",
                "cat-expense",
                "sub-market",
            ),
        )

        response = self.client.post(
            "/api/v1/transactions/history-links/batch",
            json={"ids": ["tx-installment-format"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["matched_ids"], ["tx-installment-format"])

    def test_batch_confirms_two_consecutive_groups_of_fifty(self) -> None:
        transactions = []
        history = []
        ids = []
        for index in range(100):
            tx_id = f"tx-batch-{index:02d}"
            history_id = f"hist-batch-{index:02d}"
            description = f"LOJA LOTE {index:02d}"
            normalized = description.lower()
            amount = 100 + index
            ids.append(tx_id)
            transactions.append(
                (
                    tx_id,
                    f"key-batch-{index:02d}",
                    "acc",
                    "2026-04-10",
                    "2026/04",
                    description,
                    normalized,
                    -amount,
                    "expense",
                    0,
                    "pending",
                    0,
                    0,
                    "file",
                )
            )
            history.append(
                (
                    history_id,
                    "seed:sheet:saidas",
                    "acc",
                    "2026-04-10",
                    description,
                    normalized,
                    amount,
                    "expense",
                    "cat-expense",
                    "sub-market",
                )
            )
        self.conn.executemany(
            """
            INSERT INTO transactions(
              id,tx_key,account_id,date,competence_month,description,description_norm,amount,type,locked,status,
              history_match_confirmed,identity_score,imported_file_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            transactions,
        )
        self.conn.executemany(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            history,
        )
        self.conn.executemany(
            "INSERT INTO classification_history(id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    f"hist-noise-{index:04d}",
                    "seed:sheet:saidas",
                    "acc",
                    "2025-01-01",
                    f"HISTORICO SEM VINCULO {index:04d}",
                    f"historico sem vinculo {index:04d}",
                    10000 + index,
                    "expense",
                    "cat-expense",
                    "sub-market",
                )
                for index in range(3900)
            ],
        )

        first_response = self.client.post(
            "/api/v1/transactions/history-links/batch", json={"ids": ids[:50]}
        )
        second_response = self.client.post(
            "/api/v1/transactions/history-links/batch", json={"ids": ids[50:]}
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        for payload, expected_ids in (
            (first_response.get_json(), ids[:50]),
            (second_response.get_json(), ids[50:]),
        ):
            self.assertEqual(payload["matched"], 50)
            self.assertEqual(payload["manual_review"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(set(payload["matched_ids"]), set(expected_ids))
            self.assertEqual(set(payload["affected_ids"]), set(expected_ids))
            self.assertGreaterEqual(len(payload["logs"]), 3)
            self.assertGreaterEqual(payload["duration_ms"], 0)
        self.assertEqual(
            self.conn.execute(
                """
                SELECT COUNT(*) FROM transactions
                WHERE id LIKE 'tx-batch-%' AND history_match_confirmed=1 AND locked=1
                  AND category_id='cat-expense' AND subcategory_id='sub-market'
                """
            ).fetchone()[0],
            100,
        )

    def test_confirming_installment_link_classifies_plan_without_changing_values(
        self,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO classification_history(
              id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
            ) VALUES
              ('hist-plan','seed:sheet:saidas','acc','2026-01-10','LOJA','loja',300,'expense','cat-expense','sub-market')
            """
        )
        self.conn.execute(
            "UPDATE transactions SET history_match_id='hist-plan',identity_score=99,match_probability=99 WHERE id='tx-1'"
        )

        response = self.client.post(
            "/api/v1/transactions/tx-1/history-link", json={"action": "confirm"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.get_json()["affected_ids"]), {"tx-1", "tx-2"})
        self.assertEqual(
            self.conn.execute(
                "SELECT id,amount,category_id,subcategory_id,locked FROM transactions WHERE installment_plan_id='plan-1' ORDER BY id"
            ).fetchall(),
            [
                ("tx-1", -100.0, "cat-expense", "sub-market", 1),
                ("tx-2", -100.0, "cat-expense", "sub-market", 1),
            ],
        )

    def test_direct_link_must_be_reviewed_before_manual_classification(self) -> None:
        blocked = self.client.patch(
            "/api/v1/transactions/tx-link/classify",
            json={"category_id": "cat-expense", "subcategory_id": "sub-market"},
        )
        rejected = self.client.post(
            "/api/v1/transactions/tx-link/history-link", json={"action": "reject"}
        )
        classified = self.client.patch(
            "/api/v1/transactions/tx-link/classify",
            json={"category_id": "cat-expense", "subcategory_id": "sub-market"},
        )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()["code"], "HISTORY_LINK_REVIEW_REQUIRED")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(classified.status_code, 200)

    def test_bulk_classification_skips_pending_direct_links(self) -> None:
        response = self.client.patch(
            "/api/v1/transactions/bulk-classify",
            json={"ids": ["tx-1", "tx-link"], "category_id": "cat-expense"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["updated"], 1)
        self.assertEqual(response.get_json()["skipped_history_links"], 1)
        self.assertIsNone(
            self.conn.execute(
                "SELECT category_id FROM transactions WHERE id='tx-link'"
            ).fetchone()[0]
        )

    def test_document_transaction_deletion_requires_confirmation(self) -> None:
        response = self.client.delete(
            "/api/v1/coverage/files",
            json={
                "path": "db://document-1",
                "delete_transactions": True,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["code"], "DELETE_TRANSACTIONS_CONFIRMATION_REQUIRED"
        )

    def test_historical_references_block_category_and_subcategory_deletion(
        self,
    ) -> None:
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
            "id": "collab",
            "username": "collab",
            "role": app.auth_mod.ROLE_COLLAB,
        }

        response = self.client.post(
            "/api/v1/transactions/suggestions/batch",
            json={"transaction_ids": ["tx-1"]},
            headers={"Authorization": "Bearer valid"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["states"]["tx-1"], "pending")


class AsyncDocumentImportIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "async-import.db")
        self.original_import_document = app.import_document
        self.original_import_seed_workbook = app.import_seed_workbook
        self.client = app.app.test_client()

    def tearDown(self) -> None:
        app.import_document = self.original_import_document
        app.import_seed_workbook = self.original_import_seed_workbook
        teardown_real_test_database(self)

    def test_commit_returns_job_and_status_recovers_after_page_timeout(self) -> None:
        source = Path(self.tmp.name) / "preview.csv"
        source.write_text("data,descricao,valor\n", encoding="utf-8")
        with app.db_connect() as conn:
            conn.execute(
                """
                INSERT INTO import_previews(
                  id,filename,temp_path,account_id,detected_type,detection_confidence,created_at
                ) VALUES ('preview-1','arquivo.csv',?,'account-1','EXTRATO TESTE',1,'2026-07-21')
                """,
                (str(source),),
            )

        def successful_import(*_args, **kwargs):
            kwargs["progress"]("saving", 1, 2, "1 de 2 lancamentos preparados")
            kwargs["progress"]("saving", 2, 2, "2 de 2 lancamentos preparados")
            time.sleep(0.05)
            return (
                {
                    "imported_file_id": "file-1",
                    "filename": "arquivo.csv",
                    "account_name": "CONTA TESTE",
                    "total_parsed": 2,
                    "total_inserted": 2,
                    "total_duplicates": 0,
                    "total_errors": 0,
                    "transactions_preview": [],
                },
                201,
            )

        app.import_document = successful_import
        queued = self.client.post(
            "/api/v1/import/commit",
            json={
                "preview_id": "preview-1",
                "confirm_duplicates": True,
                "competence_month": "2026/07",
            },
        )
        self.assertEqual(queued.status_code, 202)
        job_id = queued.get_json()["job_id"]

        status = None
        for _ in range(50):
            status = self.client.get(f"/api/v1/import/jobs/{job_id}")
            if status.get_json()["status"] == "completed":
                break
            time.sleep(0.02)

        payload = status.get_json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["total_inserted"], 2)
        self.assertEqual((payload["processed"], payload["total"]), (2, 2))
        self.assertTrue(any("2 de 2" in entry["message"] for entry in payload["logs"]))
        self.assertFalse(source.exists())
        with app.db_connect() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM import_previews WHERE id='preview-1'"
                ).fetchone()
            )
        repeated = self.client.post(
            "/api/v1/import/commit", json={"preview_id": "preview-1"}
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.get_json(), {"job_id": job_id, "status": "completed"})

    def test_failed_job_preserves_preview_and_can_be_retried(self) -> None:
        source = Path(self.tmp.name) / "retry.csv"
        source.write_text("data,descricao,valor\n", encoding="utf-8")
        with app.db_connect() as conn:
            conn.execute(
                """
                INSERT INTO import_previews(
                  id,filename,temp_path,account_id,detected_type,detection_confidence,created_at
                ) VALUES ('preview-retry','retry.csv',?,'account-1','EXTRATO TESTE',1,'2026-07-21')
                """,
                (str(source),),
            )

        app.import_document = lambda *_args, **_kwargs: (
            {"detail": "falha controlada", "code": "TEST"},
            422,
        )
        first = self.client.post(
            "/api/v1/import/commit", json={"preview_id": "preview-retry"}
        )
        job_id = first.get_json()["job_id"]
        for _ in range(50):
            failed = self.client.get(f"/api/v1/import/jobs/{job_id}").get_json()
            if failed["status"] == "failed":
                break
            time.sleep(0.02)
        self.assertEqual(failed["status"], "failed")
        self.assertTrue(source.exists())

        app.import_document = lambda *_args, **_kwargs: (
            {
                "imported_file_id": "file-retry",
                "filename": "retry.csv",
                "account_name": "CONTA TESTE",
                "total_parsed": 1,
                "total_inserted": 1,
                "total_duplicates": 0,
                "total_errors": 0,
                "transactions_preview": [],
            },
            201,
        )
        retried = self.client.post(
            "/api/v1/import/commit", json={"preview_id": "preview-retry"}
        )
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(retried.get_json()["job_id"], job_id)
        for _ in range(50):
            completed = self.client.get(f"/api/v1/import/jobs/{job_id}").get_json()
            if completed["status"] == "completed":
                break
            time.sleep(0.02)
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(source.exists())

    def test_invalid_historical_replacement_preserves_active_base(self) -> None:
        source = Path(self.tmp.name) / "historico.xlsx"
        source.write_bytes(b"placeholder")
        with app.db_connect() as conn:
            conn.execute(
                "INSERT INTO categories(id,name,type,color,text_color) VALUES ('cat','CAT','expense','#000','#fff')"
            )
            conn.execute(
                """
                INSERT INTO classification_history(
                  id,source_file_id,date,description,description_norm,amount,type,category_id
                ) VALUES ('old','old-seed:sheet:saidas','2026-01-01','ANTIGO','antigo',10,'expense','cat')
                """
            )
            conn.execute(
                "INSERT INTO seed_import_jobs(id,status,filename,created_at) VALUES ('seed-job','queued','historico.xlsx','2026-07-21')"
            )
        app.import_seed_workbook = lambda *_args, **_kwargs: (
            {"total_inserted": 0},
            201,
        )

        app._run_seed_import_job("seed-job", source, True)

        with app.db_connect() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT source_file_id FROM classification_history"
                ).fetchall(),
                [("old-seed:sheet:saidas",)],
            )
            job = conn.execute(
                "SELECT status,result_json FROM seed_import_jobs WHERE id='seed-job'"
            ).fetchone()
        self.assertEqual(job[0], "failed")
        self.assertEqual(app.json.loads(job[1])["code"], "EMPTY_SEED_IMPORT")


class ClassificationQueueIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "classification.db")
        self.client = app.app.test_client()
        self.conn.execute(
            "INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES ('acc','CONTA','checking','#000',1,'2026-01-01')"
        )
        self.conn.execute(
            "INSERT INTO categories(id,name,color,text_color,type) VALUES ('food','ALIMENTACAO','#000','#fff','expense')"
        )
        self.conn.execute(
            "INSERT INTO subcategories(id,name) VALUES ('market','MERCADO')"
        )
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
        teardown_real_test_database(self)

    def test_calculated_suggestion_appears_in_classification_queue(self) -> None:
        app._run_suggestion_job("queue-job")

        response = self.client.get(
            "/api/v1/transactions?classification_queue=suggestions&ledger_id=all&sort_by=suggestion_confidence"
        )
        summary = self.client.get("/api/v1/transactions/suggestions/summary")
        batch = self.client.post(
            "/api/v1/transactions/suggestions/batch",
            json={"transaction_ids": ["target"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["id"], "target")
        self.assertEqual(
            response.get_json()["items"][0]["suggestion_state"], "completed"
        )
        self.assertEqual(summary.get_json()["strong"], 1)
        self.assertEqual(summary.get_json()["links"], 1)
        self.assertEqual(summary.get_json()["waiting"], 0)
        self.assertEqual(batch.get_json()["items"]["target"][0]["category_id"], "food")

    def test_objective_evaluation_uses_leave_one_out_and_reports_coverage(self) -> None:
        self.conn.execute(
            "INSERT INTO categories(id,name,color,text_color,type) VALUES ('home','MORADIA','#111','#fff','expense')"
        )
        self.conn.execute(
            "INSERT INTO subcategories(id,name) VALUES ('rent','ALUGUEL')"
        )
        self.conn.execute(
            """
            INSERT INTO classification_history(
              id,source_file_id,account_id,date,description,description_norm,amount,type,category_id,subcategory_id
            ) VALUES ('hist-home','seed:sheet:saidas','acc','2026-01-05','ALUGUEL','aluguel',900,'expense','home','rent')
            """
        )
        self.conn.executemany(
            """
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,amount,type,status,
              account_id,imported_file_id,locked,category_id,subcategory_id,history_match_confirmed
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            """,
            [
                (
                    "eval-food",
                    "eval-food-key",
                    "2026-03-01",
                    "2026/03",
                    "MERCADO",
                    "mercado",
                    -105,
                    "expense",
                    "pending",
                    "acc",
                    "file",
                    1,
                    "food",
                    "market",
                ),
                (
                    "eval-home",
                    "eval-home-key",
                    "2026-03-05",
                    "2026/03",
                    "ALUGUEL",
                    "aluguel",
                    -900,
                    "expense",
                    "pending",
                    "acc",
                    "file",
                    1,
                    "home",
                    "rent",
                ),
                (
                    "eval-unknown",
                    "eval-unknown-key",
                    "2026-03-06",
                    "2026/03",
                    "EVENTO SEM PADRAO",
                    "evento sem padrao",
                    -77,
                    "expense",
                    "pending",
                    "acc",
                    "file",
                    1,
                    "home",
                    "rent",
                ),
            ],
        )

        result = app.evaluate_suggestion_quality(
            self.conn, target_ids=["eval-food", "eval-home", "eval-unknown"]
        )
        endpoint = self.client.get(
            "/api/v1/transactions/suggestions/evaluation?limit=2"
        )

        self.assertEqual(result["evaluated"], 3)
        self.assertEqual(result["with_suggestions"], 2)
        self.assertEqual(result["coverage"], 66.67)
        self.assertEqual(result["category"]["top1_accuracy"], 100.0)
        self.assertEqual(result["category"]["top3_accuracy"], 100.0)
        self.assertEqual(result["subcategory"]["top1_accuracy"], 100.0)
        self.assertEqual(sum(bucket["count"] for bucket in result["calibration"]), 2)
        self.assertEqual(endpoint.status_code, 200)
        self.assertEqual(endpoint.get_json()["evaluated"], 2)
        self.assertTrue(endpoint.get_json()["truncated"])


class ReconciliationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "reconciliation.db")
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
        teardown_real_test_database(self)

    def test_manual_pair_is_excluded_from_reports_and_can_be_undone(self) -> None:
        candidates = self.client.get("/api/v1/reconciliations?view=candidates")
        created = self.client.post(
            "/api/v1/reconciliations",
            json={
                "expense_transaction_id": "expense",
                "income_transaction_id": "income",
            },
        )
        report_after = self.client.get(
            "/api/v1/reports/summary?competence_month=2026/01"
        )
        transactions_after = self.client.get("/api/v1/transactions?ledger_id=all")
        duplicate = self.client.post(
            "/api/v1/reconciliations",
            json={
                "expense_transaction_id": "expense",
                "income_transaction_id": "income",
            },
        )
        reconciliation_id = created.get_json()["id"]
        undone = self.client.post(
            f"/api/v1/reconciliations/{reconciliation_id}/undo", json={}
        )
        report_restored = self.client.get(
            "/api/v1/reports/summary?competence_month=2026/01"
        )

        self.assertEqual(candidates.status_code, 200)
        self.assertEqual(len(candidates.get_json()["items"]), 1)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(report_after.get_json()["total_income"], 200)
        self.assertEqual(report_after.get_json()["total_expense"], 0)
        paired_items = {
            item["id"]: item
            for item in transactions_after.get_json()["items"]
            if item["id"] in {"expense", "income"}
        }
        self.assertEqual(
            paired_items["expense"]["reconciliation_id"], reconciliation_id
        )
        self.assertEqual(
            paired_items["expense"]["reconciliation_counterpart_id"], "income"
        )
        self.assertEqual(
            paired_items["income"]["reconciliation_counterpart_id"], "expense"
        )
        self.assertEqual(transactions_after.get_json()["summary"]["total_income"], 200)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(report_restored.get_json()["total_income"], 450)
        self.assertEqual(report_restored.get_json()["total_expense"], -250)

    def test_reconciliation_requires_opposite_types_and_equal_amounts(self) -> None:
        mismatch = self.client.post(
            "/api/v1/reconciliations",
            json={
                "expense_transaction_id": "expense",
                "income_transaction_id": "other-income",
            },
        )
        inverted = self.client.post(
            "/api/v1/reconciliations",
            json={
                "expense_transaction_id": "income",
                "income_transaction_id": "expense",
            },
        )

        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(mismatch.get_json()["code"], "AMOUNT_MISMATCH")
        self.assertEqual(inverted.status_code, 400)
        self.assertEqual(inverted.get_json()["code"], "TYPE_MISMATCH")


class FinancialReportingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        setup_real_test_database(self, "reporting.db")
        self.client = app.app.test_client()
        self.conn.executescript(
            """
            INSERT INTO accounts(id,name,type,color,is_active,created_at) VALUES
              ('bank-a','BANCO A','checking','#000',1,'2026-01-01'),
              ('bank-b','BANCO B','checking','#111',1,'2026-01-01');
            INSERT INTO categories(id,name,color,text_color,type) VALUES
              ('food','ALIMENTACAO','#111','#fff','expense'),
              ('home','MORADIA','#222','#fff','expense'),
              ('salary','RECEITA','#333','#fff','income');
            INSERT INTO transactions(
              id,tx_key,date,competence_month,description,description_norm,amount,type,status,
              account_id,imported_file_id,locked,category_id
            ) VALUES
              ('jan-income','k1','2026-01-05','2026/01','SALARIO','salario',1000,'income','reconciled','bank-a','f1',1,'salary'),
              ('jan-food','k2','2026-01-06','2026/01','MERCADO','mercado',-400,'expense','reconciled','bank-a','f1',1,'food'),
              ('jan-home','k3','2026-01-07','2026/01','CONDOMINIO','condominio',-100,'expense','pending','bank-a','f1',0,'home'),
              ('transfer-out','k4','2026-01-08','2026/01','TRANSFERENCIA ENVIADA','transferencia enviada',-300,'expense','pending','bank-a','f1',0,NULL),
              ('transfer-in','k5','2026-01-09','2026/01','TRANSFERENCIA RECEBIDA','transferencia recebida',300,'income','pending','bank-b','f2',0,NULL),
              ('ignored','k6','2026-01-10','2026/01','IGNORADO','ignorado',-999,'expense','ignored','bank-a','f1',0,NULL),
              ('duplicate','k7','2026-01-11','2026/01','DUPLICADO','duplicado',999,'income','duplicate','bank-a','f1',0,NULL),
              ('feb-income','k8','2026-02-05','2026/02','FREELA','freela',500,'income','reconciled','bank-a','f3',1,'salary'),
              ('feb-food','k9','2026-02-06','2026/02','RESTAURANTE','restaurante',-125,'expense','reconciled','bank-a','f3',1,'food');
            """
        )

    def tearDown(self) -> None:
        teardown_real_test_database(self)

    def test_summary_category_percentages_and_monthly_totals_are_exact(self) -> None:
        january = self.client.get(
            "/api/v1/reports/summary?competence_month=2026/01"
        ).get_json()
        expenses = self.client.get(
            "/api/v1/reports/by-category?type=expense&competence_month=2026/01"
        ).get_json()
        monthly = self.client.get("/api/v1/reports/monthly").get_json()

        self.assertEqual(
            january,
            {
                "total_transactions": 5,
                "pending": 3,
                "reconciled": 2,
                "total_income": 1300.0,
                "total_expense": -800.0,
                "balance": 500.0,
            },
        )
        by_name = {row["category_name"]: row for row in expenses}
        self.assertEqual(
            (by_name["ALIMENTACAO"]["total"], by_name["ALIMENTACAO"]["percentage"]),
            (-400.0, 50.0),
        )
        self.assertEqual(
            (by_name["SEM CATEGORIA"]["total"], by_name["SEM CATEGORIA"]["percentage"]),
            (-300.0, 37.5),
        )
        self.assertEqual(
            (by_name["MORADIA"]["total"], by_name["MORADIA"]["percentage"]),
            (-100.0, 12.5),
        )
        self.assertEqual(
            monthly,
            [
                {
                    "month": "2026/02",
                    "income": 500.0,
                    "expense": -125.0,
                    "balance": 375.0,
                    "transaction_count": 2,
                },
                {
                    "month": "2026/01",
                    "income": 1300.0,
                    "expense": -800.0,
                    "balance": 500.0,
                    "transaction_count": 5,
                },
            ],
        )

    def test_reconciliation_removes_both_sides_from_every_report_and_undo_restores_them(
        self,
    ) -> None:
        created = self.client.post(
            "/api/v1/reconciliations",
            json={
                "expense_transaction_id": "transfer-out",
                "income_transaction_id": "transfer-in",
            },
        )
        self.assertEqual(created.status_code, 201)

        january = self.client.get(
            "/api/v1/reports/summary?competence_month=2026/01"
        ).get_json()
        expenses = self.client.get(
            "/api/v1/reports/by-category?type=expense&competence_month=2026/01"
        ).get_json()
        monthly = self.client.get("/api/v1/reports/monthly").get_json()
        self.assertEqual(
            (
                january["total_transactions"],
                january["total_income"],
                january["total_expense"],
                january["balance"],
            ),
            (3, 1000.0, -500.0, 500.0),
        )
        self.assertEqual(
            [
                (row["category_name"], row["total"], row["percentage"])
                for row in expenses
            ],
            [("ALIMENTACAO", -400.0, 80.0), ("MORADIA", -100.0, 20.0)],
        )
        january_month = next(row for row in monthly if row["month"] == "2026/01")
        self.assertEqual(
            january_month,
            {
                "month": "2026/01",
                "income": 1000.0,
                "expense": -500.0,
                "balance": 500.0,
                "transaction_count": 3,
            },
        )

        reconciliation_id = created.get_json()["id"]
        undone = self.client.post(
            f"/api/v1/reconciliations/{reconciliation_id}/undo", json={}
        )
        restored = self.client.get(
            "/api/v1/reports/summary?competence_month=2026/01"
        ).get_json()
        self.assertEqual(undone.status_code, 200)
        self.assertEqual(
            (
                restored["total_transactions"],
                restored["total_income"],
                restored["total_expense"],
                restored["balance"],
            ),
            (5, 1300.0, -800.0, 500.0),
        )


if __name__ == "__main__":
    unittest.main()
