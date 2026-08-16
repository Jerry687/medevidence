"""Two-stage CLI for M2-006 request freeze and authorized acquisition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, str(WORKTREE_ROOT / "src"))

from evaluation.dev40_acquisition import (  # noqa: E402
    FREEZE_ROOT,
    LIVE_ACKNOWLEDGEMENT,
    LIVE_ROOT,
    prepare_request_freeze,
    run_authorized_acquisition,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI without filesystem or network I/O."""

    parser = argparse.ArgumentParser(description="Freeze or execute exact M2-006 acquisition")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare-offline", action="store_true")
    modes.add_argument("--execute-authorized-live", action="store_true")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--request-freeze-path")
    parser.add_argument("--request-freeze-sha256")
    parser.add_argument("--pre-network-review-record")
    parser.add_argument("--pre-network-review-sha256")
    parser.add_argument("--acknowledge-exact-live-authorization", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run exactly one stage and print metadata-only evidence."""

    args = build_parser().parse_args(argv)
    if args.prepare_offline:
        if Path(args.output_root).resolve() != FREEZE_ROOT.resolve():
            raise SystemExit("offline preparation requires the exact acquisition-freeze root")
        if any(
            (
                args.request_freeze_path,
                args.request_freeze_sha256,
                args.pre_network_review_record,
                args.pre_network_review_sha256,
                args.acknowledge_exact_live_authorization,
            )
        ):
            raise SystemExit("offline preparation forbids live-only arguments")
        pre_result = prepare_request_freeze(args.output_root)
        value = {
            "status": "PRE_NETWORK_REVIEW_REQUIRED",
            "network_operations": 0,
            "request_freeze_sha256": pre_result.sha256,
            "source_state_aggregate_sha256": pre_result.source_state_aggregate_sha256,
            "runtime_closure_aggregate_sha256": pre_result.runtime_closure_aggregate_sha256,
        }
    else:
        if Path(args.output_root).resolve() != LIVE_ROOT.resolve():
            raise SystemExit("live execution requires the exact acquisition-001 root")
        required = (
            args.request_freeze_path,
            args.request_freeze_sha256,
            args.pre_network_review_record,
            args.pre_network_review_sha256,
        )
        if not all(required) or not args.acknowledge_exact_live_authorization:
            raise SystemExit("live execution requires exact freeze, review, and acknowledgement")
        live_result = run_authorized_acquisition(
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=args.request_freeze_path,
            request_freeze_sha256=args.request_freeze_sha256,
            review_record_path=args.pre_network_review_record,
            review_record_sha256=args.pre_network_review_sha256,
            output_root=args.output_root,
        )
        value = {
            "status": "ACQUISITION_COMPLETE_OFFLINE_CORPUS_RECONCILIATION_ONLY",
            "manifest_sha256": live_result.manifest_sha256,
            "authorized_logical_operations": live_result.authorized_logical_operations,
            "executed_logical_operations": live_result.executed_logical_operations,
            "skipped_empty_fetches": live_result.skipped_empty_fetches,
            "http_requests": live_result.http_requests,
            "raw_bytes": live_result.raw_bytes,
        }
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
