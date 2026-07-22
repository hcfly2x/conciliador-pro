from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]


class WorkerProcessIntegrationTests(unittest.TestCase):
    def run_process(self, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            cwd=BACKEND,
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )

    def test_worker_consumes_persisted_job_across_web_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="conciliador-worker-") as temp_dir:
            env = os.environ.copy()
            env.update(
                {
                    "CONCILIADOR_DATA_DIR": temp_dir,
                    "AUTH_DISABLED": "1",
                    "WORKER_MODE": "process",
                    "WORKER_POLL_SECONDS": "0.2",
                }
            )
            env.pop("DATABASE_URL", None)
            first_web = self.run_process(env, "-c", "import app; print('web-ready')")
            self.assertEqual(first_web.returncode, 0, first_web.stderr)

            db_path = Path(temp_dir) / "conciliador_pro.db"
            job_id = str(uuid.uuid4())
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO recalculation_jobs(
                      id,status,processed,total,updated,error,created_at,started_at,finished_at
                    ) VALUES (?,'running',0,0,0,'',?,?,'')
                    """,
                    (
                        job_id,
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            restarted_before_worker = self.run_process(
                env, "-c", "import app; print('web-restarted-before-worker')"
            )
            self.assertEqual(
                restarted_before_worker.returncode, 0, restarted_before_worker.stderr
            )
            conn = sqlite3.connect(db_path)
            try:
                status_during_web_restart = conn.execute(
                    "SELECT status FROM recalculation_jobs WHERE id=?", (job_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(status_during_web_restart, "running")

            worker_env = {**env, "WORKER_PROCESS": "1", "WORKER_RUN_ONCE": "1"}
            worker = self.run_process(worker_env, "worker.py")
            self.assertEqual(worker.returncode, 0, worker.stderr)
            conn = sqlite3.connect(db_path)
            try:
                status = conn.execute(
                    "SELECT status FROM recalculation_jobs WHERE id=?", (job_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(status, "completed")

            restarted_web = self.run_process(env, "-c", "import app; print('web-restarted')")
            self.assertEqual(restarted_web.returncode, 0, restarted_web.stderr)
            conn = sqlite3.connect(db_path)
            try:
                status_after_restart = conn.execute(
                    "SELECT status FROM recalculation_jobs WHERE id=?", (job_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(status_after_restart, "completed")
