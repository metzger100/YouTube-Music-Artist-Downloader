"""Error types and stable error-category constants.

This module owns the vocabulary used to classify failures across the whole
pipeline. Every other module references these constants instead of inventing
its own ad-hoc strings, so reports and retries stay consistent.
"""

from __future__ import annotations


class DownloaderError(Exception):
    """Base class for all errors raised by this package."""


class ConfigError(DownloaderError):
    """Raised when configuration or environment validation fails."""


class InputError(DownloaderError):
    """Raised when an input file cannot be parsed."""


class DiscoveryError(DownloaderError):
    """Raised when artist/release discovery fails irrecoverably."""


class StorageError(DownloaderError):
    """Raised on unsafe or impossible filesystem operations."""


# ── Download-result error categories ────────────────────────────────────────
# These describe *why a yt-dlp invocation failed* (Phase 5 contract).
COOKIE_EXPIRED = "cookie_expired"
RATE_LIMITED = "rate_limited"
PO_TOKEN_REQUIRED = "po_token_required"
NETWORK_ERROR = "network_error"
METADATA_ERROR = "metadata_error"
PARTIAL_DOWNLOAD = "partial_download"
YT_DLP_ERROR = "yt_dlp_error"
UNKNOWN_ERROR = "unknown_error"

DOWNLOAD_ERROR_CATEGORIES = frozenset(
    {
        COOKIE_EXPIRED,
        RATE_LIMITED,
        PO_TOKEN_REQUIRED,
        NETWORK_ERROR,
        METADATA_ERROR,
        PARTIAL_DOWNLOAD,
        YT_DLP_ERROR,
        UNKNOWN_ERROR,
    }
)


# ── Job-level failure categories (Section 10) ───────────────────────────────
# These describe *why a job ended up in the failed-jobs file*. They are a
# superset of the download categories because discovery and postprocessing can
# also fail.
DISCOVERY_NO_MATCH = "discovery_no_match"
DISCOVERY_LOW_CONFIDENCE = "discovery_low_confidence"
DISCOVERY_API_ERROR = "discovery_api_error"
POSTPROCESS_ERROR = "postprocess_error"
FILESYSTEM_ERROR = "filesystem_error"

JOB_FAILURE_CATEGORIES = frozenset(
    DOWNLOAD_ERROR_CATEGORIES
    | {
        DISCOVERY_NO_MATCH,
        DISCOVERY_LOW_CONFIDENCE,
        DISCOVERY_API_ERROR,
        POSTPROCESS_ERROR,
        FILESYSTEM_ERROR,
    }
)
