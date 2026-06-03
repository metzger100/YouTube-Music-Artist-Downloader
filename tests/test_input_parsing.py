from ytmusic_artist_downloader.inputs import (
    parse_artist_line,
    parse_artists_file,
    parse_direct_releases_file,
)
from ytmusic_artist_downloader.models import ArtistRequest, ReleaseRequest


def test_plain_artist_name():
    req = parse_artist_line("Radiohead")
    assert isinstance(req, ArtistRequest)
    assert req.query == "Radiohead"
    assert req.provided_url is None and req.provided_browse_id is None


def test_blank_and_comment_lines_ignored():
    assert parse_artist_line("") is None
    assert parse_artist_line("   ") is None
    assert parse_artist_line("# a comment") is None


def test_artist_with_channel_url():
    req = parse_artist_line("Björk, https://music.youtube.com/channel/UC123abc456")
    assert isinstance(req, ArtistRequest)
    assert req.provided_name == "Björk"
    assert req.provided_url and "/channel/" in req.provided_url


def test_artist_with_bare_channel_id():
    req = parse_artist_line("Artist, UCabcdefghij12345")
    assert isinstance(req, ArtistRequest)
    assert req.provided_browse_id == "UCabcdefghij12345"


def test_release_url_becomes_release_request():
    req = parse_artist_line("Artist, https://music.youtube.com/browse/MPREb_abc123")
    assert isinstance(req, ReleaseRequest)
    assert req.artist_name == "Artist"
    assert req.source == "manual"


def test_bare_release_id():
    req = parse_artist_line("Some Artist, MPREb_xyz")
    assert isinstance(req, ReleaseRequest)


def test_parse_artists_file(tmp_path):
    p = tmp_path / "artists.txt"
    p.write_text(
        "Radiohead\n"
        "# comment\n"
        "\n"
        "Björk, https://music.youtube.com/channel/UCxyz0001234\n"
        "Aphex Twin, https://music.youtube.com/browse/MPREb_qqq\n",
        encoding="utf-8",
    )
    artists, releases = parse_artists_file(p)
    assert len(artists) == 2
    assert len(releases) == 1
    assert releases[0].artist_name == "Aphex Twin"


def test_parse_direct_releases_file(tmp_path):
    p = tmp_path / "releases.txt"
    p.write_text(
        "Boards of Canada, https://music.youtube.com/browse/MPREb_aaa\n"
        "https://music.youtube.com/browse/MPREb_bbb\n",
        encoding="utf-8",
    )
    releases = parse_direct_releases_file(p)
    assert len(releases) == 2
    assert releases[0].artist_name == "Boards of Canada"
    assert releases[1].artist_name == "Unknown Artist"
