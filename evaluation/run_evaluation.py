"""Command-line entry point for the M2 retrieval baseline comparison.

Examples
--------
BEIR-layout dataset (NFCorpus, SciFact, TREC-COVID, ...)::

    python -m evaluation.run_evaluation --beir data/nfcorpus --split test

Single-file fixture::

    python -m evaluation.run_evaluation --jsonl tests/fixtures/retrieval/tiny.json

Fast smoke run over a truncated corpus (recall is then not comparable to the
full corpus, and the truncation is recorded as a dataset warning)::

    python -m evaluation.run_evaluation --beir data/nfcorpus --max-documents 2000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

NATIVE_THREAD_ENVIRONMENT_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

for _name in NATIVE_THREAD_ENVIRONMENT_VARIABLES:
    os.environ[_name] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.datasets import load_beir_directory, load_jsonl_dataset  # noqa: E402
from evaluation.harness import MODE_DISPLAY_NAMES, RetrievalHarness, RunConfig  # noqa: E402

REPORTED = ("recall@10", "ndcg@10", "mrr@10")


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser."""

    parser = argparse.ArgumentParser(description="M2 retrieval baseline comparison")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--beir", help="BEIR-layout dataset directory")
    source.add_argument("--jsonl", help="single-file dataset")
    parser.add_argument("--dataset-name", help="declared benchmark dataset name")
    parser.add_argument("--dataset-source", help="authoritative distribution source URL")
    parser.add_argument(
        "--distribution-archive",
        help="local downloaded distribution archive whose bytes are authoritative",
    )
    parser.add_argument("--split", default="test", help="qrels split (default: test)")
    parser.add_argument("--max-documents", type=int, default=None)
    parser.add_argument("--output", default="evaluation/results")
    parser.add_argument(
        "--run-id",
        help=(
            "single deterministic output-directory name; use "
            "nfcorpus-real-final for the tracked final run"
        ),
    )
    parser.add_argument("--dimensions", type=int, default=256)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--bm25-k1", type=float, default=0.9)
    parser.add_argument("--bm25-b", type=float, default=0.4)
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--final-limit", type=int, default=10)
    parser.add_argument("--grade-min", type=int, default=1)
    parser.add_argument("--random-seed", type=int, default=0)
    parser.add_argument("--query-concurrency", type=int, default=1)
    parser.add_argument("--blas-threads", type=int, default=1)
    parser.add_argument(
        "--medcpt-artifact-manifest",
        help="external verified MedCPT artifact-acquisition manifest",
    )
    parser.add_argument(
        "--medcpt-cache-root",
        help="external local-only MedCPT cache root",
    )
    parser.add_argument(
        "--modes",
        default="sparse,dense,hybrid_rrf",
        help=("comma-separated subset of sparse,dense,hybrid_rrf,medcpt,hybrid_rrf_medcpt"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Load the dataset, run every baseline, save artifacts, print a table."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.beir:
        missing = [
            option
            for option, value in (
                ("--dataset-name", args.dataset_name),
                ("--dataset-source", args.dataset_source),
                ("--distribution-archive", args.distribution_archive),
            )
            if not value
        ]
        if missing:
            parser.error(f"--beir real benchmark requires {', '.join(missing)}")
        dataset = load_beir_directory(
            args.beir,
            split=args.split,
            dataset_id=args.dataset_name,
            dataset_source=args.dataset_source,
            distribution_archive=args.distribution_archive,
            max_documents=args.max_documents,
        )
    else:
        dataset = load_jsonl_dataset(args.jsonl)

    print(f"dataset   {dataset.dataset_id}")
    print(f"          {json.dumps(dataset.summary())}")
    for warning in dataset.warnings:
        print(f"  WARNING {warning}")

    config = RunConfig(
        bm25_k1=args.bm25_k1,
        bm25_b=args.bm25_b,
        embedding_dimensions=args.dimensions,
        rrf_k=args.rrf_k,
        candidate_limit=args.candidate_limit,
        final_limit=args.final_limit,
        relevant_grade_min=args.grade_min,
        random_state=args.random_seed,
        query_concurrency=args.query_concurrency,
        blas_threads=args.blas_threads,
    )
    modes = tuple(mode.strip() for mode in args.modes.split(",") if mode.strip())
    uses_medcpt = bool({"medcpt", "hybrid_rrf_medcpt"}.intersection(modes))
    if uses_medcpt and not args.medcpt_artifact_manifest:
        parser.error("MedCPT modes require --medcpt-artifact-manifest")
    if uses_medcpt and not args.medcpt_cache_root:
        parser.error("MedCPT modes require --medcpt-cache-root")
    if not uses_medcpt and (args.medcpt_artifact_manifest or args.medcpt_cache_root):
        parser.error("MedCPT artifact paths require a selected MedCPT mode")
    harness = RetrievalHarness(
        dataset,
        config,
        medcpt_artifact_manifest=args.medcpt_artifact_manifest,
        medcpt_cache_root=args.medcpt_cache_root,
    )
    results = harness.run_all(modes)
    run_dir = harness.save(results, args.output, run_id=args.run_id)

    display_names = {mode: MODE_DISPLAY_NAMES[mode] for mode in results}
    width = max(len(name) for name in display_names.values())
    header = f"{'mode'.ljust(width)}  " + "  ".join(name.rjust(10) for name in REPORTED)
    print("\n" + header)
    print("-" * len(header))
    for mode in modes:
        summary = results[mode].summary
        row = f"{display_names[mode].ljust(width)}  " + "  ".join(
            f"{summary.get(name, float('nan')):10.4f}" for name in REPORTED
        )
        print(row)
    print("-" * len(header))
    for mode in modes:
        summary = results[mode].summary
        print(
            f"{display_names[mode].ljust(width)}  latency/query mean "
            f"{summary.get('latency_mean_ms', 0):8.2f} ms"
            f"   p50 {summary.get('latency_p50_ms', 0):8.2f} ms"
            f"   p95 {summary.get('latency_p95_ms', 0):8.2f} ms"
            f"   build/index {float(results[mode].build_timing['seconds']):8.4f} s"
            f" ({results[mode].build_timing['kind']})"
        )
    print(f"\nartifacts {run_dir}")
    print(
        "NOTE      experiment-only M2 pilot. classical_lsi_dense remains classical "
        "latent-semantic retrieval; MedCPT modes use verified local-only CPU artifacts. "
        "ME-000C remains open outside this pilot."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
