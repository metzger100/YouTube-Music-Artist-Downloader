"""Reporting owner (Phase 7 / Section 5.8).

Owns run logs, the summary JSON, the failed-jobs file, and user-facing console
output. It holds no business logic and makes no retry/cookie decisions.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from . import utils
from .config import AppConfig
from .models import DownloadJob, DownloadResult, RunSummary

LOGGER_NAME = "ytmusic_artist_downloader"


def setup_logging(config: AppConfig) -> Path:
    """Configure root logging to console + a timestamped run log file."""
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.logs_dir / f"run-{utils.run_stamp()}.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if config.verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if config.verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    return log_path


class Reporter:
    def __init__(self, config: AppConfig):
        self.config = config
        self.log = logging.getLogger(LOGGER_NAME)
        self.failed_path = config.state_dir / "failed-jobs.jsonl"
        self.summary_path = config.state_dir / "summary.json"
        self._lock = threading.Lock()

    def job_started(self, job: DownloadJob) -> None:
        self.log.info("→ %s — %s", job.artist_name, job.release_title)

    def job_finished(self, job: DownloadJob, result: DownloadResult) -> None:
        if result.success:
            self.log.info("  done: %s", job.release_title)
        else:
            self.log.warning(
                "  failed (%s, rc=%s): %s",
                result.error_category,
                result.return_code,
                job.release_title,
            )

    def record_failed_job(
        self, job: DownloadJob, result: DownloadResult | None, category: str
    ) -> dict:
        record = {
            "job_id": job.job_id,
            "artist_name": job.artist_name,
            "release_title": job.release_title,
            "release_url": job.release_url,
            "error_category": category,
            "return_code": result.return_code if result else 1,
            "stderr_log": str(result.stderr_log) if result else "",
            "created_at": utils.utc_now_iso(),
        }
        with self._lock:
            utils.append_jsonl(self.failed_path, record)
        return record

    def write_summary(self, summary: RunSummary) -> None:
        utils.write_json_atomic(self.summary_path, summary.to_dict())

    def print_final(self, summary: RunSummary) -> None:
        self.log.info("")
        self.log.info("Done:")
        self.log.info("  downloaded: %d", summary.jobs_done)
        self.log.info("  skipped: %d", summary.jobs_skipped)
        self.log.info("  failed: %d", summary.jobs_failed)
        if summary.jobs_failed:
            self.log.info("")
            self.log.info("Failed jobs:")
            self.log.info("  See %s", self.failed_path)
