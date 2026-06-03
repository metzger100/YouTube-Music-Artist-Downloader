"""Storage owner (Phase 6 / Section 5.6).

Manages per-job workspaces, validates downloads, and moves finished releases
into the final music folder using a conflict policy that, by default, never
deletes or overwrites existing files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .errors import StorageError
from .models import DownloadJob, DownloadResult

# Files that indicate an incomplete or non-final download.
PARTIAL_SUFFIXES = (".part", ".ytdl", ".webm", ".webp", ".temp", ".tmp")

VALID_CONFLICT_POLICIES = frozenset(
    {"merge-safe", "rename-new", "rename-existing", "skip-existing", "replace-existing"}
)

AUDIO_SUFFIXES = (".m4a", ".mp3", ".opus", ".flac", ".ogg", ".aac", ".wav")


class StorageManager:
    def __init__(
        self,
        work_dir: Path,
        output_root: Path,
        conflict_policy: str = "merge-safe",
    ):
        if conflict_policy not in VALID_CONFLICT_POLICIES:
            raise StorageError(f"Unknown conflict policy: {conflict_policy}")
        self.work_dir = Path(work_dir)
        self.output_root = Path(output_root)
        self.conflict_policy = conflict_policy

    # ── workspace ─────────────────────────────────────────────────────────--
    def prepare_job_workspace(self, job: DownloadJob) -> Path:
        ws = self.work_dir / f"job-{job.job_id}"
        (ws / "downloads").mkdir(parents=True, exist_ok=True)
        (ws / "logs").mkdir(parents=True, exist_ok=True)
        return ws

    def workspace_for(self, job: DownloadJob) -> Path:
        return self.work_dir / f"job-{job.job_id}"

    # ── validation ─────────────────────────────────────────────────────────-
    def find_partial_files(self, folder: Path) -> list[Path]:
        return [
            p
            for p in Path(folder).rglob("*")
            if p.is_file() and p.suffix.lower() in PARTIAL_SUFFIXES
        ]

    def find_audio_files(self, folder: Path) -> list[Path]:
        return [
            p
            for p in Path(folder).rglob("*")
            if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
        ]

    # ── finalisation ─────────────────────────────────────────────────────--
    def finalize_job(self, job: DownloadJob, result: DownloadResult) -> Path:
        """Validate then move a finished job's files into the music folder.

        Raises :class:`StorageError` on partial downloads or missing audio so
        the caller records a failure rather than promoting a bad result.
        """
        downloads = self.workspace_for(job) / "downloads"
        if not downloads.is_dir():
            raise StorageError(f"No downloads directory for job {job.job_id}")

        partials = self.find_partial_files(downloads)
        if partials:
            raise StorageError(
                f"Leftover temporary files detected: "
                f"{', '.join(p.name for p in partials[:5])}"
            )

        audio = self.find_audio_files(downloads)
        if not audio:
            raise StorageError(f"No audio files produced for job {job.job_id}")

        self.output_root.mkdir(parents=True, exist_ok=True)
        moved_root: Path | None = None

        # The download template produces <artist>/<album>/... under downloads;
        # move each top-level entry into the final root with conflict handling.
        for entry in sorted(downloads.iterdir()):
            dest = self.output_root / entry.name
            final = self._move_with_policy(entry, dest)
            if moved_root is None:
                moved_root = final
        return moved_root or self.output_root

    def _move_with_policy(self, src: Path, dest: Path) -> Path:
        if not dest.exists():
            shutil.move(str(src), str(dest))
            return dest

        policy = self.conflict_policy
        if policy == "skip-existing":
            return dest  # leave existing untouched, drop the new copy
        if policy == "replace-existing":
            self._remove(dest)
            shutil.move(str(src), str(dest))
            return dest
        if policy == "rename-new":
            new_dest = self._next_available(dest)
            shutil.move(str(src), str(new_dest))
            return new_dest
        if policy == "rename-existing":
            backup = self._next_available(dest)
            shutil.move(str(dest), str(backup))
            shutil.move(str(src), str(dest))
            return dest
        # merge-safe (default): recurse; never delete or overwrite a file.
        return self._merge_safe(src, dest)

    def _merge_safe(self, src: Path, dest: Path) -> Path:
        if src.is_dir() and dest.is_dir():
            for child in sorted(src.iterdir()):
                self._move_with_policy(child, dest / child.name)
            # src directory is now drained of conflicts; remove if empty.
            try:
                src.rmdir()
            except OSError:
                pass
            return dest
        if src.is_file() and dest.exists():
            # Never overwrite: keep existing, place the new file under a new name.
            new_dest = self._next_available(dest)
            shutil.move(str(src), str(new_dest))
            return new_dest
        shutil.move(str(src), str(dest))
        return dest

    @staticmethod
    def _next_available(dest: Path) -> Path:
        if not dest.exists():
            return dest
        stem, suffix = dest.stem, dest.suffix
        parent = dest.parent
        n = 1
        while True:
            candidate = parent / f"{stem} ({n}){suffix}"
            if not candidate.exists():
                return candidate
            n += 1

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    # ── cleanup ───────────────────────────────────────────────────────────--
    def cleanup_job(self, job: DownloadJob) -> None:
        """Remove a successful job's workspace. Failed jobs are left in place."""
        ws = self.workspace_for(job)
        if ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
