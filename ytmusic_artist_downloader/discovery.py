"""Discovery owner (Phase 3 / Section 5.2).

Resolves artist names and collects releases via ``ytmusicapi`` (unauthenticated
by default). It never downloads anything and never touches yt-dlp cookies.

``ytmusicapi`` is imported lazily so the rest of the package (and the test
suite) can run without it installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

from . import utils
from .errors import DiscoveryError
from .ytmusicapi_compat import apply_ytmusicapi_compat_patches
from .models import (
    ArtistIdentity,
    ArtistRequest,
    Release,
    ReleaseRequest,
)

YTMUSIC_BROWSE_URL = "https://music.youtube.com/browse/{browse_id}"


class DiscoveryNoMatchError(DiscoveryError):
    """Raised when no artist candidate matches the query at all.

    Distinct from API/network failures so the reporter can categorise it as
    ``discovery_no_match`` rather than ``discovery_api_error``.
    """


class DiscoveryProvider(Protocol):
    def resolve_artist(self, request: ArtistRequest) -> ArtistIdentity: ...
    def get_releases(self, artist: ArtistIdentity) -> list[Release]: ...


# ── Pure matching logic (testable without network) ──────────────────────────
def best_match(
    requested_name: str,
    candidates: list[dict],
) -> tuple[Optional[dict], float]:
    """Pick the best candidate by normalised string similarity.

    ``candidates`` are dicts with at least an ``artist`` (or ``name``) key.
    Returns ``(candidate, confidence)`` or ``(None, 0.0)`` if empty.
    """
    best: Optional[dict] = None
    best_score = 0.0
    for cand in candidates:
        name = cand.get("artist") or cand.get("name") or cand.get("title") or ""
        score = utils.string_similarity(requested_name, name)
        if score > best_score:
            best_score = score
            best = cand
    return best, best_score


def release_url_for(release_id: str, fallback_url: str = "") -> str:
    """Build a YouTube Music URL for a release/playlist ID.

    Delegates to :func:`utils.normalize_release_url` so ``OLAK5uy_`` audio
    playlist IDs become /playlist?list= URLs while ``MPRE...`` browse IDs
    become /browse/ URLs.
    """
    if release_id:
        return utils.normalize_release_url(release_id)
    return fallback_url


class YTMusicDiscoveryProvider:
    """Concrete discovery provider backed by ``ytmusicapi``."""

    def __init__(self, confidence_threshold: float = 0.60):
        self.confidence_threshold = confidence_threshold
        self._client = None  # lazily constructed

    @property
    def client(self):
        if self._client is None:
            apply_ytmusicapi_compat_patches()
            try:
                from ytmusicapi import YTMusic  # type: ignore
            except ImportError as exc:  # pragma: no cover - env dependent
                raise DiscoveryError(
                    "ytmusicapi is not installed. Install it with "
                    "'pip install ytmusicapi'."
                ) from exc
            # Unauthenticated client (Section: default behaviour).
            self._client = YTMusic()
        return self._client

    # ── resolve_artist ──────────────────────────────────────────────────────
    def resolve_artist(self, request: ArtistRequest) -> ArtistIdentity:
        # Direct browse ID short-circuits search entirely.
        if request.provided_browse_id:
            return ArtistIdentity(
                requested_name=request.provided_name or request.query,
                resolved_name=request.provided_name or request.query,
                browse_id=request.provided_browse_id,
                confidence=1.0,
            )
        if request.provided_url and "/channel/" in request.provided_url:
            browse_id = request.provided_url.rstrip("/").rsplit("/", 1)[-1]
            return ArtistIdentity(
                requested_name=request.provided_name or request.query,
                resolved_name=request.provided_name or request.query,
                browse_id=browse_id,
                confidence=1.0,
            )

        try:
            results = self.client.search(request.query, filter="artists")
        except Exception as exc:  # noqa: BLE001 - external API surface
            raise DiscoveryError(f"Search failed for {request.query!r}: {exc}") from exc

        candidate, confidence = best_match(request.query, results or [])
        if candidate is None:
            raise DiscoveryNoMatchError(f"No artist match for {request.query!r}")

        return ArtistIdentity(
            requested_name=request.query,
            resolved_name=candidate.get("artist", request.query),
            browse_id=candidate.get("browseId", ""),
            confidence=round(confidence, 4),
        )

    # ── get_releases ──────────────────────────────────────────────────────--
    def get_releases(self, artist: ArtistIdentity) -> list[Release]:
        try:
            details = self.client.get_artist(artist.browse_id)
        except Exception as exc:  # noqa: BLE001
            raise DiscoveryError(
                f"Failed to fetch artist {artist.browse_id!r}: {exc}"
            ) from exc

        releases: list[Release] = []
        releases.extend(self._extract_section(artist, details, "albums", "album"))
        releases.extend(self._extract_section(artist, details, "singles", "single"))
        return _dedupe_releases(releases)

    def _extract_section(
        self, artist: ArtistIdentity, details: dict, key: str, release_type: str
    ) -> list[Release]:
        section = details.get(key) or {}
        items = section.get("results") or []
        # If the artist page only previews items, expand via the section browse.
        browse_id = section.get("browseId")
        params = section.get("params")
        if browse_id:
            try:
                expanded = self.client.get_artist_albums(browse_id, params)
                if expanded:
                    items = expanded
            except Exception:  # noqa: BLE001 - fall back to preview list
                pass

        out: list[Release] = []
        for item in items:
            rid = item.get("browseId") or item.get("audioPlaylistId") or ""
            title = item.get("title") or "Unknown"
            out.append(
                Release(
                    artist_name=artist.resolved_name,
                    title=title,
                    release_type=release_type,  # type: ignore[arg-type]
                    browse_id=rid,
                    url=release_url_for(rid),
                    source="ytmusicapi",
                )
            )
        return out


def manual_release(request: ReleaseRequest) -> Release:
    """Convert a direct ReleaseRequest into a Release without any API call."""
    url = utils.normalize_release_url(request.release_url)
    # Derive a stable id/title from the URL where possible.
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    if "list=" in url:
        tail = url.split("list=", 1)[-1].split("&", 1)[0]
    return Release(
        artist_name=request.artist_name,
        title=tail or "Manual Release",
        release_type="unknown",
        browse_id="",
        url=url,
        source="manual",
    )


def _dedupe_releases(releases: list[Release]) -> list[Release]:
    seen: set[str] = set()
    out: list[Release] = []
    for rel in releases:
        key = rel.browse_id or utils.normalize_url(rel.url)
        if key and key not in seen:
            seen.add(key)
            out.append(rel)
    return out


# ── Cache helpers ────────────────────────────────────────────────────────────
class DiscoveryCache:
    """Reads/writes the discovery cache files described in Phase 3.

    The cache is *scoped by an input fingerprint*: if the artist input changes
    between runs, :meth:`load_releases` returns nothing so the previous run's
    releases are never reused for a different input.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.artists_path = self.cache_dir / "artists.json"
        self.releases_path = self.cache_dir / "releases.json"
        self.errors_path = self.cache_dir / "discovery-errors.jsonl"

    def load_releases(self, fingerprint: str) -> list[Release]:
        """Return cached releases only if the stored fingerprint matches."""
        payload = utils.read_json(self.releases_path, default=None)
        if not isinstance(payload, dict):
            return []  # legacy/absent cache: treat as empty (safe)
        if payload.get("input_hash") != fingerprint:
            return []  # input changed: do not reuse
        return [Release.from_dict(r) for r in payload.get("releases", [])]

    def save(
        self,
        artists: list[ArtistIdentity],
        releases: list[Release],
        fingerprint: str,
    ) -> None:
        utils.write_json_atomic(
            self.artists_path,
            {
                "input_hash": fingerprint,
                "artists": [a.to_dict() for a in artists],
            },
        )
        utils.write_json_atomic(
            self.releases_path,
            {
                "input_hash": fingerprint,
                "artists": [a.resolved_name for a in artists],
                "releases": [r.to_dict() for r in releases],
            },
        )

    def record_error(self, category: str, query: str, message: str) -> None:
        utils.append_jsonl(
            self.errors_path,
            {
                "category": category,
                "query": query,
                "message": message,
                "created_at": utils.utc_now_iso(),
            },
        )
