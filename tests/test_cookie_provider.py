import pytest

from ytmusic_artist_downloader.cookies import (
    NoCookieProvider,
    StaticCookieFileProvider,
)
from ytmusic_artist_downloader.errors import ConfigError


def test_no_cookie_provider_yields_no_args():
    assert NoCookieProvider().yt_dlp_args() == []


def test_static_cookie_provider_args(tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    provider = StaticCookieFileProvider(cookie)
    assert provider.yt_dlp_args() == ["--cookies", str(cookie)]


def test_static_cookie_provider_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        StaticCookieFileProvider(tmp_path / "nope.txt")


def test_static_cookie_provider_does_not_mutate_file(tmp_path):
    cookie = tmp_path / "cookies.txt"
    original = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tX\t1\n"
    cookie.write_text(original, encoding="utf-8")
    provider = StaticCookieFileProvider(cookie)
    provider.yt_dlp_args()
    provider.yt_dlp_args()
    assert cookie.read_text(encoding="utf-8") == original
