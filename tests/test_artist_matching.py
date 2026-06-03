from ytmusic_artist_downloader.discovery import best_match
from ytmusic_artist_downloader.utils import (
    normalize_name,
    normalize_url,
    string_similarity,
)


def test_normalize_name_strips_diacritics_and_case():
    assert normalize_name("Björk") == "bjork"
    assert normalize_name("  The   Beatles!! ") == "the beatles"


def test_string_similarity_exact():
    assert string_similarity("Radiohead", "radiohead") == 1.0


def test_string_similarity_close():
    assert string_similarity("Beatles", "The Beatles") > 0.5


def test_string_similarity_far():
    assert string_similarity("Radiohead", "Metallica") < 0.4


def test_best_match_picks_highest():
    candidates = [
        {"artist": "Radiohead Tribute", "browseId": "UC1"},
        {"artist": "Radiohead", "browseId": "UC2"},
        {"artist": "Coldplay", "browseId": "UC3"},
    ]
    match, score = best_match("Radiohead", candidates)
    assert match["browseId"] == "UC2"
    assert score == 1.0


def test_best_match_empty():
    match, score = best_match("Anything", [])
    assert match is None and score == 0.0


def test_normalize_url_dedup():
    a = "https://music.youtube.com/browse/MPREb_x?foo=1#bar"
    b = "https://www.youtube.com/browse/MPREb_x/"
    assert normalize_url(a) == normalize_url(b)


def test_playlist_list_id_preserved():
    a = normalize_url("https://music.youtube.com/playlist?list=OLAK5uy_a")
    b = normalize_url("https://music.youtube.com/playlist?list=OLAK5uy_b")
    assert a != b


def test_playlist_same_list_id_dedups():
    a = normalize_url("https://music.youtube.com/playlist?list=OLAK5uy_a&si=1")
    b = normalize_url("https://www.youtube.com/playlist?list=OLAK5uy_a")
    assert a == b


def test_playlist_urls_with_different_list_ids_have_different_job_ids():
    from ytmusic_artist_downloader.utils import make_job_id
    a = make_job_id("Artist", "https://music.youtube.com/playlist?list=OLAK5uy_a")
    b = make_job_id("Artist", "https://music.youtube.com/playlist?list=OLAK5uy_b")
    assert a != b
