from pathlib import Path

from ytmusic_artist_downloader.config import AppConfig
from ytmusic_artist_downloader.cookies import NoCookieProvider, StaticCookieFileProvider
from ytmusic_artist_downloader.downloader import build_command
from ytmusic_artist_downloader.models import DownloadJob


def _config(tmp_path, cookie_mode="none", cookie_file=None, yt_dlp_args=()):
    return AppConfig(
        input_file=tmp_path / "artists.txt",
        output_dir=tmp_path / "music",
        cache_dir=tmp_path / "cache",
        state_dir=tmp_path / "state",
        work_dir=tmp_path / "work",
        cookie_mode=cookie_mode,
        cookie_file=cookie_file,
        download_workers=1,
        concurrent_fragments=2,
        discovery_cache=True,
        fail_fast=False,
        yt_dlp_args=tuple(yt_dlp_args),
    )


def _job(tmp_path):
    return DownloadJob(
        job_id="abc",
        artist_name="Artist",
        release_title="Album",
        release_type="album",
        release_url="https://music.youtube.com/browse/MPRE1",
        output_root=tmp_path / "music",
    )


def test_command_includes_safe_defaults(tmp_path):
    cfg = _config(tmp_path)
    cmd = build_command(_job(tmp_path), cfg, NoCookieProvider(), tmp_path / "ws")
    assert cmd[0] == "yt-dlp"
    assert "--download-archive" in cmd
    assert "--continue" in cmd
    assert "--no-abort-on-error" in cmd
    assert "--extract-audio" in cmd
    assert "--concurrent-fragments" in cmd
    assert cmd[-1] == "https://music.youtube.com/browse/MPRE1"


def test_no_cookie_mode_has_no_cookie_args(tmp_path):
    cfg = _config(tmp_path)
    cmd = build_command(_job(tmp_path), cfg, NoCookieProvider(), tmp_path / "ws")
    assert "--cookies" not in cmd


def test_cookie_mode_passes_cookies(tmp_path):
    cookie = tmp_path / "c.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    cfg = _config(tmp_path, cookie_mode="file", cookie_file=cookie)
    provider = StaticCookieFileProvider(cookie)
    cmd = build_command(_job(tmp_path), cfg, provider, tmp_path / "ws")
    assert "--cookies" in cmd
    assert str(cookie) in cmd


def test_concurrent_fragments_value_propagates(tmp_path):
    cfg = _config(tmp_path)
    object.__setattr__(cfg, "concurrent_fragments", 4)
    cmd = build_command(_job(tmp_path), cfg, NoCookieProvider(), tmp_path / "ws")
    idx = cmd.index("--concurrent-fragments")
    assert cmd[idx + 1] == "4"


def test_extra_yt_dlp_args_are_passed_before_output_and_url(tmp_path):
    cfg = _config(
        tmp_path,
        yt_dlp_args=(
            "--remote-components",
            "ejs:github",
            "--extractor-args",
            "youtube:player_client=mweb",
        ),
    )
    cmd = build_command(_job(tmp_path), cfg, NoCookieProvider(), tmp_path / "ws")

    assert "--remote-components" in cmd
    assert "ejs:github" in cmd
    assert "--extractor-args" in cmd
    assert "youtube:player_client=mweb" in cmd
    assert cmd.index("youtube:player_client=mweb") < cmd.index("-o")
    assert cmd[-1] == "https://music.youtube.com/browse/MPRE1"
