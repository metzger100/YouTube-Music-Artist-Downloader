"""Command-line entry point and lifecycle orchestrator.

Wires the independent layers together across the seven phases. The CLI itself
contains no domain logic beyond sequencing and error handling.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from . import errors
from .config import build_config, validate_config, AppConfig
from .cookies import build_cookie_provider
from .discovery import (
    DiscoveryCache,
    DiscoveryNoMatchError,
    YTMusicDiscoveryProvider,
    manual_release,
)
from .downloader import Downloader
from .inputs import parse_artists_file, parse_direct_releases_file
from .metadata import MetadataProcessor
from .models import Release, RunSummary
from .planner import JobState, Planner
from .reporting import Reporter, setup_logging
from .storage import StorageManager
from . import utils


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytmusic_artist_downloader",
        description=(
            "Discover artists/releases via ytmusicapi and download them with "
            "yt-dlp. Resumable, conservative, and safe with existing files."
        ),
    )
    p.add_argument("--artists", help="File containing artist names.")
    p.add_argument("--direct-releases", help="File containing direct release URLs.")
    p.add_argument("--output-dir", default="music", help="Final music folder. Default: music")
    p.add_argument("--work-dir", default="work", help="Temporary working folder. Default: work")
    p.add_argument("--cache-dir", default="cache", help="Discovery cache folder. Default: cache")
    p.add_argument("--state-dir", default="state", help="Runtime state folder. Default: state")
    p.add_argument("--auth", choices=["none", "cookies"], default="none",
                   help="yt-dlp authentication mode. Default: none")
    p.add_argument("--cookies", help="Static Netscape cookie file for yt-dlp.")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel yt-dlp jobs. Default: 1")
    p.add_argument("--concurrent-fragments", type=int, default=2,
                   help="yt-dlp concurrent fragment count. Default: 2")
    p.add_argument("--conflict-policy", default="merge-safe",
                   choices=sorted(
                       ["merge-safe", "rename-new", "rename-existing",
                        "skip-existing", "replace-existing"]
                   ),
                   help="Folder conflict policy. Default: merge-safe")
    p.add_argument("--refresh-discovery", action="store_true",
                   help="Ignore cached discovery data.")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve artists and create job plan, but do not download.")
    p.add_argument("--fail-fast", action="store_true",
                   help="Stop after first failed job.")
    p.add_argument("--allow-low-confidence", action="store_true",
                   help="Allow low-confidence artist matches.")
    p.add_argument("--no-metadata-patch", action="store_true",
                   help="Disable post-download album-artist tagging.")
    p.add_argument("--verbose", action="store_true", help="Print detailed logs.")
    return p


# ── Phase 3: discovery ────────────────────────────────────────────────────--
def run_discovery(
    config: AppConfig,
    reporter: Reporter,
    cache: DiscoveryCache,
    summary: RunSummary,
) -> list[Release]:
    artists: list = []
    inline_releases: list = []
    if config.input_file:
        artists, inline = parse_artists_file(config.input_file)
        inline_releases += inline
    if config.direct_releases_file:
        inline_releases += parse_direct_releases_file(config.direct_releases_file)

    summary.artists_requested = len(artists)

    # Fingerprint the artist input so a changed input file invalidates the
    # cache. Includes every identity-relevant field, not just the display name,
    # so two entries that differ only by channel/browse ID hash differently.
    fingerprint = utils.input_fingerprint(
        *[
            "|".join(
                [
                    a.query or "",
                    a.provided_name or "",
                    a.provided_url or "",
                    a.provided_browse_id or "",
                ]
            )
            for a in artists
        ]
    )
    manual = [manual_release(r) for r in inline_releases]

    # Cache hit: reuse releases only if the input fingerprint matches.
    if config.discovery_cache and not config.refresh_discovery:
        cached = cache.load_releases(fingerprint)
        if cached:
            reporter.log.info("Using cached discovery (%d releases).", len(cached))
            # Manual releases always merge in fresh (they bypass discovery).
            combined = cached + manual
            summary.releases_found = len(combined)
            return combined

    provider = YTMusicDiscoveryProvider(config.confidence_threshold)
    identities = []
    releases: list[Release] = []

    for req in artists:
        try:
            identity = provider.resolve_artist(req)
        except DiscoveryNoMatchError as exc:
            reporter.log.warning("No match for %r: %s", req.query, exc)
            cache.record_error(errors.DISCOVERY_NO_MATCH, req.query, str(exc))
            continue
        except errors.DiscoveryError as exc:
            reporter.log.warning("Discovery failed for %r: %s", req.query, exc)
            cache.record_error(errors.DISCOVERY_API_ERROR, req.query, str(exc))
            continue

        if identity.confidence < config.confidence_threshold and not config.allow_low_confidence:
            reporter.log.warning(
                "Skipping low-confidence match for %r (%.2f).",
                req.query, identity.confidence,
            )
            cache.record_error(
                errors.DISCOVERY_LOW_CONFIDENCE, req.query,
                f"confidence={identity.confidence}",
            )
            continue

        identities.append(identity)
        summary.artists_resolved += 1
        try:
            releases.extend(provider.get_releases(identity))
        except errors.DiscoveryError as exc:
            reporter.log.warning("Release fetch failed for %s: %s",
                                 identity.resolved_name, exc)
            cache.record_error(errors.DISCOVERY_API_ERROR, identity.resolved_name, str(exc))

    # Persist only the discovered (non-manual) releases under the fingerprint;
    # manual releases are appended afterwards so they are never cached against
    # the wrong input.
    if config.discovery_cache:
        cache.save(identities, releases, fingerprint)

    combined = releases + manual
    summary.releases_found = len(combined)
    return combined


# ── Phase 5+6: download a single job (used by the worker pool) ───────────────
def _process_job(
    job,
    config: AppConfig,
    downloader: Downloader,
    storage: StorageManager,
    metadata: MetadataProcessor,
    reporter: Reporter,
    state: JobState,
):
    reporter.job_started(job)
    running = job.with_status("running")
    state.append_event(running)

    workspace = storage.prepare_job_workspace(job)
    result = downloader.download(job, workspace)
    reporter.job_finished(job, result)

    if not result.success:
        record = reporter.record_failed_job(job, result, result.error_category or
                                             errors.YT_DLP_ERROR)
        failed = job.with_status("failed")
        state.append_event(failed)
        return failed, record

    # Postprocessing (Phase 6).
    try:
        final_dir = storage.finalize_job(job, result)
        metadata.process_release_folder(final_dir, job.artist_name)
        storage.cleanup_job(job)
    except Exception as exc:  # noqa: BLE001
        category = (
            errors.POSTPROCESS_ERROR
            if "audio" in str(exc).lower() or "temporary" in str(exc).lower()
            else errors.FILESYSTEM_ERROR
        )
        record = reporter.record_failed_job(job, result, category)
        reporter.log.warning("  postprocess failed: %s", exc)
        failed = job.with_status("failed")
        state.append_event(failed)
        return failed, record

    done = job.with_status("done")
    state.append_event(done)
    state.mark_release_complete(done)
    return done, None


# ── Main ─────────────────────────────────────────────────────────────────--
def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = build_config(args)

    try:
        warnings = validate_config(config)
    except errors.ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    setup_logging(config)
    reporter = Reporter(config)
    for w in warnings:
        reporter.log.warning("Warning: %s", w)

    summary = RunSummary(
        started_at=utils.utc_now_iso(),
        cookie_mode=config.cookie_mode,
        download_workers=config.download_workers,
    )

    cache = DiscoveryCache(config.cache_dir)
    state = JobState(config.state_dir)
    planner = Planner(config.output_dir, completed_job_ids=state.completed_job_ids())

    # Phase 3 (guard the input/discovery boundary so bad input is a clean exit).
    try:
        releases = run_discovery(config, reporter, cache, summary)
    except errors.InputError as exc:
        reporter.log.error("Input error: %s", exc)
        return 2
    except errors.DiscoveryError as exc:
        reporter.log.error("Discovery error: %s", exc)
        return 1

    # Phase 4 (resume-aware).
    existing = state.load_jobs()
    jobs = planner.create_jobs(releases, existing_jobs=existing)
    state.save_jobs(jobs)
    summary.jobs_created = len(jobs)

    pending = [j for j in jobs if j.status == "pending"]
    summary.jobs_skipped = sum(1 for j in jobs if j.status == "skipped")
    summary.jobs_done = sum(1 for j in jobs if j.status == "done")

    reporter.log.info(
        "Plan: %d jobs (%d pending, %d already done, %d skipped).",
        len(jobs), len(pending), summary.jobs_done, summary.jobs_skipped,
    )

    if config.dry_run:
        reporter.log.info("Dry run — no downloads performed. Planned releases:")
        for j in jobs:
            reporter.log.info("  [%s] %s — %s", j.status, j.artist_name, j.release_title)
        summary.finished_at = utils.utc_now_iso()
        reporter.write_summary(summary)
        return 0

    downloader = Downloader(config, build_cookie_provider(config))
    storage = StorageManager(config.work_dir, config.output_dir, config.conflict_policy)
    metadata = MetadataProcessor(enabled=config.metadata_patch)

    final_jobs = {j.job_id: j for j in jobs}

    # Incremental scheduling: keep at most `workers` jobs in flight so that on a
    # --fail-fast failure we can stop submitting the remaining queue. Note this
    # cancels not-yet-started jobs; jobs already running finish naturally (we do
    # not kill live yt-dlp subprocesses).
    try:
        _run_jobs(config, pending, final_jobs, summary,
                  downloader, storage, metadata, reporter, state)
    except Exception as exc:  # noqa: BLE001 - last-resort guard around the pool
        reporter.log.error("Unexpected error during downloads: %s", exc)

    state.save_jobs([final_jobs[k] for k in sorted(final_jobs)])
    summary.finished_at = utils.utc_now_iso()
    reporter.write_summary(summary)
    reporter.print_final(summary)
    return 1 if summary.jobs_failed and config.fail_fast else 0


def _run_jobs(
    config: AppConfig,
    pending: list,
    final_jobs: dict,
    summary: RunSummary,
    downloader: Downloader,
    storage: StorageManager,
    metadata: MetadataProcessor,
    reporter: Reporter,
    state: JobState,
) -> None:
    queue = list(pending)
    idx = 0
    stop = False
    with ThreadPoolExecutor(max_workers=config.download_workers) as pool:
        in_flight = {}
        # Prime the pool.
        while idx < len(queue) and len(in_flight) < config.download_workers:
            j = queue[idx]
            in_flight[pool.submit(_process_job, j, config, downloader, storage,
                                  metadata, reporter, state)] = j
            idx += 1

        while in_flight:
            done_futures = [f for f in as_completed(list(in_flight))]
            for fut in done_futures:
                in_flight.pop(fut, None)
                updated, _failure = fut.result()
                final_jobs[updated.job_id] = updated
                if updated.status == "done":
                    summary.jobs_done += 1
                elif updated.status == "failed":
                    summary.jobs_failed += 1
                    if config.fail_fast and not stop:
                        stop = True
                        reporter.log.warning(
                            "--fail-fast: not scheduling remaining jobs."
                        )
                # Refill unless we've been told to stop scheduling.
                if not stop and idx < len(queue):
                    j = queue[idx]
                    in_flight[pool.submit(_process_job, j, config, downloader,
                                          storage, metadata, reporter, state)] = j
                    idx += 1
            if stop:
                break


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
