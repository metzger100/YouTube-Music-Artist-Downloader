"""Cookie owner (Section 5.4).

Generates yt-dlp cookie CLI arguments and validates that a static cookie file
exists. It NEVER launches a browser, refreshes, rewrites, or mutates cookie
files in any way. There is no Selenium, no ChromeDriver, no refresh thread.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .config import AppConfig
from .errors import ConfigError


@runtime_checkable
class CookieProvider(Protocol):
    def yt_dlp_args(self) -> list[str]: ...


class NoCookieProvider:
    """Default provider: contributes no cookie arguments at all."""

    def yt_dlp_args(self) -> list[str]:
        return []

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "NoCookieProvider()"


class StaticCookieFileProvider:
    """Reads cookie *configuration* only; treats the file as read-only."""

    def __init__(self, cookie_file: Path):
        cookie_file = Path(cookie_file)
        if not cookie_file.is_file():
            raise ConfigError(f"Cookie file not found: {cookie_file}")
        self.cookie_file = cookie_file

    def yt_dlp_args(self) -> list[str]:
        return ["--cookies", str(self.cookie_file)]

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"StaticCookieFileProvider({self.cookie_file!s})"


def build_cookie_provider(config: AppConfig) -> CookieProvider:
    """Factory selecting the provider implied by configuration."""
    if config.cookie_mode == "file":
        if not config.cookie_file:
            raise ConfigError("Cookie mode 'file' requires a cookie file path.")
        return StaticCookieFileProvider(config.cookie_file)
    return NoCookieProvider()
