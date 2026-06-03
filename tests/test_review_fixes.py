"""Regression tests covering the code-review fixes."""

from pathlib import Path

import pytest

from ytmusic_artist_downloader import errors, utils
from ytmusic_artist_downloader.config import AppConfig
from ytmusic_artist_downloader.cookies import NoCookieProvider
from ytmusic_artist_downloader.discovery import (
    DiscoveryCache,
    DiscoveryNoMatchError,
    YTMusicDiscoveryProvider,
    manual_release,
)
from ytmusic_artist_downloader.downloader import Downloader, build_command
from ytmusic_artist_downloader.inputs import parse_artist_line, parse_direct_releases_file
from ytmusic_artist_downloader.models import ArtistRequest, DownloadJob, Release, ReleaseRequest


# ── Fix #2: bare release IDs become full URLs ────────────────────────────────
def test_normalize_release_url_browse():
    assert utils.normalize_release_url("MPREb_xyz") == (
        "https://music.youtube.com/browse/MPREb_xyz"
    )


def test_normalize_release_url_playlist():
    assert utils.normalize_release_url("OLAK5uy_abc") == (
        "https://music.youtube.com/playlist?list=OLAK5uy_abc"
    )


def test_normalize_release_url_passthrough():
    url = "https://music.youtube.com/browse/MPREb_xyz"
    assert utils.normalize_release_url(url) == url


def test_input_parser_normalizes_release_id():
    req = parse_artist_line("Some Artist, MPREb_xyz")
    assert isinstance(req, ReleaseRequest)
    assert req.release_url.startswith("https://music.youtube.com/browse/")


def test_manual_release_has_full_url():
    rel = manual_release(ReleaseRequest(artist_name="A", release_url="MPREb_xyz"))
    assert rel.url.startswith("https://music.youtube.com/browse/")


def test_direct_releases_file_normalizes(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("Artist, MPREb_aaa\n", encoding="utf-8")
    rels = parse_direct_releases_file(p)
    assert rels[0].release_url.startswith("https://music.youtube.com/browse/")


# ── Fix #1: discovery cache is scoped by input fingerprint ───────────────────
def test_cache_rejected_when_input_changes(tmp_path):
    cache = DiscoveryCache(tmp_path / "cache")
    rel = Release("Radiohead", "OK Computer", "album", "MPRE1",
                  "https://music.youtube.com/browse/MPRE1", "ytmusicapi")
    fp_a = utils.input_fingerprint("Radiohead")
    cache.save([], [rel], fp_a)

    # Same input -> hit
    assert len(cache.load_releases(fp_a)) == 1
    # Different input -> miss (no stale reuse)
    fp_b = utils.input_fingerprint("Björk")
    assert cache.load_releases(fp_b) == []


# ── Fix #3: explicit sleep options present in the command ────────────────────
def _config(tmp_path):
    return AppConfig(
        input_file=tmp_path / "a.txt",
        output_dir=tmp_path / "music",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        work_dir=tmp_path / "work",
        cookie_mode="none",
        cookie_file=None,
        download_workers=1,
        concurrent_fragments=2,
        discovery_cache=True,
        fail_fast=False,
    )


def _job(tmp_path):
    return DownloadJob("id", "Artist", "Album", "album",
                       "https://music.youtube.com/browse/MPRE1", tmp_path / "music")


def test_command_has_sleep_options(tmp_path):
    cmd = build_command(_job(tmp_path), _config(tmp_path), NoCookieProvider(), tmp_path / "ws")
    assert "--sleep-requests" in cmd
    assert "--sleep-interval" in cmd
    assert "--max-sleep-interval" in cmd


def test_command_no_longer_ignores_errors(tmp_path):
    cmd = build_command(_job(tmp_path), _config(tmp_path), NoCookieProvider(), tmp_path / "ws")
    assert "--ignore-errors" not in cmd
    assert "--no-abort-on-error" in cmd


# ── Fix #4: false-success guard (ERROR: in stderr -> failure even on rc 0) ───
def test_error_in_stderr_marks_failure(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    dl = Downloader(cfg, NoCookieProvider())
    job = _job(tmp_path)
    ws = tmp_path / "ws"

    class FakeProc:
        stdout = "downloaded most tracks"
        stderr = "ERROR: track 3 unavailable"
        returncode = 0  # yt-dlp continued past the failure

    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeProc())
    result = dl.download(job, ws)
    assert result.success is False
    assert result.error_category in errors.DOWNLOAD_ERROR_CATEGORIES


def test_clean_success(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    dl = Downloader(cfg, NoCookieProvider())

    class FakeProc:
        stdout = "ok"
        stderr = ""
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeProc())
    result = dl.download(_job(tmp_path), tmp_path / "ws2")
    assert result.success is True
    assert result.error_category is None


# ── Fix #7: no-match raises a distinct exception ─────────────────────────────
def test_no_match_raises_distinct_error():
    provider = YTMusicDiscoveryProvider()

    class FakeClient:
        def search(self, query, filter=None):
            return []  # nothing found

    provider._client = FakeClient()
    with pytest.raises(DiscoveryNoMatchError):
        provider.resolve_artist(ArtistRequest(query="Nonexistent Band"))


# ── Remaining #1: fingerprint distinguishes same name, different browse ID ───
def _fp(artists):
    return utils.input_fingerprint(
        *[
            "|".join([a.query or "", a.provided_name or "",
                      a.provided_url or "", a.provided_browse_id or ""])
            for a in artists
        ]
    )


def test_fingerprint_differs_by_browse_id():
    a = [ArtistRequest(query="Artist", provided_browse_id="UCaaaaaaaaaaaa")]
    b = [ArtistRequest(query="Artist", provided_browse_id="UCbbbbbbbbbbbb")]
    assert _fp(a) != _fp(b)


def test_fingerprint_differs_by_url():
    a = [ArtistRequest(query="Artist", provided_url="https://music.youtube.com/channel/UCa")]
    b = [ArtistRequest(query="Artist", provided_url="https://music.youtube.com/channel/UCb")]
    assert _fp(a) != _fp(b)


def test_fingerprint_same_when_identical():
    a = [ArtistRequest(query="Artist", provided_browse_id="UCsame")]
    b = [ArtistRequest(query="Artist", provided_browse_id="UCsame")]
    assert _fp(a) == _fp(b)


# ── Remaining #2: OLAK5uy_ audio-playlist IDs map to playlist URLs ───────────
def test_release_url_for_audio_playlist():
    from ytmusic_artist_downloader.discovery import release_url_for
    assert release_url_for("OLAK5uy_abc") == (
        "https://music.youtube.com/playlist?list=OLAK5uy_abc"
    )


def test_release_url_for_browse_id():
    from ytmusic_artist_downloader.discovery import release_url_for
    assert release_url_for("MPREb_xyz") == (
        "https://music.youtube.com/browse/MPREb_xyz"
    )
