"""No-clobber local JSON/Markdown export under one configured project directory."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import suppress
from pathlib import Path

from medevidence.domain import sha256_digest

_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_ROOT = (
    _CHECKOUT_ROOT.parents[2]
    if _CHECKOUT_ROOT.parent.name == "worktrees" and _CHECKOUT_ROOT.parent.parent.name == ".local"
    else _CHECKOUT_ROOT
)
DEFAULT_EXPORT_ROOT = _PROJECT_ROOT / ".local" / "data" / "v1-completion-20260914" / "exports"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_EXPORT_BYTES = 33_554_432


class LocalExportIntegrityError(RuntimeError):
    """An export path or published byte stream differs from the approved material."""


class LocalExportWriter:
    """Write generated names only; publication never replaces an existing file."""

    def __init__(self) -> None:
        self._root = DEFAULT_EXPORT_ROOT

    @classmethod
    def _for_testing(cls, root: Path) -> LocalExportWriter:
        if not root.is_absolute():
            raise ValueError("test export root must be absolute")
        result = cls.__new__(cls)
        result._root = root
        return result

    def _directory(self, *, create: bool = True) -> Path:
        root = self._root
        if not root.is_absolute():
            raise LocalExportIntegrityError("export root is not absolute")
        current = Path(root.anchor)
        for part in root.parts[1:]:
            current = current / part
            if current.exists() and (current.is_symlink() or current.resolve() != current):
                raise LocalExportIntegrityError("export directory traverses a symlink or junction")
        if create:
            root.mkdir(parents=True, exist_ok=True)
        current = Path(root.anchor)
        for part in root.parts[1:]:
            current = current / part
            if current.is_symlink():
                raise LocalExportIntegrityError("export directory traverses a symlink")
        if not root.is_dir() or root.resolve() != root:
            raise LocalExportIntegrityError("export directory resolves outside configured root")
        return root

    @staticmethod
    def filenames(idempotency_key: str) -> tuple[str, str]:
        if type(idempotency_key) is not str or _DIGEST.fullmatch(idempotency_key) is None:
            raise ValueError("export idempotency key is invalid")
        suffix = idempotency_key.removeprefix("sha256:")
        return f"export-{suffix}.json", f"export-{suffix}.md"

    @staticmethod
    def _verify(path: Path, expected_hash: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise LocalExportIntegrityError("published export path is not a regular file")
        if sha256_digest(path.read_bytes()) != expected_hash:
            raise LocalExportIntegrityError("published export bytes differ from approved material")

    @staticmethod
    def _publish(root: Path, filename: str, data: bytes, expected_hash: str) -> None:
        path = root / filename
        if path.exists() or path.is_symlink():
            LocalExportWriter._verify(path, expected_hash)
            return
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".export-", suffix=".tmp", dir=root, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            with suppress(FileExistsError):
                if os.name == "nt":
                    os.rename(temporary, path)  # Windows rename never replaces an existing file.
                else:
                    os.link(temporary, path)  # Portable atomic no-clobber publication.
            LocalExportWriter._verify(path, expected_hash)
            try:
                directory_fd = os.open(root, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass  # Windows may not allow fsync on directory handles.
                finally:
                    os.close(directory_fd)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write(
        self,
        idempotency_key: str,
        json_text: str,
        markdown_text: str,
        json_byte_hash: str,
        markdown_byte_hash: str,
    ) -> tuple[str, str]:
        if type(json_text) is not str or type(markdown_text) is not str:
            raise ValueError("export material must be exact text")
        json_bytes = json_text.encode("utf-8")
        markdown_bytes = markdown_text.encode("utf-8")
        if len(json_bytes) > _MAX_EXPORT_BYTES or len(markdown_bytes) > _MAX_EXPORT_BYTES:
            raise ValueError("export material exceeds the 32 MiB per-file bound")
        if (
            sha256_digest(json_bytes) != json_byte_hash
            or sha256_digest(markdown_bytes) != markdown_byte_hash
        ):
            raise LocalExportIntegrityError("approved export material hash drift")
        names = self.filenames(idempotency_key)
        root = self._directory()
        for name, data, expected in (
            (names[0], json_bytes, json_byte_hash),
            (names[1], markdown_bytes, markdown_byte_hash),
        ):
            self._publish(root, name, data, expected)
        return names

    def read_verified(self, idempotency_key: str, format: str, expected_hash: str) -> bytes:
        """Read committed bytes without creating directories or repairing files."""

        if format not in ("json", "markdown"):
            raise ValueError("export format is invalid")
        if type(expected_hash) is not str or _DIGEST.fullmatch(expected_hash) is None:
            raise ValueError("export expected hash is invalid")
        names = self.filenames(idempotency_key)
        root = self._directory(create=False)
        path = root / (names[0] if format == "json" else names[1])
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise LocalExportIntegrityError("committed export path is not a regular file")
        if path.stat().st_size > 2_097_152:
            raise LocalExportIntegrityError("committed export exceeds download byte bound")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2_097_152:
                raise LocalExportIntegrityError("committed export handle is not a bounded file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(2_097_153)
        finally:
            os.close(fd)
        if path.is_symlink() or path.resolve() != path:
            raise LocalExportIntegrityError("committed export path changed during read")
        if len(data) > 2_097_152 or sha256_digest(data) != expected_hash:
            raise LocalExportIntegrityError("committed export bytes differ from approval")
        return data

    def verify(
        self, idempotency_key: str, json_byte_hash: str, markdown_byte_hash: str
    ) -> tuple[str, str]:
        names = self.filenames(idempotency_key)
        root = self._directory()
        self._verify(root / names[0], json_byte_hash)
        self._verify(root / names[1], markdown_byte_hash)
        return names
