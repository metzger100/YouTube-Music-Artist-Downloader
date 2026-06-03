"""Immutable data contracts shared between layers.

These dataclasses are the stable contracts described in the specification.
Layers communicate only through these objects; no layer reaches into another
layer's internals. All of them are JSON-serialisable through ``to_dict`` so
that state, cache, and report files stay human-readable and resumable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

ReleaseType = Literal["album", "single", "ep", "unknown"]
ReleaseSource = Literal["ytmusicapi", "manual"]
JobStatus = Literal["pending", "running", "done", "failed", "skipped"]


def _json_safe(value: Any) -> Any:
    """Convert Path objects to strings recursively for JSON serialisation."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


# ── Input layer ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ArtistRequest:
    query: str
    provided_name: Optional[str] = None
    provided_url: Optional[str] = None
    provided_browse_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class ReleaseRequest:
    artist_name: str
    release_url: str
    source: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


# ── Discovery layer ───────────────────────────────────────────────────────--
@dataclass(frozen=True)
class ArtistIdentity:
    requested_name: str
    resolved_name: str
    browse_id: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(frozen=True)
class Release:
    artist_name: str
    title: str
    release_type: ReleaseType
    browse_id: str
    url: str
    source: ReleaseSource

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Release":
        return cls(
            artist_name=data["artist_name"],
            title=data["title"],
            release_type=data.get("release_type", "unknown"),
            browse_id=data.get("browse_id", ""),
            url=data["url"],
            source=data.get("source", "ytmusicapi"),
        )


# ── Planning layer ────────────────────────────────────────────────────────--
@dataclass(frozen=True)
class DownloadJob:
    job_id: str
    artist_name: str
    release_title: str
    release_type: str
    release_url: str
    output_root: Path
    status: JobStatus = "pending"

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadJob":
        return cls(
            job_id=data["job_id"],
            artist_name=data["artist_name"],
            release_title=data["release_title"],
            release_type=data.get("release_type", "unknown"),
            release_url=data["release_url"],
            output_root=Path(data["output_root"]),
            status=data.get("status", "pending"),
        )

    def with_status(self, status: JobStatus) -> "DownloadJob":
        """Return a copy with an updated status (dataclass is frozen)."""
        return DownloadJob(
            job_id=self.job_id,
            artist_name=self.artist_name,
            release_title=self.release_title,
            release_type=self.release_type,
            release_url=self.release_url,
            output_root=self.output_root,
            status=status,
        )


# ── Download layer ────────────────────────────────────────────────────────--
@dataclass(frozen=True)
class DownloadResult:
    job_id: str
    success: bool
    return_code: int
    stdout_log: Path
    stderr_log: Path
    output_dir: Optional[Path] = None
    error_category: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


# ── Reporting layer ───────────────────────────────────────────────────────--
@dataclass
class RunSummary:
    started_at: str = ""
    finished_at: str = ""
    artists_requested: int = 0
    artists_resolved: int = 0
    releases_found: int = 0
    jobs_created: int = 0
    jobs_done: int = 0
    jobs_failed: int = 0
    jobs_skipped: int = 0
    cookie_mode: str = "none"
    download_workers: int = 1
    failed_jobs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = _json_safe(asdict(self))
        # failed_jobs is internal detail surfaced separately; keep summary clean
        data.pop("failed_jobs", None)
        return data
