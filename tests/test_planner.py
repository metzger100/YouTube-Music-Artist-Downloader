from pathlib import Path

from ytmusic_artist_downloader.models import Release
from ytmusic_artist_downloader.planner import JobState, Planner
from ytmusic_artist_downloader.utils import make_job_id


def _release(title, url, artist="Artist", browse_id=""):
    return Release(
        artist_name=artist,
        title=title,
        release_type="album",
        browse_id=browse_id,
        url=url,
        source="ytmusicapi",
    )


def test_job_id_deterministic():
    a = make_job_id("Radiohead", "https://music.youtube.com/browse/MPRE1")
    b = make_job_id("radiohead", "https://music.youtube.com/browse/MPRE1/")
    assert a == b


def test_dedup_creates_one_job(tmp_path):
    planner = Planner(tmp_path / "music")
    rels = [
        _release("OK Computer", "https://music.youtube.com/browse/MPRE1"),
        _release("OK Computer", "https://music.youtube.com/browse/MPRE1?x=1"),
    ]
    jobs = planner.create_jobs(rels)
    assert len(jobs) == 1


def test_two_direct_olak_releases_create_two_jobs(tmp_path):
    planner = Planner(tmp_path / "music")
    releases = [
        _release("A", "https://music.youtube.com/playlist?list=OLAK5uy_a"),
        _release("B", "https://music.youtube.com/playlist?list=OLAK5uy_b"),
    ]
    jobs = planner.create_jobs(releases)
    assert len(jobs) == 2


def test_jobs_sorted_deterministically(tmp_path):
    planner = Planner(tmp_path / "music")
    rels = [
        _release("B", "https://music.youtube.com/browse/MPREB"),
        _release("A", "https://music.youtube.com/browse/MPREA"),
    ]
    jobs1 = planner.create_jobs(rels)
    jobs2 = planner.create_jobs(list(reversed(rels)))
    assert [j.job_id for j in jobs1] == [j.job_id for j in jobs2]


def test_existing_done_jobs_preserved(tmp_path):
    planner = Planner(tmp_path / "music")
    rels = [_release("X", "https://music.youtube.com/browse/MPREX")]
    first = planner.create_jobs(rels)
    done = [first[0].with_status("done")]
    second = planner.create_jobs(rels, existing_jobs=done)
    assert second[0].status == "done"


def test_completed_marker_skips(tmp_path):
    # A release recorded in the completed-releases marker is planned as done.
    state = JobState(tmp_path / "state")
    planner = Planner(tmp_path / "music")
    rels = [_release("Z", "https://music.youtube.com/browse/MPREZ", browse_id="MPREZ")]
    jobs = planner.create_jobs(rels)
    state.mark_release_complete(jobs[0])

    planner2 = Planner(tmp_path / "music", completed_job_ids=state.completed_job_ids())
    jobs2 = planner2.create_jobs(rels)
    assert jobs2[0].status == "done"


def test_job_state_roundtrip(tmp_path):
    state = JobState(tmp_path / "state")
    planner = Planner(tmp_path / "music")
    jobs = planner.create_jobs([_release("X", "https://music.youtube.com/browse/MPX")])
    state.save_jobs(jobs)
    loaded = state.load_jobs()
    assert len(loaded) == 1
    assert loaded[0].job_id == jobs[0].job_id
