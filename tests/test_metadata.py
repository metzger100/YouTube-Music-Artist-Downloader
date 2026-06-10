from pathlib import Path
import sys
import types

from ytmusic_artist_downloader.metadata import MetadataProcessor


def test_metadata_processor_overwrites_existing_albumartist(tmp_path, monkeypatch):
    audio_file = tmp_path / "Artist" / "Album" / "01 - Track.m4a"
    audio_file.parent.mkdir(parents=True)
    audio_file.write_text("audio", encoding="utf-8")

    saved = {}

    class FakeEasyMP4(dict):
        def __init__(self, path):
            super().__init__({"albumartist": ["Long Contributor List"]})
            self.path = path

        def save(self):
            saved["path"] = self.path
            saved["albumartist"] = self["albumartist"]

    fake_module = types.ModuleType("mutagen.easymp4")
    fake_module.EasyMP4 = FakeEasyMP4
    fake_pkg = types.ModuleType("mutagen")

    monkeypatch.setitem(sys.modules, "mutagen", fake_pkg)
    monkeypatch.setitem(sys.modules, "mutagen.easymp4", fake_module)

    MetadataProcessor(enabled=True).process_release_folder(tmp_path, "Mint Royale")

    assert saved["path"] == str(audio_file)
    assert saved["albumartist"] == "Mint Royale"
