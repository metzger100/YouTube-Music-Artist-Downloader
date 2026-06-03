"""Download owner (Phase 5 / Section 5.5).

Builds yt-dlp commands, runs them as subprocesses, captures logs, and
classifies failures. It treats yt-dlp as an opaque black box: it never opens a
browser, never mutates cookie files, and never performs discovery.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import errors
from .config import AppConfig
from .cookies import CookieProvider
from .models import DownloadJob, DownloadResult

# Safe default yt-dlp options (Phase 5). Concurrency-sensitive values are
# injected from config rather than hard-coded.
#
# Note: we deliberately do NOT pass --ignore-errors. With --ignore-errors,
# yt-dlp can skip failed tracks and still exit 0, producing a partial album
# that looks successful. --no-abort-on-error lets a playlist continue past one
# bad item, but the run still surfaces "ERROR:" lines, which the runner treats
# as a failure (see Downloader.download).
BASE_YT_DLP_OPTIONS = [
    "--continue",
    "--no-abort-on-error",
    "--retries", "10",
    "--fragment-retries", "10",
    "--retry-sleep", "http:exp=5:60",
    "--retry-sleep", "fragment:exp=5:60",
    # Between-request / between-download pacing for long-running stability.
    "--sleep-requests", "0.75",
    "--sleep-interval", "10",
    "--max-sleep-interval", "20",
    "--compat-options", "filename-sanitization",
]

AUDIO_OPTIONS = [
    "-f", "bestaudio/best",
    "--extract-audio",
    "--embed-metadata",
    "--add-metadata",
    "--embed-thumbnail",
]


def build_command(
    job: DownloadJob,
    config: AppConfig,
    cookie_provider: CookieProvider,
    workspace: Path,
) -> list[str]:
    """Construct the full yt-dlp argument vector for a job.

    The output template writes into the job's workspace; postprocessing moves
    finished files into the final music folder afterwards.
    """
    output_template = str(
        Path(workspace) / "%(album_artist,artist,uploader)s"
        / "%(album,playlist_title)s" / "%(track_number,playlist_index)02d - %(title)s.%(ext)s"
    )

    cmd: list[str] = ["yt-dlp"]
    cmd += BASE_YT_DLP_OPTIONS
    cmd += ["--download-archive", str(config.download_archive)]
    cmd += ["--concurrent-fragments", str(config.concurrent_fragments)]

    if config.extract_audio:
        cmd += AUDIO_OPTIONS
        cmd += ["--audio-format", config.audio_format]

    # Cookie args are appended only when a cookie provider supplies them.
    cmd += cookie_provider.yt_dlp_args()

    cmd += ["-o", output_template]
    cmd += [job.release_url]
    return cmd


# ── Error classification (testable, pure) ────────────────────────────────────
def classify_error(return_code: int, stderr_text: str) -> str:
    """Map a yt-dlp result to a stable error category."""
    text = (stderr_text or "").lower()

    if return_code == 0:
        return ""  # success has no category

    if any(s in text for s in ("sign in", "login required", "cookies", "account",
                               "this video is private", "members-only")):
        return errors.COOKIE_EXPIRED
    if any(s in text for s in ("429", "too many requests", "rate limit",
                               "rate-limit")):
        return errors.RATE_LIMITED
    if "po_token" in text or "po token" in text or "potoken" in text:
        return errors.PO_TOKEN_REQUIRED
    if any(s in text for s in ("getaddrinfo", "connection reset", "timed out",
                               "timeout", "temporary failure in name resolution",
                               "network is unreachable", "connection refused")):
        return errors.NETWORK_ERROR
    if any(s in text for s in ("ffmpeg", "postprocess", "thumbnail", "metadata")):
        return errors.METADATA_ERROR
    if any(s in text for s in (".part", "fragment", "incomplete")):
        return errors.PARTIAL_DOWNLOAD
    if "error" in text:
        return errors.YT_DLP_ERROR
    return errors.UNKNOWN_ERROR


class Downloader:
    """Runs yt-dlp subprocesses and returns structured results."""

    def __init__(self, config: AppConfig, cookie_provider: CookieProvider):
        self.config = config
        self.cookie_provider = cookie_provider

    def download(self, job: DownloadJob, workspace: Path) -> DownloadResult:
        workspace = Path(workspace)
        logs_dir = workspace / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = logs_dir / "yt-dlp.stdout.log"
        stderr_log = logs_dir / "yt-dlp.stderr.log"

        downloads_dir = workspace / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        cmd = build_command(job, self.config, self.cookie_provider, downloads_dir)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except FileNotFoundError as exc:
            stdout, stderr, rc = "", f"yt-dlp not executable: {exc}", 127
        except Exception as exc:  # noqa: BLE001
            stdout, stderr, rc = "", f"subprocess error: {exc}", 1

        stdout_log.write_text(stdout or "", encoding="utf-8")
        stderr_log.write_text(stderr or "", encoding="utf-8")

        # False-success guard: yt-dlp may continue past per-item failures and
        # still exit 0. If stderr reports any "ERROR:", treat the job as failed
        # so a partially downloaded release is never marked done.
        has_error_line = "error:" in (stderr or "").lower()
        success = rc == 0 and not has_error_line
        if success:
            category = None
        else:
            effective_rc = rc if rc != 0 else 1
            category = classify_error(effective_rc, stderr)

        return DownloadResult(
            job_id=job.job_id,
            success=success,
            return_code=rc,
            stdout_log=stdout_log,
            stderr_log=stderr_log,
            output_dir=downloads_dir if success else None,
            error_category=category,
        )
