"""Bind local execution to real Git ancestry and immutable implementation bytes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from medevidence.domain import canonical_json, sha256_digest
from medevidence.ingestion.snapshots import SnapshotStore

CHECKOUT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class RuntimeImplementationIdentity:
    revision: str
    manifest_bytes: bytes
    manifest_hash: str


def _revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError("local runtime requires an identifiable Git checkout")
    return result.stdout.strip()


def capture_runtime_identity(
    revision: str, *, root: Path = CHECKOUT_ROOT
) -> RuntimeImplementationIdentity:
    """Read source/config bytes, including uncommitted changes; never read secrets."""
    if revision != _revision(root):
        raise ValueError("configured code revision differs from the actual checkout HEAD")
    paths = [*root.joinpath("src").rglob("*.py"), *root.joinpath("alembic").rglob("*.py")]
    paths.extend(root / name for name in ("pyproject.toml", "uv.lock", "alembic.ini"))
    if not paths or any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError("runtime source inventory is incomplete or redirected")
    files = {
        path.relative_to(root).as_posix(): sha256_digest(path.read_bytes())
        for path in sorted(paths)
    }
    raw = canonical_json(
        {"marker": "MEDEVIDENCE_RUNTIME_IMPLEMENTATION_V1", "git_head": revision, "files": files}
    ).encode("utf-8")
    return RuntimeImplementationIdentity(revision, raw, sha256_digest(raw))


def bind_runtime_implementation(
    snapshots: SnapshotStore, identity: RuntimeImplementationIdentity, *, run_id: str
) -> None:
    """Publish a no-clobber run binding before source/model work or replay."""
    if sha256_digest(identity.manifest_bytes) != identity.manifest_hash:
        raise ValueError("runtime implementation manifest changed")
    manifest_path = (
        "runtime/implementation/" + identity.manifest_hash.removeprefix("sha256:") + ".json"
    )
    run_path = (
        "runtime/run-implementation/" + sha256_digest(run_id).removeprefix("sha256:") + ".json"
    )
    binding = canonical_json(
        {
            "marker": "MEDEVIDENCE_RUN_IMPLEMENTATION_V1",
            "run_id": run_id,
            "git_head": identity.revision,
            "implementation_hash": identity.manifest_hash,
        }
    ).encode("utf-8")
    with snapshots.writer():
        snapshots.publish_bytes(manifest_path, identity.manifest_bytes, artifact_class="manifest")
        snapshots.publish_bytes(run_path, binding, artifact_class="journal")
