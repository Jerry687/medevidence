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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.datasets import load_beir_directory, load_jsonl_dataset
from evaluation.harness import RetrievalHarness, RunConfig

REPORTED = ("recall@5", "recall@10", "mrr@10", "ndcg@10")


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser."""

    parser = argparse.ArgumentParser(description="M2 retrieval baseline comparison")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--beir", help="BEIR-layout dataset directory")
    source.add_argument("--jsonl", help="single-file dataset")
    parser.add_argument("--split", default="test", help="qrels split (default: test)")
    parser.add_argument("--max-documents", type=int, default=None)
    parser.add_argument("--output", default="evaluation/results")
    parser.add_argument("--dimensions", type=int, default=256)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--bm25-k1", type=float, default=0.9)
    parser.add_argument("--bm25-b", type=float, default=0.4)
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--final-limit", type=int, default=10)
    parser.add_argument("--grade-min", type=int, default=1)
    parser.add_argument(
        "--modes",
        default="sparse,dense,hybrid_rrf",
        help="comma-separated subset of sparse,dense,hybrid_rrf",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Load the dataset, run every baseline, save artifacts, print a table."""

    args = build_parser().parse_args(argv)
    if args.beir:
        dataset = load_beir_directory(args.beir, split=args.split, max_documents=args.max_documents)
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
    )
    harness = RetrievalHarness(dataset, config)
    modes = tuple(mode.strip() for mode in args.modes.split(",") if mode.strip())
    results = harness.run_all(modes)
    run_dir = harness.save(results, args.output)

    width = max(len(mode) for mode in results)
    header = f"{'mode'.ljust(width)}  " + "  ".join(name.rjust(10) for name in REPORTED)
    print("\n" + header)
    print("-" * len(header))
    for mode in modes:
        summary = results[mode].summary
        row = f"{mode.ljust(width)}  " + "  ".join(
            f"{summary.get(name, float('nan')):10.4f}" for name in REPORTED
        )
        print(row)
    print("-" * len(header))
    for mode in modes:
        summary = results[mode].summary
        print(
            f"{mode.ljust(width)}  latency p50 {summary.get('latency_p50_ms', 0):8.2f} ms"
            f"   p95 {summary.get('latency_p95_ms', 0):8.2f} ms"
        )
    print(f"\nartifacts {run_dir}")
    print(
        "NOTE      experiment only; ME-000C is open and no value above is an "
        "approved configuration or a release threshold."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
