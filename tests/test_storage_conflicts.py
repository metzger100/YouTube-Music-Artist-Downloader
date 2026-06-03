import pytest

from ytmusic_artist_downloader.errors import StorageError
from ytmusic_artist_downloader.models import DownloadJob
from ytmusic_artist_downloader.storage import StorageManager


def _job(tmp_path, job_id="job1"):
    return DownloadJob(
        job_id=job_id,
        artist_name="Artist",
        release_title="Album",
        release_type="album",
        release_url="https://music.youtube.com/browse/MPRE1",
        output_root=tmp_path / "music",
    )


def _populate(ws, artist="Artist", album="Album", track="01 - Song.m4a"):
    d = ws / "downloads" / artist / album
    d.mkdir(parents=True, exist_ok=True)
    (d / track).write_text("audio", encoding="utf-8")
    return d


def test_invalid_policy_rejected(tmp_path):
    with pytest.raises(StorageError):
        StorageManager(tmp_path / "work", tmp_path / "music", "destroy-everything")


def test_finalize_moves_audio(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music")
    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    _populate(ws)
    sm.finalize_job(job, result=None)
    assert (tmp_path / "music" / "Artist" / "Album" / "01 - Song.m4a").is_file()


def test_partial_file_blocks_finalize(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music")
    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    d = _populate(ws)
    (d / "01 - Song.m4a.part").write_text("incomplete", encoding="utf-8")
    with pytest.raises(StorageError):
        sm.finalize_job(job, result=None)


def test_no_audio_blocks_finalize(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music")
    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    d = ws / "downloads" / "Artist" / "Album"
    d.mkdir(parents=True)
    (d / "cover.webp").write_text("img", encoding="utf-8")
    # leftover webp is itself a partial marker -> StorageError
    with pytest.raises(StorageError):
        sm.finalize_job(job, result=None)


def test_merge_safe_never_overwrites(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music", "merge-safe")
    # pre-existing file in final location
    existing = tmp_path / "music" / "Artist" / "Album" / "01 - Song.m4a"
    existing.parent.mkdir(parents=True)
    existing.write_text("ORIGINAL", encoding="utf-8")

    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    _populate(ws)  # same path, content "audio"
    sm.finalize_job(job, result=None)

    # original must be untouched
    assert existing.read_text(encoding="utf-8") == "ORIGINAL"
    # new file kept under an alternate name
    alt = tmp_path / "music" / "Artist" / "Album" / "01 - Song (1).m4a"
    assert alt.is_file()


def test_skip_existing_keeps_original(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music", "skip-existing")
    existing = tmp_path / "music" / "Artist"
    existing.mkdir(parents=True)
    (existing / "marker.txt").write_text("keep", encoding="utf-8")

    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    _populate(ws)
    sm.finalize_job(job, result=None)
    # original Artist folder content preserved
    assert (existing / "marker.txt").read_text(encoding="utf-8") == "keep"


def test_cleanup_removes_workspace(tmp_path):
    sm = StorageManager(tmp_path / "work", tmp_path / "music")
    job = _job(tmp_path)
    ws = sm.prepare_job_workspace(job)
    assert ws.is_dir()
    sm.cleanup_job(job)
    assert not ws.exists()
