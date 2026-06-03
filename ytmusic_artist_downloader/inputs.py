"""Input layer (Phase 2).

Normalises raw input lines into :class:`ArtistRequest` / :class:`ReleaseRequest`
objects. Supports three modes from the spec:

1. ``Artist Name``
2. ``Artist Name, https://music.youtube.com/channel/...`` or ``UC...``
3. ``Artist Name, https://music.youtube.com/browse/...`` or ``MPRE...``

Lines starting with ``#`` and blank lines are ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import InputError
from .models import ArtistRequest, ReleaseRequest
from . import utils

# Channel/browse-ID shapes used by YouTube Music.
_CHANNEL_ID_RE = re.compile(r"^(UC|MPLA)[A-Za-z0-9_-]{10,}$")
_RELEASE_ID_RE = re.compile(r"^(MPRE|OLAK5uy_)[A-Za-z0-9_-]+$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _looks_like_release(value: str) -> bool:
    if _RELEASE_ID_RE.match(value):
        return True
    if _URL_RE.match(value) and ("/browse/" in value or "/playlist" in value
                                 or "list=" in value or "OLAK5uy_" in value):
        return True
    return False


def _looks_like_channel(value: str) -> bool:
    if _CHANNEL_ID_RE.match(value):
        return True
    if _URL_RE.match(value) and "/channel/" in value:
        return True
    return False


def parse_artist_line(line: str) -> ArtistRequest | ReleaseRequest | None:
    """Parse a single non-empty, non-comment line into a request object.

    Returns ``None`` for blank/comment lines.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if "," in stripped:
        name_part, _, value_part = stripped.partition(",")
        name = name_part.strip()
        value = value_part.strip()
        if not name:
            raise InputError(f"Missing artist name in line: {line!r}")

        if _looks_like_release(value):
            return ReleaseRequest(
                artist_name=name,
                release_url=utils.normalize_release_url(value),
                source="manual",
            )
        if _looks_like_channel(value):
            if _URL_RE.match(value):
                return ArtistRequest(query=name, provided_name=name, provided_url=value)
            return ArtistRequest(
                query=name, provided_name=name, provided_browse_id=value
            )
        # A comma but an unrecognised second field: treat whole as a name query
        # but keep the parsed name to be safe.
        return ArtistRequest(query=name, provided_name=name)

    # Single token: either a bare name, or a bare ID/URL.
    if _looks_like_release(stripped):
        # A bare release with no artist; use a placeholder artist name.
        return ReleaseRequest(
            artist_name="Unknown Artist",
            release_url=utils.normalize_release_url(stripped),
        )
    if _looks_like_channel(stripped):
        if _URL_RE.match(stripped):
            return ArtistRequest(query=stripped, provided_url=stripped)
        return ArtistRequest(query=stripped, provided_browse_id=stripped)

    return ArtistRequest(query=stripped)


def parse_artists_file(path: Path) -> tuple[list[ArtistRequest], list[ReleaseRequest]]:
    """Parse an artists file into artist requests and any inline release requests."""
    artists: list[ArtistRequest] = []
    releases: list[ReleaseRequest] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Could not read input file {path}: {exc}")

    for raw in text.splitlines():
        parsed = parse_artist_line(raw)
        if parsed is None:
            continue
        if isinstance(parsed, ReleaseRequest):
            releases.append(parsed)
        else:
            artists.append(parsed)
    return artists, releases


def parse_direct_releases_file(path: Path) -> list[ReleaseRequest]:
    """Parse a dedicated direct-releases file.

    Each line is ``Artist Name, URL`` or just ``URL``.
    """
    releases: list[ReleaseRequest] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Could not read direct-releases file {path}: {exc}")

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "," in stripped:
            name_part, _, url_part = stripped.partition(",")
            releases.append(
                ReleaseRequest(
                    artist_name=name_part.strip() or "Unknown Artist",
                    release_url=utils.normalize_release_url(url_part.strip()),
                    source="manual",
                )
            )
        else:
            releases.append(
                ReleaseRequest(
                    artist_name="Unknown Artist",
                    release_url=utils.normalize_release_url(stripped),
                )
            )
    return releases
