# YouTube Music Artist Downloader

Discover an artist's albums and singles with [`ytmusicapi`](https://github.com/sigma67/ytmusicapi)
and download them with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp). The tool is
**resumable**, **conservative**, and **safe with existing files**.

There is **no Selenium, no ChromeDriver, and no live cookie refresh**. Browser
state is replaced with explicit input files, stable caches, resumable jobs, and
deliberately slow, stable download behavior.

## 1. Overview

The downloader runs as a pipeline with one owner per stage:

```
artists.txt ─▶ Input ─▶ Discovery (ytmusicapi) ─▶ Planning ─▶ Download (yt-dlp)
                                                                   │
                            Reporting ◀─ Postprocessing (move/metadata) ◀┘
```

Each release becomes a deterministic **job**. Jobs are recorded in `state/` so an
interrupted run can be resumed: completed jobs are skipped and failed jobs are
retried.

## 2. Installation

```bash
pip install ytmusicapi yt-dlp
pip install mutagen          # optional, enables album-artist tagging
# or, from this project:
pip install -e .
```

## 3. Requirements

- Python **3.10+**
- `yt-dlp` on your `PATH`
- `ffmpeg` on your `PATH` (required for audio extraction)
- `ytmusicapi` (discovery)
- `mutagen` (optional metadata patching)

## 4. Basic usage

```bash
python -m ytmusic_artist_downloader --artists artists.txt
```

This uses the safe defaults: no cookies, one download worker, two concurrent
fragments, discovery caching on, download archive on, merge-safe storage.

## 5. Input file formats

`artists.txt` accepts three line shapes. Blank lines and `#` comments are ignored.

```text
# 1. Plain artist name
Radiohead

# 2. Artist with a channel link or browse ID
Björk, https://music.youtube.com/channel/UCxxxxxxxxxxxx
Aphex Twin, UCxxxxxxxxxxxx

# 3. A direct album/release URL or release ID
Boards of Canada, https://music.youtube.com/browse/MPREb_xxxxxxxx
Some Artist, MPREb_xxxxxxxx
```

You can also pass a dedicated direct-release file:

```bash
python -m ytmusic_artist_downloader --direct-releases releases.txt
```

## 6. No-cookie default mode

By default **no cookies are used** for discovery or downloads (`--auth none`).
Most public catalog content downloads fine this way. Start here.

## 7. Optional cookie mode

If (and only if) downloads fail because authentication is genuinely required,
supply a **static** Netscape cookie file:

```bash
python -m ytmusic_artist_downloader \
  --artists artists.txt \
  --auth cookies \
  --cookies logincookies.txt
```

Rules: the cookie file must exist at startup, is treated as **read-only**, and is
**never overwritten**. No browser is launched and no refresh thread exists.
Jobs that fail due to bad/expired cookies are categorized `cookie_expired`.

> **Live cookie refresh is not supported by design.** If cookies expire, export
> a fresh file and re-run; the run resumes from where it stopped.

## 8. Long-running download strategy

Large discographies should run slowly and steadily. Keep concurrency low:

```bash
python -m ytmusic_artist_downloader \
  --artists artists.txt \
  --workers 1 \
  --concurrent-fragments 2
```

If YouTube/yt-dlp requires a temporary client, PO-token provider, or challenge
solver workaround, pass extra yt-dlp options without editing the package:

```bash
python -m ytmusic_artist_downloader \
  --artists artists.txt \
  --yt-dlp-args "--remote-components ejs:github" \
  --yt-dlp-args "--js-runtimes deno" \
  --yt-dlp-args "--extractor-args youtube:player_client=mweb"
```

Alternatively, repeat `--yt-dlp-arg` for one argv token at a time. For tokens that start with `-`, use the equals form, e.g. `--yt-dlp-arg=--extractor-args --yt-dlp-arg youtube:player_client=mweb`.

yt-dlp is invoked with exponential backoff (`--retry-sleep`), explicit pacing
(`--sleep-requests`, `--sleep-interval`, `--max-sleep-interval`), `--continue`,
and a download archive. It is **not** run with `--ignore-errors`: if yt-dlp
reports an `ERROR:` (e.g. a track is unavailable) the job is recorded as failed
rather than silently treated as a complete album.

## 9. Resume behavior

Release-level resume is driven by **the tool's own state**, not by yt-dlp's
download archive (which tracks individual tracks and is not a reliable
whole-release signal). State lives in:

- `state/jobs.json` — the deterministic plan and per-job status
- `state/completed-releases.jsonl` — a durable marker written only after a
  release passes postprocessing

On re-run:

- jobs marked `done`, or present in the completed-releases marker, are skipped
- previously failed jobs are retried
- partially downloaded files are continued (via yt-dlp `--continue`), never
  assumed complete

Just re-run the **same command** to resume. Add `--refresh-discovery` to ignore
the discovery cache and re-query `ytmusicapi`.

The discovery cache is **scoped to the artist input**: if `artists.txt` changes,
the cache is invalidated automatically so a previous run's releases are never
reused for a different input.

### A note on `--fail-fast`

`--fail-fast` means *stop scheduling further jobs after the first failure*. Jobs
that are already running finish naturally; their yt-dlp subprocesses are not
killed mid-download. Not-yet-started jobs are not scheduled. With `--workers 1`
this effectively stops after the failing job.

## 10. Troubleshooting

| Symptom | Likely category | What to do |
|---|---|---|
| "Sign in to confirm…" | `cookie_expired` | export a fresh cookie file, re-run with `--auth cookies` |
| HTTP 429 / too many requests | `rate_limited` | wait, lower `--workers`/`--concurrent-fragments`, re-run |
| "po_token required" | `po_token_required` | use a current yt-dlp PO-token/provider setup via `--yt-dlp-args`, keep concurrency low, re-run |
| name resolution / timeouts | `network_error` | check connectivity, re-run |
| ffmpeg/metadata errors | `metadata_error` | confirm `ffmpeg` is installed |
| leftover `.part`/`.webm` | `partial_download` | re-run; the job continues |

Failed jobs are recorded in `state/failed-jobs.jsonl` with the stderr log path.

## 11. Rate-limit guidance

Stability beats speed. Recommended maximums: **2 workers** and **4 concurrent
fragments**. Exceeding these prints:

```
Warning: High concurrency can trigger rate limits or account/session blocking.
```

Discovery is sequential and cached; downloads are mildly parallel at most.

## 12. Folder layout

```
music/                     # final library (never deleted by default)
  Artist Name/
    Album Name/
      01 - Track.m4a
work/                      # per-job scratch space (cleaned on success)
  job-<job_id>/
    downloads/
    logs/
cache/                     # discovery cache (artists.json, releases.json)
state/                     # jobs.json, failed-jobs.jsonl, summary.json, logs/
  completed-releases.jsonl # durable per-release completion markers (resume)
  downloaded-archive.txt   # yt-dlp track-level archive
```

Conflict policy controls what happens when a release already exists in `music/`:
`merge-safe` (default, never overwrites), `rename-new`, `rename-existing`,
`skip-existing`, `replace-existing`. Note `skip-existing` skips at the folder
level it first encounters (e.g. an existing artist folder), so prefer the
default `merge-safe` if you want per-file behavior.

Post-download album-artist tagging is on by default; disable it with
`--no-metadata-patch`. Tagging also requires the optional `mutagen` package and
is skipped silently if it is not installed.

## 13. Legal and account-risk warning

Downloading from YouTube Music may violate its Terms of Service and, in some
jurisdictions, copyright law. Using account cookies carries a risk of session or
account restriction. You are responsible for ensuring you have the right to
download any content. This tool does not bypass DRM or access restrictions and
makes no guarantee that YouTube's behavior will not change.

## 14. Examples

```bash
# Default safe run
python -m ytmusic_artist_downloader --artists artists.txt

# With static cookies
python -m ytmusic_artist_downloader \
  --artists artists.txt --auth cookies --cookies logincookies.txt

# Plan only, no downloads
python -m ytmusic_artist_downloader --artists artists.txt --dry-run

# Explicit conservative long run
python -m ytmusic_artist_downloader \
  --artists artists.txt --workers 1 --concurrent-fragments 2
```

## Development

```bash
pip install pytest
pytest          # parsing, matching, planning, cookies, command building,
                # storage conflicts, error classification
```

## Module map

| Module | Owns |
|---|---|
| `config.py` | CLI config, defaults, environment validation |
| `inputs.py` | parsing input files into request objects |
| `discovery.py` | `ytmusicapi` artist/release discovery + cache |
| `planner.py` | deterministic jobs, dedup, skip logic, job state |
| `cookies.py` | static cookie args (never mutates files) |
| `downloader.py` | yt-dlp command building, subprocess, error classes |
| `storage.py` | workspaces, safe moves, conflict policy |
| `metadata.py` | optional album-artist normalization |
| `reporting.py` | logs, summary JSON, console output |
| `errors.py` | error/failure category vocabulary |
| `utils.py` | normalization, IDs, atomic JSON I/O |


## 15. YouTube Music / ytmusicapi compatibility notes

Some YouTube Music artist pages expose description hashtag chips as
`searchEndpoint` objects instead of `urlEndpoint` objects. Older `ytmusicapi`
versions may raise while parsing those pages even though album and single data is
still available. This package applies a small compatibility shim before creating
the `YTMusic` discovery client so those description-only links are ignored rather
than aborting discovery.
