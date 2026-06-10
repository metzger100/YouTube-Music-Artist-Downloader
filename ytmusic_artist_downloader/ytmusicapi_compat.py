"""Compatibility helpers for ytmusicapi API/renderer changes.

The YouTube Music web API occasionally changes renderer shapes before
``ytmusicapi`` has caught up. Keep the workaround local and safe so discovery
can continue instead of requiring operators to patch site-packages from Docker.
"""

from __future__ import annotations

from typing import Any


def apply_ytmusicapi_compat_patches() -> None:
    """Apply small defensive monkey patches to ytmusicapi.

    Currently this guards ``parse_description_runs`` against artist description
    runs that contain a ``searchEndpoint`` (for example hashtag chips) instead
    of the older/expected ``urlEndpoint``. Older ytmusicapi versions raise while
    parsing those artist pages, causing release discovery to fail even though
    albums and singles are otherwise available.

    The patch is intentionally tolerant: it preserves description text and only
    adds a URL entry when YouTube supplied one. It is also idempotent.
    """

    try:
        import ytmusicapi.helpers as helpers  # type: ignore
    except Exception:  # pragma: no cover - ytmusicapi may not be installed
        return

    if getattr(helpers, "_ytmad_parse_description_runs_patched", False):
        return

    original = getattr(helpers, "parse_description_runs", None)
    if original is None:
        return

    def parse_description_runs(descriptionRunsList: Any | None):
        if not isinstance(descriptionRunsList, list):
            return "", []

        description_runs: list[dict[str, str]] = []
        description = ""

        for run in descriptionRunsList:
            if not isinstance(run, dict):
                continue

            text = run.get("text", "") or ""
            description += text

            nav_endpoint = run.get("navigationEndpoint") or {}
            if not isinstance(nav_endpoint, dict):
                nav_endpoint = {}
            url_endpoint = nav_endpoint.get("urlEndpoint") or {}
            if not isinstance(url_endpoint, dict):
                url_endpoint = {}
            url = url_endpoint.get("url")

            if url:
                description_runs.append({"text": text, "url": url})
            else:
                description_runs.append({"text": text})

        return description, description_runs

    helpers.parse_description_runs = parse_description_runs
    helpers._ytmad_parse_description_runs_patched = True
