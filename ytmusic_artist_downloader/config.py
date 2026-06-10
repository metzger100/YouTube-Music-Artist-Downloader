"""Configuration owner (Section 5.1).

Owns CLI-derived configuration, defaults, and *all* startup validation
(Phase 1). No network calls happen here. This module never downloads, never
discovers, never touches cookies beyond checking that a file exists.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from .errors import ConfigError

CookieMode = Literal["none", "file"]

# Concurrency policy (Section 9).
MAX_RECOMMENDED_WORKERS = 2
MAX_RECOMMENDED_FRAGMENTS = 4
MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class AppConfig:
    input_file: Path
    output_dir: Path
    cache_dir: Path
    state_dir: Path
    work_dir: Path
    cookie_mode: CookieMode
    cookie_file: Optional[Path]
    download_workers: int
    concurrent_fragments: int
    discovery_cache: bool
    fail_fast: bool
    # Extra knobs not in the minimal contract but needed by the lifecycle.
    direct_releases_file: Optional[Path] = None
    audio_format: str = "m4a"
    extract_audio: bool = True
    metadata_patch: bool = True
    conflict_policy: str = "merge-safe"
    allow_low_confidence: bool = False
    confidence_threshold: float = 0.60
    dry_run: bool = False
    refresh_discovery: bool = False
    verbose: bool = False
    yt_dlp_args: tuple[str, ...] = ()

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def download_archive(self) -> Path:
        return self.state_dir / "downloaded-archive.txt"


def build_config(args) -> AppConfig:
    """Translate parsed argparse namespace into an AppConfig.

    Pure translation only — validation lives in :func:`validate_config` so it
    can be invoked explicitly after construction.
    """
    cookie_mode: CookieMode = "file" if args.auth == "cookies" else "none"
    cookie_file = Path(args.cookies) if (cookie_mode == "file" and args.cookies) else None

    yt_dlp_args: list[str] = []
    for raw_args in getattr(args, "yt_dlp_args", []) or []:
        try:
            yt_dlp_args.extend(shlex.split(raw_args))
        except ValueError as exc:
            raise ConfigError(f"Invalid --yt-dlp-args value {raw_args!r}: {exc}") from exc
    yt_dlp_args.extend(getattr(args, "yt_dlp_arg", []) or [])

    return AppConfig(
        input_file=Path(args.artists) if args.artists else None,  # validated later
        direct_releases_file=Path(args.direct_releases) if args.direct_releases else None,
        output_dir=Path(args.output_dir),
        cache_dir=Path(args.cache_dir),
        state_dir=Path(args.state_dir),
        work_dir=Path(args.work_dir),
        cookie_mode=cookie_mode,
        cookie_file=cookie_file,
        download_workers=int(args.workers),
        concurrent_fragments=int(args.concurrent_fragments),
        discovery_cache=not args.refresh_discovery,
        fail_fast=bool(args.fail_fast),
        conflict_policy=args.conflict_policy,
        allow_low_confidence=bool(args.allow_low_confidence),
        dry_run=bool(args.dry_run),
        refresh_discovery=bool(args.refresh_discovery),
        verbose=bool(args.verbose),
        metadata_patch=not bool(getattr(args, "no_metadata_patch", False)),
        yt_dlp_args=tuple(yt_dlp_args),
    )


def _ensure_writable_dir(path: Path, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"{label} directory could not be created: {path} ({exc})")
    probe = path / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise ConfigError(f"{label} directory is not writable: {path} ({exc})")


def validate_config(config: AppConfig) -> list[str]:
    """Run all Phase-1 startup checks. Returns a list of non-fatal warnings.

    Fatal problems raise :class:`ConfigError`. No network call is made.
    """
    warnings: list[str] = []

    # Python version.
    if sys.version_info < MIN_PYTHON:
        raise ConfigError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info.major}.{sys.version_info.minor}"
        )

    # Required external command: yt-dlp. Skipped for dry-run, which only
    # exercises input/discovery/planning and downloads nothing.
    if not config.dry_run:
        if shutil.which("yt-dlp") is None:
            raise ConfigError("Required command 'yt-dlp' was not found on PATH.")

        # ffmpeg required only if audio extraction is enabled.
        if config.extract_audio and shutil.which("ffmpeg") is None:
            raise ConfigError(
                "ffmpeg is required for audio extraction but was not found on PATH."
            )

    # Input must exist (either an artists file or a direct-releases file).
    if not config.input_file and not config.direct_releases_file:
        raise ConfigError("No input provided: pass --artists and/or --direct-releases.")
    if config.input_file and not config.input_file.is_file():
        raise ConfigError(f"Artists input file not found: {config.input_file}")
    if config.direct_releases_file and not config.direct_releases_file.is_file():
        raise ConfigError(
            f"Direct-releases input file not found: {config.direct_releases_file}"
        )

    # Output / cache / state / work directories must be writable.
    _ensure_writable_dir(config.output_dir, "Output")
    _ensure_writable_dir(config.cache_dir, "Cache")
    _ensure_writable_dir(config.state_dir, "State")
    _ensure_writable_dir(config.work_dir, "Work")
    _ensure_writable_dir(config.logs_dir, "Logs")

    # Cookie file must exist only when cookie mode is enabled.
    if config.cookie_mode == "file":
        if not config.cookie_file:
            raise ConfigError("--auth cookies requires --cookies PATH.")
        if not config.cookie_file.is_file():
            raise ConfigError(f"Cookie file not found: {config.cookie_file}")

    # Concurrency policy warnings (Section 9).
    if config.download_workers > MAX_RECOMMENDED_WORKERS:
        warnings.append(
            "High concurrency can trigger rate limits or account/session "
            f"blocking (workers={config.download_workers} > "
            f"{MAX_RECOMMENDED_WORKERS})."
        )
    if config.concurrent_fragments > MAX_RECOMMENDED_FRAGMENTS:
        warnings.append(
            "High concurrency can trigger rate limits or account/session "
            f"blocking (concurrent-fragments={config.concurrent_fragments} > "
            f"{MAX_RECOMMENDED_FRAGMENTS})."
        )
    if config.download_workers < 1:
        raise ConfigError("--workers must be at least 1.")
    if config.concurrent_fragments < 1:
        raise ConfigError("--concurrent-fragments must be at least 1.")

    return warnings
