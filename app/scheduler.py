"""Long-running scheduler: runs the ingestion and trigger-check jobs daily.

An alternative to driving app/jobs/ingest.py and app/jobs/check_triggers.py
via system cron — this process stays running and fires both jobs itself,
using APScheduler. Ingestion runs before the trigger check, so any filing
that dropped today is already searchable before that day's price move is
checked (see SPEC.md's "Decisions made" section).

Run with: python -m app.scheduler
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.jobs.check_triggers import run_once as run_check_triggers
from app.jobs.ingest import run_once as run_ingest

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Local time each job runs, 24-hour clock. Ingestion runs first so a
# same-day new filing is already embedded before that day's price move is
# checked.
INGEST_HOUR = 6
CHECK_TRIGGERS_HOUR = 17


def _run_ingest_job() -> None:
    """Scheduled wrapper around the ingestion job's `run_once`.

    `run_once` already handles per-company failures internally and never
    raises for them; this wrapper only guards against something truly
    unexpected escaping and killing the scheduler process, since one bad
    day's run must not cancel every future scheduled run along with it.
    """
    logger.info("Starting scheduled ingestion run")
    try:
        run_ingest()
    except Exception:
        logger.exception("Ingestion run raised an unexpected error")


def _run_check_triggers_job() -> None:
    """Scheduled wrapper around the trigger job's `run_once`.

    Same reasoning as `_run_ingest_job`: guards against an unexpected
    error taking down the scheduler itself.
    """
    logger.info("Starting scheduled trigger check")
    try:
        run_check_triggers()
    except Exception:
        logger.exception("Trigger check run raised an unexpected error")


def main() -> None:
    """Start the scheduler and run both jobs daily, forever.

    Loads settings once up front so a missing/invalid `.env` fails fast at
    startup, rather than silently failing every scheduled run thereafter.
    """
    get_settings()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _run_ingest_job,
        CronTrigger(hour=INGEST_HOUR, minute=0),
        id="ingest",
        name="Daily filing ingestion",
    )
    scheduler.add_job(
        _run_check_triggers_job,
        CronTrigger(hour=CHECK_TRIGGERS_HOUR, minute=0),
        id="check_triggers",
        name="Daily price trigger check",
    )

    logger.info(
        "Scheduler started: ingestion at %02d:00, trigger check at %02d:00 (local time)",
        INGEST_HOUR,
        CHECK_TRIGGERS_HOUR,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
