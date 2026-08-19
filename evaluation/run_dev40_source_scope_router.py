"""CLI for the exact offline M2-009 Dev-40 routed execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", required=True, type=Path)
    parser.add_argument("--blinded-packet", required=True, type=Path)
    parser.add_argument("--qrels", required=True, type=Path)
    parser.add_argument("--nonzero-qrels", required=True, type=Path)
    parser.add_argument("--adjudication", required=True, type=Path)
    parser.add_argument("--metric-contract", required=True, type=Path)
    parser.add_argument("--bundle-manifest", required=True, type=Path)
    parser.add_argument("--model-manifest", required=True, type=Path)
    parser.add_argument("--model-cache", required=True, type=Path)
    parser.add_argument("--m2-006-manifest", required=True, type=Path)
    parser.add_argument("--routing-contract", required=True, type=Path)
    parser.add_argument("--routing-validation", required=True, type=Path)
    parser.add_argument("--stage-a-replay-manifest", required=True, type=Path)
    parser.add_argument("--stage-a-routed", required=True, type=Path)
    parser.add_argument("--owner-exception-closure", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one production-selected mode per routed question from local bytes only."""

    args = _parser().parse_args(argv)
    for name, value in OFFLINE_ENVIRONMENT.items():
        os.environ[name] = value
    from evaluation.dev40_benchmark import (
        Dev40InputPaths,
        build_local_medcpt_index,
        load_dev40_dataset,
    )
    from evaluation.dev40_source_scope_router import (
        Dev40SourceScopeRouterRunner,
        RoutingEvidencePaths,
        load_routing_evidence,
        save_routed_execution,
        validate_output_root,
    )

    # This gate intentionally precedes every corpus, qrels, routing, and model read.
    validate_output_root(args.output_root)
    dataset = load_dev40_dataset(
        Dev40InputPaths(
            corpus=args.corpus_manifest,
            packet=args.blinded_packet,
            qrels=args.qrels,
            nonzero_qrels=args.nonzero_qrels,
            adjudication=args.adjudication,
            contract=args.metric_contract,
            bundle_manifest=args.bundle_manifest,
        )
    )
    evidence_paths = RoutingEvidencePaths(
        m2_006_manifest=args.m2_006_manifest,
        routing_contract=args.routing_contract,
        routing_validation=args.routing_validation,
        stage_a_replay_manifest=args.stage_a_replay_manifest,
        stage_a_routed=args.stage_a_routed,
        owner_exception_closure=args.owner_exception_closure,
    )
    evidence = load_routing_evidence(evidence_paths, dataset)
    index, build_seconds = build_local_medcpt_index(
        dataset,
        manifest_path=args.model_manifest,
        cache_root=args.model_cache,
    )
    run = Dev40SourceScopeRouterRunner(
        dataset,
        index,
        evidence,
        medcpt_build_seconds=build_seconds,
    ).run()
    output = save_routed_execution(
        run,
        dataset,
        evidence,
        index,
        evidence_paths,
        args.output_root,
    )
    manifest = output / "manifest.json"
    print(
        json.dumps(
            {
                "status": "M2_009_DEV40_ROUTED_EXECUTION_001_ARTIFACT_WRITTEN",
                "output_root": str(output),
                "manifest_bytes": manifest.stat().st_size,
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "network_operations": 0,
                "holdout_access": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
