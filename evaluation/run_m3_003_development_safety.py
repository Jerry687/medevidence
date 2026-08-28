"""CLI for the exact offline M3-003 Development safety evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from evaluation.m3_003_development_safety import (
    DevelopmentSafetyError,
    build_artifact,
    canonical_repository_text_bytes,
    load_case_definitions,
    write_artifact,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APPROVED_FIXTURE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "evaluation"
    / "m3_003_development_safety"
    / "cases.json"
)
APPROVED_FIXTURE_BYTES = 3151
APPROVED_FIXTURE_SHA256 = "5ad45867a58b7aa1746120a7bef4a8a2cf5d4a3cad9458a7db953fdc4e72a4c2"
APPROVED_OUTPUT_ROOT = Path(
    r"D:\Projects\medevidence-external-evidence\M3-003-DEVELOPMENT-SAFETY-EVALUATION\run-001-successor-005"
)
OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "NO_PROXY": "*",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def validate_paths(fixture: Path, output_root: Path) -> bytes:
    """Reject every input and output outside the exact Owner-approved paths."""

    if fixture.resolve(strict=False) != APPROVED_FIXTURE.resolve(strict=False):
        raise DevelopmentSafetyError("fixture path is not the one approved Development input")
    supplied_windows = PureWindowsPath(str(output_root))
    approved_windows = PureWindowsPath(str(APPROVED_OUTPUT_ROOT))
    if str(supplied_windows).casefold() != str(approved_windows).casefold():
        raise DevelopmentSafetyError("output path is outside the exact external evidence root")
    lowered = str(supplied_windows).casefold()
    if "holdout" in lowered or not supplied_windows.is_absolute():
        raise DevelopmentSafetyError("repository and Holdout-looking output is forbidden")
    if os.name == "nt" and output_root.resolve(strict=False).is_relative_to(
        REPOSITORY_ROOT.resolve(strict=False)
    ):
        raise DevelopmentSafetyError("repository and Holdout-looking output is forbidden")
    try:
        physical = fixture.read_bytes()
    except OSError as error:
        raise DevelopmentSafetyError("cannot read approved fixture") from error
    data = canonical_repository_text_bytes(physical, label="approved fixture")
    if (
        len(data) != APPROVED_FIXTURE_BYTES
        or hashlib.sha256(data).hexdigest() != APPROVED_FIXTURE_SHA256
    ):
        raise DevelopmentSafetyError("approved fixture exact bytes or hash drifted")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the frozen synthetic suite and publish one immutable artifact."""

    args = _parser().parse_args(argv)
    for name, value in OFFLINE_ENVIRONMENT.items():
        os.environ[name] = value
    fixture_bytes = validate_paths(args.fixture, args.output_root)
    if os.name != "nt":
        raise DevelopmentSafetyError("external evidence publication requires Windows")
    cases = load_case_definitions(args.fixture)
    artifact = build_artifact(
        cases,
        fixture_bytes=fixture_bytes,
        generated_at_utc=datetime.now(UTC),
    )
    identities = write_artifact(artifact, args.output_root)
    print(
        json.dumps(
            {
                "status": "M3_003_DEVELOPMENT_SAFETY_ARTIFACT_WRITTEN",
                "output_root": str(args.output_root),
                **identities,
                "network_operations": 0,
                "medical_source_operations": 0,
                "model_operations": 0,
                "package_operations": 0,
                "holdout_20_accessed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
