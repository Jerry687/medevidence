"""Root-scoped immutable publication for M1A raw and journal artifacts."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final, Literal
from uuid import uuid4

from medevidence.domain.identifiers import Sha256Digest

PERSISTENT_FILE_CAPACITY: Final = 1_214
PERSISTENT_WITH_LOCK_CAPACITY: Final = 1_215
TEMPORARY_FILE_PEAK_CAPACITY: Final = 1_216
COMMITTED_BYTE_CAPACITY: Final = 8_425_963_520
TEMPORARY_PEAK_BYTE_CAPACITY: Final = 12_720_930_816
RAW_RUN_BYTE_CAPACITY: Final = 529_530_880
RAW_RESPONSE_BYTE_CAPACITY: Final = 5_242_880
INITIAL_FREE_SPACE_FLOOR_BYTES: Final = 13_958_643_712
PER_WRITE_FREE_SPACE_RESERVE_BYTES: Final = 1_073_741_824
ROOT_LOCK_FILENAME: Final = ".m1a-constrained-v1.lock"
TEMP_PREFIX: Final = ".m1a-incomplete-"

type ArtifactClass = Literal["raw", "journal", "manifest"]


class SnapshotError(RuntimeError):
    """Base immutable-publication error."""


class SnapshotBusyError(SnapshotError):
    """The caller does not own the configured root writer lock."""


class SnapshotCapacityError(SnapshotError):
    """The frozen storage-capacity policy cannot admit a publication."""


class SnapshotIntegrityError(SnapshotError):
    """Existing or newly written bytes fail their exact identity."""


class SnapshotContainmentError(SnapshotError):
    """A path escapes the configured root or crosses a reparse point."""


@dataclass(frozen=True, slots=True)
class PublishedFile:
    """Verified result of one root-scoped immutable publication."""

    path: Path
    byte_size: int
    sha256_hex: str
    reused_existing: bool


@dataclass(frozen=True, slots=True)
class SnapshotWrite:
    """Verified result of an immutable raw-body publication."""

    artifact_id: Sha256Digest
    path: Path
    byte_size: int
    reused_existing: bool


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    """Non-destructive bounded observation of one exact journal directory."""

    directory: Path
    incomplete_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _Ledger:
    committed_files: int
    committed_bytes: int
    raw_bytes: int
    temporary_files: int
    temporary_bytes: int


def _default_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


class SnapshotStore:
    """One-writer immutable store with fail-closed on-disk capacity accounting."""

    def __init__(
        self,
        root: Path,
        *,
        free_bytes: Callable[[Path], int] = _default_free_bytes,
        committed_bytes: Callable[[], int] | None = None,
        committed_files: Callable[[], int] | None = None,
        raw_bytes: Callable[[], int] | None = None,
    ) -> None:
        self.root = root.absolute()
        self._free_bytes = free_bytes
        self._committed_bytes_probe = committed_bytes
        self._committed_files_probe = committed_files
        self._raw_bytes_probe = raw_bytes
        self._lock_handle: BinaryIO | None = None
        self._initialized = False

    @property
    def has_writer_lock(self) -> bool:
        """Return whether this instance owns the root writer lock."""

        return self._lock_handle is not None

    def initialize(self) -> None:
        """Admit a new root once and validate an existing root without re-flooring."""

        self.root.mkdir(parents=True, exist_ok=True)
        self._require_safe_path(self.root, allow_missing_leaf=False)
        lock_path = self.root / ROOT_LOCK_FILENAME
        self._require_safe_path(lock_path, allow_missing_leaf=True)
        first_admission = not lock_path.exists()
        if first_admission and self._free_bytes(self.root) < INITIAL_FREE_SPACE_FLOOR_BYTES:
            raise SnapshotCapacityError("snapshot root has less than the frozen 13 GiB floor")
        if first_admission:
            try:
                with lock_path.open("xb"):
                    pass
            except FileExistsError:
                pass
        self._require_safe_path(lock_path, allow_missing_leaf=False)
        if not lock_path.is_file() or lock_path.stat().st_size != 0:
            raise SnapshotIntegrityError("root writer lock must be a zero-byte regular file")
        self._initialized = True

    @contextmanager
    def writer(self) -> Iterator[SnapshotStore]:
        """Acquire the root-scoped nonblocking writer lock."""

        if not self._initialized:
            self.initialize()
        self._acquire_lock()
        try:
            yield self
        finally:
            self._release_lock()

    def publish_bytes(
        self,
        relative_path: str,
        data: bytes,
        *,
        artifact_class: ArtifactClass,
    ) -> PublishedFile:
        """Atomically publish exact bytes through the shared root safety gate."""

        self._require_writer()
        normalized = self._validated_relative_path(relative_path)
        target = self.root.joinpath(*normalized.parts)
        self._ensure_safe_parent(target.parent)
        self._require_safe_path(target, allow_missing_leaf=True)
        digest = sha256(data).hexdigest()
        if target.exists():
            self._verify_file(target, digest, len(data))
            return PublishedFile(target, len(data), digest, True)

        self._admit_write(len(data), artifact_class=artifact_class)
        temporary = target.parent / f"{TEMP_PREFIX}{digest}-{uuid4().hex}.tmp"
        self._require_safe_path(temporary, allow_missing_leaf=True)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._require_safe_path(temporary, allow_missing_leaf=False)
            self._verify_file(temporary, digest, len(data))
            self._require_safe_path(target, allow_missing_leaf=True)
            try:
                os.link(temporary, target)
            except FileExistsError:
                self._require_safe_path(target, allow_missing_leaf=False)
                self._verify_file(target, digest, len(data))
                return PublishedFile(target, len(data), digest, True)
            self._require_safe_path(target, allow_missing_leaf=False)
            self._verify_file(target, digest, len(data))
            return PublishedFile(target, len(data), digest, False)
        finally:
            if temporary.exists():
                self._require_safe_path(temporary, allow_missing_leaf=False)
                temporary.unlink()

    def store_raw_body(self, body: bytes) -> SnapshotWrite:
        """Publish one exact bounded PubMed response body."""

        if len(body) > RAW_RESPONSE_BYTE_CAPACITY:
            raise SnapshotCapacityError("raw response exceeds 5,242,880 bytes")
        digest = sha256(body).hexdigest()
        relative = f"pubmed/sha256/{digest[:2]}/{digest}.bin"
        published = self.publish_bytes(relative, body, artifact_class="raw")
        return SnapshotWrite(
            artifact_id=f"sha256:{digest}",
            path=published.path,
            byte_size=published.byte_size,
            reused_existing=published.reused_existing,
        )

    def verify(self, artifact_id: Sha256Digest) -> Path:
        """Verify and return the exact content-addressed raw-body path."""

        digest = artifact_id.removeprefix("sha256:")
        relative = f"pubmed/sha256/{digest[:2]}/{digest}.bin"
        target = self.root.joinpath(*PurePosixPath(relative).parts)
        self._require_safe_path(target, allow_missing_leaf=False)
        if not target.is_file():
            raise SnapshotIntegrityError("snapshot file is missing")
        self._verify_file(target, digest, target.stat().st_size)
        return target

    def observe_recovery(self, exact_directory: Path) -> RecoveryObservation:
        """Observe one exact contained directory without parsing incomplete bytes."""

        directory = exact_directory.absolute()
        self._require_safe_path(directory, allow_missing_leaf=False)
        if not directory.is_dir():
            raise SnapshotContainmentError("recovery target must be one exact directory")
        incomplete: list[Path] = []
        for path in directory.iterdir():
            if _is_reparse(path):
                raise SnapshotContainmentError("recovery entry is a symlink or reparse point")
            if path.is_file() and path.name.startswith(TEMP_PREFIX):
                incomplete.append(path)
        return RecoveryObservation(directory, tuple(sorted(incomplete)))

    def _admit_write(self, size: int, *, artifact_class: ArtifactClass) -> None:
        ledger = self._ledger()
        if ledger.committed_files + 1 > PERSISTENT_FILE_CAPACITY:
            raise SnapshotCapacityError("write exceeds the frozen persistent-file ceiling")
        if ledger.committed_files + 2 > PERSISTENT_WITH_LOCK_CAPACITY:
            raise SnapshotCapacityError("write exceeds the frozen persistent-with-lock ceiling")
        if ledger.committed_files + ledger.temporary_files + 3 > TEMPORARY_FILE_PEAK_CAPACITY:
            raise SnapshotCapacityError("write exceeds the frozen lock/temp file peak")
        if ledger.committed_bytes + size > COMMITTED_BYTE_CAPACITY:
            raise SnapshotCapacityError("write exceeds the frozen committed-byte ceiling")
        if (
            ledger.committed_bytes + ledger.temporary_bytes + (2 * size)
            > TEMPORARY_PEAK_BYTE_CAPACITY
        ):
            raise SnapshotCapacityError("write exceeds the frozen temporary-byte peak")
        if artifact_class == "raw" and ledger.raw_bytes + size > RAW_RUN_BYTE_CAPACITY:
            raise SnapshotCapacityError("raw responses exceed the frozen run-raw byte ceiling")
        if self._free_bytes(self.root) < size + PER_WRITE_FREE_SPACE_RESERVE_BYTES:
            raise SnapshotCapacityError("write would consume the frozen 1 GiB reserve")

    def _ledger(self) -> _Ledger:
        scanned = self._scan_ledger()
        committed_files = (
            self._committed_files_probe()
            if self._committed_files_probe is not None
            else scanned.committed_files
        )
        committed_bytes = (
            self._committed_bytes_probe()
            if self._committed_bytes_probe is not None
            else scanned.committed_bytes
        )
        raw_bytes = (
            self._raw_bytes_probe() if self._raw_bytes_probe is not None else scanned.raw_bytes
        )
        if min(committed_files, committed_bytes, raw_bytes) < 0:
            raise SnapshotCapacityError("capacity probes must not return negative values")
        return _Ledger(
            committed_files,
            committed_bytes,
            raw_bytes,
            scanned.temporary_files,
            scanned.temporary_bytes,
        )

    def _scan_ledger(self) -> _Ledger:
        committed_files = 0
        committed_bytes = 0
        raw_bytes = 0
        temporary_files = 0
        temporary_bytes = 0
        if not self.root.exists():
            return _Ledger(0, 0, 0, 0, 0)
        for directory, names, filenames in os.walk(self.root, followlinks=False):
            directory_path = Path(directory)
            self._require_safe_path(directory_path, allow_missing_leaf=False)
            for name in names:
                child = directory_path / name
                if _is_reparse(child):
                    raise SnapshotContainmentError("ledger path crosses a reparse point")
            for filename in filenames:
                path = directory_path / filename
                self._require_safe_path(path, allow_missing_leaf=False)
                if filename == ROOT_LOCK_FILENAME:
                    continue
                if not path.is_file():
                    raise SnapshotContainmentError("ledger entry is not a regular file")
                size = path.stat().st_size
                if filename.startswith(TEMP_PREFIX):
                    temporary_files += 1
                    temporary_bytes += size
                    continue
                committed_files += 1
                committed_bytes += size
                relative = path.relative_to(self.root).as_posix()
                if (
                    relative.startswith("pubmed/sha256/")
                    and relative.endswith(".bin")
                    and len(PurePosixPath(relative).parts) == 4
                ):
                    raw_bytes += size
        return _Ledger(
            committed_files,
            committed_bytes,
            raw_bytes,
            temporary_files,
            temporary_bytes,
        )

    def _ensure_safe_parent(self, parent: Path) -> None:
        relative = parent.absolute().relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            self._require_safe_path(current, allow_missing_leaf=True)
            with suppress(FileExistsError):
                current.mkdir()
            self._require_safe_path(current, allow_missing_leaf=False)
            if not current.is_dir():
                raise SnapshotContainmentError("publication parent is not a directory")

    def _validated_relative_path(self, value: str) -> PurePosixPath:
        if "\\" in value:
            raise SnapshotContainmentError("store-relative paths must use POSIX separators")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise SnapshotContainmentError("invalid store-relative publication path")
        return path

    def _verify_file(self, path: Path, digest: str, expected_size: int) -> None:
        self._require_safe_path(path, allow_missing_leaf=False)
        if not path.is_file() or path.stat().st_size != expected_size:
            raise SnapshotIntegrityError("published file size or type is invalid")
        hasher = sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65_536), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise SnapshotIntegrityError("published bytes do not match content identity")

    def _require_safe_path(self, path: Path, *, allow_missing_leaf: bool) -> None:
        candidate = path.absolute()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise SnapshotContainmentError("path escapes configured snapshot root") from error
        if self.root.exists() and _is_reparse(self.root):
            raise SnapshotContainmentError("snapshot root is a symlink or reparse point")
        current = self.root
        for index, part in enumerate(candidate.relative_to(self.root).parts):
            current = current / part
            if not current.exists():
                if allow_missing_leaf:
                    break
                raise SnapshotContainmentError("required contained path is missing")
            if _is_reparse(current):
                raise SnapshotContainmentError("contained path crosses a symlink or reparse point")
            if index < len(candidate.relative_to(self.root).parts) - 1 and not current.is_dir():
                raise SnapshotContainmentError("contained parent is not a directory")

    def _require_writer(self) -> None:
        if self._lock_handle is None:
            raise SnapshotBusyError("immutable publication requires the root writer lock")

    def _acquire_lock(self) -> None:
        if self._lock_handle is not None:
            raise SnapshotBusyError("writer lock is already held by this store")
        lock_path = self.root / ROOT_LOCK_FILENAME
        self._require_safe_path(lock_path, allow_missing_leaf=False)
        handle = lock_path.open("r+b")
        try:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 0:
                raise SnapshotIntegrityError("root lock handle is not a zero-byte regular file")
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
        except OSError as error:
            handle.close()
            raise SnapshotBusyError("snapshot root already has a writer") from error
        except Exception:
            handle.close()
            raise
        self._lock_handle = handle

    def _release_lock(self) -> None:
        handle = self._lock_handle
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_UN,  # type: ignore[attr-defined]
                )
        finally:
            handle.close()
            self._lock_handle = None
