"""Explicit two-stage CLI for the bounded M2-005 Gold-10 V2 lifecycle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.gold10_v2 import (
    CANONICAL_OUTPUT_ROOT,
    LIVE_ACKNOWLEDGEMENT,
    prepare_pre_network,
    run_live_recovery,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI without performing filesystem or network I/O."""

    parser = argparse.ArgumentParser(
        description="Prepare offline M2-005 evidence or execute its one-shot live recovery"
    )
    parser.add_argument(
        "--output-root",
        required=True,
        choices=[str(CANONICAL_OUTPUT_ROOT)],
        help="exact external M2-005 evidence root",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--prepare-offline",
        action="store_true",
        help="reconstruct retained evidence and create no network-capable client",
    )
    modes.add_argument(
        "--execute-authorized-live-recovery",
        action="store_true",
        help="consume the new one-shot MOUNJARO authorization",
    )
    parser.add_argument("--pre-network-review-record")
    parser.add_argument("--pre-network-review-sha256")
    parser.add_argument(
        "--acknowledge-exact-live-authorization",
        action="store_true",
        help="acknowledge the exact M2-005 MOUNJARO operation and no-rerun rule",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run exactly one selected stage and print metadata-only evidence."""

    args = build_parser().parse_args(argv)
    if args.prepare_offline:
        if (
            args.pre_network_review_record
            or args.pre_network_review_sha256
            or args.acknowledge_exact_live_authorization
        ):
            raise SystemExit("offline preparation forbids live-only arguments")
        pre_result = prepare_pre_network(args.output_root)
        value = {
            "status": "PRE_NETWORK_REVIEW_REQUIRED",
            "network_operations": 0,
            "live_authorization_status": "unconsumed",
            "manifest_sha256": pre_result.manifest_sha256,
            "pubmed_items": pre_result.pubmed_items,
            "ozempic_retrieval_items": pre_result.ozempic_retrieval_items,
            "ozempic_structural_occurrences": pre_result.ozempic_structural_occurrences,
        }
    else:
        if not args.acknowledge_exact_live_authorization:
            raise SystemExit("live recovery requires the exact acknowledgement flag")
        if not args.pre_network_review_record or not args.pre_network_review_sha256:
            raise SystemExit("live recovery requires a hash-bound independent review record")
        live_result = run_live_recovery(
            args.output_root,
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            review_record_path=args.pre_network_review_record,
            review_record_sha256=args.pre_network_review_sha256,
        )
        value = {
            "status": "OWNER_DECISION_REQUIRED",
            "corpus_manifest_sha256": live_result.corpus_manifest_sha256,
            "adjudication_packet_sha256": live_result.adjudication_packet_sha256,
            "mounjaro_retrieval_items": live_result.mounjaro_retrieval_items,
            "mounjaro_structural_occurrences": live_result.mounjaro_structural_occurrences,
            "http_attempts": live_result.http_attempts,
        }
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
