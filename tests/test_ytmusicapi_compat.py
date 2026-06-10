from ytmusic_artist_downloader.ytmusicapi_compat import apply_ytmusicapi_compat_patches


def test_parse_description_runs_tolerates_search_endpoint():
    try:
        import ytmusicapi.helpers as helpers
    except ImportError:
        return

    apply_ytmusicapi_compat_patches()

    description, runs = helpers.parse_description_runs([
        {
            "text": "#pfwywh50",
            "navigationEndpoint": {
                "searchEndpoint": {"query": "#pfwywh50", "params": "agIoAQ%3D%3D"}
            },
        },
        {
            "text": " website",
            "navigationEndpoint": {"urlEndpoint": {"url": "https://example.com"}},
        },
    ])

    assert description == "#pfwywh50 website"
    assert runs[0] == {"text": "#pfwywh50"}
    assert runs[1] == {"text": " website", "url": "https://example.com"}
