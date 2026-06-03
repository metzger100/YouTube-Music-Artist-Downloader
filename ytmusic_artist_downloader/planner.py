"""Planning owner (Phase 4 / Section 5.3).

Converts discovered releases into deterministic download jobs and owns job
state. The downloader only *consumes* jobs; it never creates or mutates the
plan files.

Release-level resume is driven by **our own** state — ``state/jobs.json`` and a
``state/completed-releases.jsonl`` marker written when a release finishes
postprocessing. yt-dlp's download archive stores per-track IDs and is NOT a
reliable signal that a whole release is complete, so it is not used here for
release-level skipping.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import utils
from .models import DownloadJob, Release


class JobState:
    """Owns the on-disk job state (``state/jobs.json`` etc.).

    Used both to persist a fresh plan and to resume an interrupted run. Append
    operations are guarded by a lock so multiple download workers can record
    events to the same JSONL files safely.
    """

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.jobs_json = self.state_dir / "jobs.json"
        self.jobs_jsonl = self.state_dir / "jobs.jsonl"
        self.failed_jobs = self.state_dir / "failed-jobs.jsonl"
        self.completed_releases = self.state_dir / "completed-releases.jsonl"
        self.summary_json = self.state_dir / "summary.json"
        self._lock = threading.Lock()

    def load_jobs(self) -> list[DownloadJob]:
        raw = utils.read_json(self.jobs_json, default=[])
        return [DownloadJob.from_dict(j) for j in raw]

    def save_jobs(self, jobs: list[DownloadJob]) -> None:
        # jobs.json is the authoritative, deterministic snapshot.
        with self._lock:
            utils.write_json_atomic(self.jobs_json, [j.to_dict() for j in jobs])

    def append_event(self, job: DownloadJob) -> None:
        """Append a status transition to the append-only jobs.jsonl trail."""
        record = job.to_dict()
        record["recorded_at"] = utils.utc_now_iso()
        with self._lock:
            utils.append_jsonl(self.jobs_jsonl, record)

    def record_failure(self, record: dict) -> None:
        with self._lock:
            utils.append_jsonl(self.failed_jobs, record)

    def mark_release_complete(self, job: DownloadJob) -> None:
        """Write a durable release-completion marker (Section 10 resume)."""
        with self._lock:
            utils.append_jsonl(
                self.completed_releases,
                {
                    "job_id": job.job_id,
                    "release_url": job.release_url,
                    "completed_at": utils.utc_now_iso(),
                },
            )

    def completed_job_ids(self) -> set[str]:
        return {
            rec.get("job_id", "")
            for rec in utils.read_jsonl(self.completed_releases)
            if rec.get("job_id")
        }


class Planner:
    """Creates jobs from releases with deduplication and skip logic."""

    def __init__(
        self,
        output_root: Path,
        completed_job_ids: set[str] | None = None,
    ):
        self.output_root = Path(output_root)
        # Release-level completion comes from our own marker file, not yt-dlp.
        self.completed_job_ids = set(completed_job_ids or set())

    def create_jobs(
        self,
        releases: list[Release],
        existing_jobs: list[DownloadJob] | None = None,
    ) -> list[DownloadJob]:
        """Build the deduplicated, deterministic job list.

        - duplicate releases collapse to a single job (same job_id)
        - jobs already marked ``done`` in ``existing_jobs`` keep that status
        - jobs present in the completed-releases marker are marked ``done``
        """
        existing_by_id = {j.job_id: j for j in (existing_jobs or [])}

        jobs: dict[str, DownloadJob] = {}
        for rel in releases:
            job_id = utils.make_job_id(rel.artist_name, rel.url)
            if job_id in jobs:
                continue  # deduplicate

            prior = existing_by_id.get(job_id)
            status = "pending"
            if (prior and prior.status == "done") or job_id in self.completed_job_ids:
                status = "done"

            jobs[job_id] = DownloadJob(
                job_id=job_id,
                artist_name=rel.artist_name,
                release_title=rel.title,
                release_type=rel.release_type,
                release_url=rel.url,
                output_root=self.output_root,
                status=status,
            )

        # Deterministic ordering by job_id keeps jobs.json stable across runs.
        return [jobs[k] for k in sorted(jobs)]
