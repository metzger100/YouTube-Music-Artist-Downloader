from ytmusic_artist_downloader import errors
from ytmusic_artist_downloader.downloader import classify_error


def test_success_has_no_category():
    assert classify_error(0, "") == ""


def test_cookie_expired():
    assert classify_error(1, "ERROR: Sign in to confirm your age") == errors.COOKIE_EXPIRED


def test_rate_limited():
    assert classify_error(1, "HTTP Error 429: Too Many Requests") == errors.RATE_LIMITED


def test_po_token():
    assert classify_error(1, "po_token is required") == errors.PO_TOKEN_REQUIRED


def test_network_error():
    assert classify_error(1, "getaddrinfo failed") == errors.NETWORK_ERROR


def test_metadata_error():
    assert classify_error(1, "ffmpeg exited with code 1") == errors.METADATA_ERROR


def test_generic_yt_dlp_error():
    assert classify_error(1, "ERROR: something odd happened") == errors.YT_DLP_ERROR


def test_unknown_error():
    assert classify_error(1, "weird output with no keywords") == errors.UNKNOWN_ERROR


def test_all_categories_known():
    for code, text in [
        (1, "sign in"), (1, "429"), (1, "po_token"),
        (1, "timed out"), (1, "ffmpeg"), (1, ".part incomplete"),
        (1, "error"), (1, "noise"),
    ]:
        assert classify_error(code, text) in errors.DOWNLOAD_ERROR_CATEGORIES
