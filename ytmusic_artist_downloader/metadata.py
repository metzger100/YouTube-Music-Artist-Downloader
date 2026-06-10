"""Metadata owner (Section 5.7).

Optional, best-effort post-download metadata patching. It only inspects and
normalises tags on already-downloaded audio files; it never downloads,
discovers, or moves files. ``mutagen`` is imported lazily and any failure is
non-fatal (the rest of the run continues).
"""

from __future__ import annotations

from pathlib import Path

AUDIO_SUFFIXES = (".m4a", ".mp4", ".aac")


class MetadataProcessor:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def process_release_folder(self, folder: Path, artist_name: str) -> None:
        """Ensure album-artist is set so music libraries group releases right."""
        if not self.enabled:
            return
        try:
            from mutagen.easymp4 import EasyMP4  # type: ignore
        except ImportError:
            return  # mutagen optional; skip silently

        for path in Path(folder).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
                continue
            try:
                audio = EasyMP4(str(path))
                # Keep library grouping consistent with the filesystem layout:
                # the planned artist owns the release, even when YouTube/yt-dlp
                # reports a long per-track contributor list as albumartist.
                audio["albumartist"] = artist_name
                audio.save()
            except Exception:  # noqa: BLE001 - tagging is best-effort
                continue
