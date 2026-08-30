"""Root-scoped immutable publication for M1A raw and journal artifacts."""

from __future__ import annotations

import os
import re
import shutil
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final, Literal, final
from uuid import uuid4

from medevidence.domain.identifiers import Sha256Digest

PERSISTENT_FILE_CAPACITY: Final = 1_232
PERSISTENT_WITH_LOCK_CAPACITY: Final = 1_233
TEMPORARY_FILE_PEAK_CAPACITY: Final = 1_234
COMMITTED_BYTE_CAPACITY: Final = 8_430_436_352
TEMPORARY_PEAK_BYTE_CAPACITY: Final = 12_725_403_648
RAW_RUN_BYTE_CAPACITY: Final = 529_530_880
RAW_RESPONSE_BYTE_CAPACITY: Final = 5_242_880
PUBMED_SEARCH_PROGRESS_BYTE_CAPACITY: Final = 16_384
PUBMED_TERMINAL_PROGRESS_BYTE_CAPACITY: Final = 262_144
SOURCE_REPLAY_RECORD_BYTE_CAPACITY: Final = 262_144
GENERATION_RECEIPT_BYTE_CAPACITY: Final = 65_536
INITIAL_FREE_SPACE_FLOOR_BYTES: Final = 13_958_643_712
PER_WRITE_FREE_SPACE_RESERVE_BYTES: Final = 1_073_741_824
ROOT_LOCK_FILENAME: Final = ".m1a-constrained-v1.lock"
TEMP_PREFIX: Final = ".m1a-incomplete-"
_RUN_ID_PATTERN: Final = re.compile(
    r"^run:([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$"
)
_SOURCE_TASK_ATTEMPT_PATTERN: Final = re.compile(r"^source-task-attempt:sha256:([0-9a-f]{64})$")
_GENERATION_RECEIPT_ID_PATTERN: Final = re.compile(r"^generation-receipt:sha256:([0-9a-f]{64})$")

type SourceReplayKind = Literal["dailymed-discovery", "dailymed-fetch", "faers-aggregate"]

_SOURCE_REPLAY_LAYOUT: Final[dict[SourceReplayKind, tuple[str, str]]] = {
    "dailymed-discovery": ("dailymed", "discovery"),
    "dailymed-fetch": ("dailymed", "fetch"),
    "faers-aggregate": ("faers", "aggregate"),
}
_SOURCE_REPLAY_RUN_CAPACITY: Final = {"dailymed": 8, "faers": 8}
_SOURCE_REPLAY_KEY_BYTE_CAPACITY: Final = 256

type ArtifactClass = Literal["raw", "journal", "manifest"]


type DailyMedSplValidator = Callable[[bytes, str, str], None]


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


@final
class SnapshotStore:
    """One-writer immutable store with fail-closed on-disk capacity accounting."""

    _authority_frozen: bool
    _committed_bytes_probe: Callable[[], int] | None
    _committed_files_probe: Callable[[], int] | None
    _dailymed_spl_validator: DailyMedSplValidator | None
    _free_bytes: Callable[[Path], int]
    _initialized: bool
    _lock_handle: BinaryIO | None
    _raw_bytes_probe: Callable[[], int] | None
    _root: Path

    __slots__ = (
        "_authority_frozen",
        "_committed_bytes_probe",
        "_committed_files_probe",
        "_dailymed_spl_validator",
        "_free_bytes",
        "_initialized",
        "_lock_handle",
        "_raw_bytes_probe",
        "_root",
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("SnapshotStore is a sealed concrete persistence authority")

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_authority_frozen", False):
            raise AttributeError("SnapshotStore authority is frozen after construction")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        root: Path,
        *,
        free_bytes: Callable[[Path], int] = _default_free_bytes,
        committed_bytes: Callable[[], int] | None = None,
        committed_files: Callable[[], int] | None = None,
        raw_bytes: Callable[[], int] | None = None,
        dailymed_spl_validator: DailyMedSplValidator | None = None,
    ) -> None:
        object.__setattr__(self, "_authority_frozen", False)
        object.__setattr__(self, "_root", root.absolute())
        object.__setattr__(self, "_free_bytes", free_bytes)
        object.__setattr__(self, "_committed_bytes_probe", committed_bytes)
        object.__setattr__(self, "_committed_files_probe", committed_files)
        object.__setattr__(self, "_raw_bytes_probe", raw_bytes)
        object.__setattr__(self, "_dailymed_spl_validator", dailymed_spl_validator)
        object.__setattr__(self, "_lock_handle", None)
        object.__setattr__(self, "_initialized", False)
        object.__setattr__(self, "_authority_frozen", True)

    @property
    def root(self) -> Path:
        """Return the exact absolute immutable snapshot root."""

        return self._root

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
        object.__setattr__(self, "_initialized", True)

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

    def read_pubmed_search_progress(self, run_id: str) -> bytes:
        """Read only the bounded immutable PubMed search-progress journal record."""

        match = _RUN_ID_PATTERN.fullmatch(run_id)
        if match is None:
            raise SnapshotContainmentError("invalid PubMed search-progress run identity")
        if not self._initialized:
            self.initialize()
        relative = f"journal/{match.group(1)}/acquisition-0000/search-progress.json"
        target = self.root.joinpath(*PurePosixPath(relative).parts)
        self._require_safe_path(target, allow_missing_leaf=True)
        if not target.is_file():
            raise SnapshotIntegrityError("PubMed search-progress record is missing")
        size = target.stat().st_size
        if size <= 0 or size > PUBMED_SEARCH_PROGRESS_BYTE_CAPACITY:
            raise SnapshotIntegrityError("PubMed search-progress record has invalid size")
        raw = target.read_bytes()
        self._require_safe_path(target, allow_missing_leaf=False)
        if len(raw) != size:
            raise SnapshotIntegrityError("PubMed search-progress record changed during read")
        return raw

    def read_pubmed_terminal_progress(self, run_id: str, attempt_id: str) -> bytes:
        """Read only one bounded immutable PubMed terminal replay receipt."""

        run_match = _RUN_ID_PATTERN.fullmatch(run_id)
        attempt_match = _SOURCE_TASK_ATTEMPT_PATTERN.fullmatch(attempt_id)
        if run_match is None or attempt_match is None:
            raise SnapshotContainmentError("invalid PubMed terminal-progress identity")
        if not self._initialized:
            self.initialize()
        relative = (
            f"journal/{run_match.group(1)}/orchestration/pubmed/"
            f"{attempt_match.group(1)}/terminal-progress.json"
        )
        target = self.root.joinpath(*PurePosixPath(relative).parts)
        self._require_safe_path(target, allow_missing_leaf=True)
        if not target.is_file():
            raise SnapshotIntegrityError("PubMed terminal-progress record is missing")
        size = target.stat().st_size
        if size <= 0 or size > PUBMED_TERMINAL_PROGRESS_BYTE_CAPACITY:
            raise SnapshotIntegrityError("PubMed terminal-progress record has invalid size")
        raw = target.read_bytes()
        self._require_safe_path(target, allow_missing_leaf=False)
        if len(raw) != size:
            raise SnapshotIntegrityError("PubMed terminal-progress record changed during read")
        return raw

    def publish_source_replay(
        self,
        kind: SourceReplayKind,
        data: bytes,
        *,
        run_id: str,
        task_id: str,
        attempt_id: str,
        query_id: str,
        acquisition_intent_id: str,
    ) -> PublishedFile:
        """Insert or verify one exact bounded DailyMed/FAERS replay record."""

        if not data or len(data) > SOURCE_REPLAY_RECORD_BYTE_CAPACITY:
            raise SnapshotCapacityError("source replay record has invalid size")
        relative, source, run_uuid = self._source_replay_relative_path(
            kind,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            query_id=query_id,
            acquisition_intent_id=acquisition_intent_id,
        )
        target = self.root.joinpath(*relative.parts)
        self._require_safe_path(target, allow_missing_leaf=True)
        if (
            not target.exists()
            and self._source_replay_count(run_uuid, source) >= _SOURCE_REPLAY_RUN_CAPACITY[source]
        ):
            raise SnapshotCapacityError(f"{source} replay records exceed the frozen run ceiling")
        return self.publish_bytes(relative.as_posix(), data, artifact_class="journal")

    def read_source_replay(
        self,
        kind: SourceReplayKind,
        *,
        run_id: str,
        task_id: str,
        attempt_id: str,
        query_id: str,
        acquisition_intent_id: str,
    ) -> bytes:
        """Read one exact bounded DailyMed/FAERS replay record and no arbitrary path."""

        if not self._initialized:
            self.initialize()
        relative, _source, _run_uuid = self._source_replay_relative_path(
            kind,
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            query_id=query_id,
            acquisition_intent_id=acquisition_intent_id,
        )
        target = self.root.joinpath(*relative.parts)
        self._require_safe_path(target, allow_missing_leaf=True)
        if not target.is_file():
            raise SnapshotIntegrityError("source replay record is missing")
        size = target.stat().st_size
        if size <= 0 or size > SOURCE_REPLAY_RECORD_BYTE_CAPACITY:
            raise SnapshotIntegrityError("source replay record has invalid size")
        raw = target.read_bytes()
        self._require_safe_path(target, allow_missing_leaf=False)
        if len(raw) != size:
            raise SnapshotIntegrityError("source replay record changed during read")
        return raw

    def publish_generation_receipt(
        self,
        data: bytes,
        *,
        run_id: str,
        receipt_id: str,
    ) -> PublishedFile:
        """Insert or verify one exact bounded generation receipt."""

        if not data or len(data) > GENERATION_RECEIPT_BYTE_CAPACITY:
            raise SnapshotCapacityError("generation receipt has invalid size")
        relative = SnapshotStore._generation_receipt_relative_path(
            self,
            run_id=run_id,
            receipt_id=receipt_id,
        )
        return SnapshotStore.publish_bytes(
            self,
            relative.as_posix(),
            data,
            artifact_class="journal",
        )

    def read_generation_receipt(self, *, run_id: str, receipt_id: str) -> bytes:
        """Read one exact bounded generation receipt and no arbitrary path."""

        if not self._initialized:
            SnapshotStore.initialize(self)
        relative = SnapshotStore._generation_receipt_relative_path(
            self,
            run_id=run_id,
            receipt_id=receipt_id,
        )
        target = self.root.joinpath(*relative.parts)
        SnapshotStore._require_safe_path(self, target, allow_missing_leaf=True)
        if not target.is_file():
            raise SnapshotIntegrityError("generation receipt is missing")
        size = target.stat().st_size
        if size <= 0 or size > GENERATION_RECEIPT_BYTE_CAPACITY:
            raise SnapshotIntegrityError("generation receipt has invalid size")
        raw = target.read_bytes()
        SnapshotStore._require_safe_path(self, target, allow_missing_leaf=False)
        if len(raw) != size:
            raise SnapshotIntegrityError("generation receipt changed during read")
        return raw

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

    def store_dailymed_response(self, body: bytes) -> SnapshotWrite:
        """Publish one exact bounded DailyMed response outside Git."""

        return self._store_dailymed_bytes(body, stable_spl=False)

    def store_faers_response(self, body: bytes) -> SnapshotWrite:
        """Publish one exact bounded FAERS aggregate response outside Git."""

        if len(body) > RAW_RESPONSE_BYTE_CAPACITY:
            raise SnapshotCapacityError("FAERS response exceeds 5,242,880 bytes")
        digest = sha256(body).hexdigest()
        relative = f"faers/raw/sha256/{digest[:2]}/{digest}.bin"
        published = self.publish_bytes(relative, body, artifact_class="raw")
        return SnapshotWrite(
            artifact_id=f"sha256:{digest}",
            path=published.path,
            byte_size=published.byte_size,
            reused_existing=published.reused_existing,
        )

    def store_dailymed_spl(
        self,
        body: bytes,
        *,
        selected_setid: str,
        selected_spl_version: str,
    ) -> SnapshotWrite:
        """Publish one run-independent content-addressed SPL XML artifact."""

        if not body:
            raise SnapshotCapacityError("a stable SPL artifact must be structurally nonempty")
        self.validate_dailymed_spl(body, selected_setid, selected_spl_version)
        return self._store_dailymed_bytes(body, stable_spl=True)

    def verify_dailymed(
        self,
        artifact_id: Sha256Digest,
        *,
        stable_spl: bool,
        selected_setid: str | None = None,
        selected_spl_version: str | None = None,
    ) -> Path:
        """Verify one exact DailyMed raw-response or stable-SPL artifact."""

        digest = artifact_id.removeprefix("sha256:")
        relative = (
            f"dailymed/sha256/{digest}.xml"
            if stable_spl
            else f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin"
        )
        target = self.root.joinpath(*PurePosixPath(relative).parts)
        self._require_safe_path(target, allow_missing_leaf=False)
        if not target.is_file():
            raise SnapshotIntegrityError("DailyMed snapshot file is missing")
        self._verify_file(target, digest, target.stat().st_size)
        if stable_spl:
            if selected_setid is None or selected_spl_version is None:
                raise SnapshotIntegrityError(
                    "stable SPL verification requires the selected SETID/version"
                )
            try:
                self.validate_dailymed_spl(
                    target.read_bytes(), selected_setid, selected_spl_version
                )
            except ValueError as error:
                raise SnapshotIntegrityError(
                    "stable SPL content is not the exact selected label"
                ) from error
        return target

    def verify_faers(self, artifact_id: Sha256Digest) -> Path:
        """Verify one exact content-addressed FAERS aggregate response."""

        digest = artifact_id.removeprefix("sha256:")
        relative = f"faers/raw/sha256/{digest[:2]}/{digest}.bin"
        target = self.root.joinpath(*PurePosixPath(relative).parts)
        self._require_safe_path(target, allow_missing_leaf=False)
        if not target.is_file():
            raise SnapshotIntegrityError("FAERS snapshot file is missing")
        self._verify_file(target, digest, target.stat().st_size)
        return target

    def validate_dailymed_spl(
        self,
        body: bytes,
        selected_setid: str,
        selected_spl_version: str,
    ) -> None:
        """Invoke the injected connector-owned frozen SPL validator."""

        if self._dailymed_spl_validator is None:
            raise SnapshotIntegrityError("stable SPL validation dependency is not configured")
        try:
            self._dailymed_spl_validator(body, selected_setid, selected_spl_version)
        except SnapshotIntegrityError:
            raise
        except Exception as error:
            raise SnapshotIntegrityError(
                "stable SPL content is not the exact selected label"
            ) from error

    def _store_dailymed_bytes(self, body: bytes, *, stable_spl: bool) -> SnapshotWrite:
        if len(body) > RAW_RESPONSE_BYTE_CAPACITY:
            raise SnapshotCapacityError("DailyMed artifact exceeds 5,242,880 bytes")
        digest = sha256(body).hexdigest()
        relative = (
            f"dailymed/sha256/{digest}.xml"
            if stable_spl
            else f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin"
        )
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

    def _source_replay_relative_path(
        self,
        kind: SourceReplayKind,
        *,
        run_id: str,
        task_id: str,
        attempt_id: str,
        query_id: str,
        acquisition_intent_id: str,
    ) -> tuple[PurePosixPath, str, str]:
        run_match = _RUN_ID_PATTERN.fullmatch(run_id)
        if run_match is None or kind not in _SOURCE_REPLAY_LAYOUT:
            raise SnapshotContainmentError("invalid source replay identity")
        source, operation = _SOURCE_REPLAY_LAYOUT[kind]
        keys = tuple(
            self._source_replay_key_digest(value)
            for value in (task_id, attempt_id, query_id, acquisition_intent_id)
        )
        run_uuid = run_match.group(1)
        relative = PurePosixPath(
            "journal",
            run_uuid,
            "orchestration",
            "source-replay",
            source,
            operation,
            *keys,
            "projection.json",
        )
        return relative, source, run_uuid

    def _generation_receipt_relative_path(
        self,
        *,
        run_id: str,
        receipt_id: str,
    ) -> PurePosixPath:
        run_match = _RUN_ID_PATTERN.fullmatch(run_id)
        receipt_match = _GENERATION_RECEIPT_ID_PATTERN.fullmatch(receipt_id)
        if run_match is None or receipt_match is None:
            raise SnapshotContainmentError("invalid generation receipt identity")
        return PurePosixPath(
            "journal",
            run_match.group(1),
            "generation",
            f"{receipt_match.group(1)}.json",
        )

    def _source_replay_key_digest(self, value: str) -> str:
        if not isinstance(value, str):
            raise SnapshotContainmentError("source replay keys must be strings")
        encoded = value.encode("utf-8")
        if not encoded or len(encoded) > _SOURCE_REPLAY_KEY_BYTE_CAPACITY:
            raise SnapshotContainmentError("source replay key has invalid size")
        return sha256(encoded).hexdigest()

    def _source_replay_count(self, run_uuid: str, source: str) -> int:
        source_root = self.root / "journal" / run_uuid / "orchestration" / "source-replay" / source
        self._require_safe_path(source_root, allow_missing_leaf=True)
        if not source_root.exists():
            return 0
        count = 0
        for directory, names, filenames in os.walk(source_root, followlinks=False):
            directory_path = Path(directory)
            self._require_safe_path(directory_path, allow_missing_leaf=False)
            for name in names:
                child = directory_path / name
                if _is_reparse(child):
                    raise SnapshotContainmentError("source replay path crosses a reparse point")
            for filename in filenames:
                child = directory_path / filename
                self._require_safe_path(child, allow_missing_leaf=False)
                if not child.is_file():
                    raise SnapshotContainmentError("source replay entry is not a regular file")
                if filename == "projection.json":
                    count += 1
        return count

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
                parts = PurePosixPath(relative).parts
                if relative.endswith(".bin") and (
                    (relative.startswith("pubmed/sha256/") and len(parts) == 4)
                    or (
                        (
                            relative.startswith("dailymed/raw/sha256/")
                            or relative.startswith("faers/raw/sha256/")
                        )
                        and len(parts) == 5
                    )
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
        object.__setattr__(self, "_lock_handle", handle)

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
            object.__setattr__(self, "_lock_handle", None)
