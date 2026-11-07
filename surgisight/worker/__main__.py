"""Background worker process polling the database job queue (WP5).

Usage:
    python -m surgisight.worker [--once] [--poll-interval 2.0]
"""

from __future__ import annotations

import argparse
import logging
import time

from surgisight.db import SyncSessionLocal
from surgisight.worker.orchestrator import PipelineOrchestrator
from surgisight.worker.queue import claim_next_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("surgisight.worker")


def run_worker_loop(
    once: bool = False, poll_interval: float = 2.0, worker_id: str = "worker_1"
) -> None:
    logger.info(
        "Starting SurgiSight worker (id=%s, once=%s, interval=%.1fs)",
        worker_id,
        once,
        poll_interval,
    )

    while True:
        with SyncSessionLocal() as session:
            claimed_run = claim_next_run(session, worker_id=worker_id)
            if claimed_run:
                logger.info(
                    "Claimed run %s for video %s. Executing pipeline...",
                    claimed_run.id,
                    claimed_run.video_id,
                )
                orchestrator = PipelineOrchestrator(session, claimed_run.id)
                try:
                    orchestrator.execute()
                    logger.info("Run %s completed successfully.", claimed_run.id)
                except Exception as exc:
                    logger.error("Run %s failed: %s", claimed_run.id, exc)

                if once:
                    break
                continue

        if once:
            logger.info("No pending runs. Exiting (--once).")
            break

        time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="SurgiSight background job worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument(
        "--poll-interval", type=float, default=2.0, help="Seconds between queue polls"
    )
    parser.add_argument("--worker-id", default="worker_main", help="Unique worker identifier")
    args = parser.parse_args()

    run_worker_loop(once=args.once, poll_interval=args.poll_interval, worker_id=args.worker_id)


if __name__ == "__main__":
    main()
