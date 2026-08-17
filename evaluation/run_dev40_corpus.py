"""Offline-only CLI for the M2-006 Dev-40 corpus freeze."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.dev40_corpus import OUTPUT_ROOT, freeze_dev40, load_and_validate_freeze


def build_parser() -> argparse.ArgumentParser:
    """Build the request-free CLI parser."""

    parser = argparse.ArgumentParser(description="Freeze or verify the offline Dev-40 corpus")
    parser.add_argument("--output-root", required=True, choices=[str(OUTPUT_ROOT)])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--freeze", action="store_true")
    modes.add_argument("--verify", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one explicit offline corpus operation."""

    args = build_parser().parse_args(argv)
    result = (
        freeze_dev40(args.output_root)
        if args.freeze
        else load_and_validate_freeze(args.output_root)
    )
    print(
        json.dumps(
            {
                "status": "OWNER_ADJUDICATION_REQUIRED",
                "network_operations": 0,
                "corpus_units": result.corpus_units,
                "adjudication_questions": result.adjudication_questions,
                "corpus_manifest_sha256": result.corpus_manifest_sha256,
                "blinded_packet_sha256": result.blinded_packet_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
