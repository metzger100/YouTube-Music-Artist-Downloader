"""Pure, dependency-free helper functions.

Nothing in here does network I/O or subprocess work, which makes it trivially
testable and safe to import anywhere.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

# ── Name / URL normalisation ────────────────────────────────────────────────
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def strip_diacritics(text: str) -> str:
    """Remove accents/diacritics so 'Bjork' matches 'Björk'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Normalise an artist/release name for comparison and ID generation.

    Lower-cases, strips diacritics and punctuation, collapses whitespace.
    """
    if name is None:
        return ""
    text = strip_diacritics(name).lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    """Normalise a URL for deduplication.

    Drops the scheme's case, query params, fragments and trailing slashes, and
    collapses ``music.youtube.com``/``www.youtube.com`` host variants.
    """
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.netloc or "").lower()
    # Collapse YouTube host variants (music./www./m.) so the same release at a
    # different subdomain deduplicates to one identity.
    for prefix in ("music.", "www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    path = parsed.path.rstrip("/").lower()

    # For playlist URLs the release identity lives in the `list` query param
    # (e.g. ?list=OLAK5uy_...). Dropping it would collapse distinct playlists to
    # the same identity, so preserve it; all other query params are discarded.
    query = urllib.parse.parse_qs(parsed.query)
    if path == "/playlist" and query.get("list"):
        return f"{host}{path}?list={query['list'][0]}".lower()

    return f"{host}{path}".lower()


def string_similarity(a: str, b: str) -> float:
    """Return a 0..1 similarity ratio between two names (after normalisation)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


# ── Identity ─────────────────────────────────────────────────────────────────
def make_job_id(artist_name: str, release_url: str) -> str:
    """Deterministic job ID: sha256(normalized_artist + '|' + normalized_url)."""
    basis = f"{normalize_name(artist_name)}|{normalize_url(release_url)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_RELEASE_ID_PREFIXES = ("MPRE", "OLAK5uy_", "MPLA")
YTMUSIC_BROWSE_URL = "https://music.youtube.com/browse/{id}"
YTMUSIC_PLAYLIST_URL = "https://music.youtube.com/playlist?list={id}"


def normalize_release_url(value: str) -> str:
    """Turn a bare release/playlist ID into a full YouTube Music URL.

    ``MPRE...`` / ``MPLA...`` browse IDs become /browse/ URLs; ``OLAK5uy_...``
    audio-playlist IDs become /playlist?list= URLs. Already-formed URLs pass
    through unchanged.
    """
    value = (value or "").strip()
    if value.lower().startswith(("http://", "https://")):
        return value
    if value.startswith("OLAK5uy_"):
        return YTMUSIC_PLAYLIST_URL.format(id=value)
    if value.startswith(("MPRE", "MPLA")):
        return YTMUSIC_BROWSE_URL.format(id=value)
    return value


def input_fingerprint(*parts: str) -> str:
    """Stable hash of the input that produced a cache, so a changed input file
    invalidates the cache instead of silently reusing the wrong releases."""
    joined = "\n".join(normalize_name(p) for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ── Filesystem-safe names ────────────────────────────────────────────────────
_UNSAFE_FS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, *, max_len: int = 180) -> str:
    """Make a string safe to use as a single path component."""
    cleaned = _UNSAFE_FS_RE.sub("_", name).strip().strip(".")
    cleaned = _WS_RE.sub(" ", cleaned)
    if not cleaned:
        cleaned = "untitled"
    return cleaned[:max_len].rstrip()


# ── JSON / JSONL persistence (atomic where it matters) ───────────────────────
def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON via a temp file + atomic rename so readers never see a
    half-written file even if the process is killed mid-write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON record as a line. Append-only files are crash-friendly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except FileNotFoundError:
        return []
    return records


# ── Time ─────────────────────────────────────────────────────────────────────
def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def run_stamp() -> str:
    """Compact local timestamp for log file names: YYYYMMDD-HHMMSS."""
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def dedupe_preserve_order(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
