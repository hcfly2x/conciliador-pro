from __future__ import annotations

import logging
import os
import time

os.environ.setdefault("WORKER_MODE", "process")
os.environ.setdefault("WORKER_PROCESS", "1")

from app import db_connect, IS_POSTGRES, process_next_queued_job, recover_interrupted_process_jobs


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("conciliador.worker")


def main() -> None:
    interval = max(0.2, float(os.environ.get("WORKER_POLL_SECONDS", "1")))
    run_once = (os.environ.get("WORKER_RUN_ONCE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    lease_conn = None
    try:
        if IS_POSTGRES:
            lease_conn = db_connect(direct=True)
            acquired = bool(
                lease_conn.execute("SELECT pg_try_advisory_lock(815502)").fetchone()[0]
            )
            if not acquired:
                logger.warning("Outro worker possui o lease; encerrando este processo")
                return
        recovered = recover_interrupted_process_jobs()
        logger.info(
            "Worker iniciado; polling a cada %.1fs; jobs_recuperados=%s",
            interval,
            recovered,
        )
        if run_once:
            processed = process_next_queued_job()
            logger.info("Worker one-shot encerrado; job_processado=%s", processed)
            return
        while True:
            try:
                if not process_next_queued_job():
                    time.sleep(interval)
            except KeyboardInterrupt:
                logger.info("Worker encerrado")
                return
            except Exception:
                logger.exception("Falha inesperada no loop do worker")
                time.sleep(interval)
    finally:
        if lease_conn is not None:
            lease_conn.close()


if __name__ == "__main__":
    main()
