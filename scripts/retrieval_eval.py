"""Run the local production ranker against document-level relevance judgments."""

import argparse
import hashlib
from importlib import metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyzer import library

FIXTURE = ROOT / "examples/retrieval-eval"
MODES = {"bm25": {"BM25"}, "vector": {"Vector"}, "hybrid": {"BM25", "Vector"}, "hybridAst": None}


def assess(hits, relevant):
    documents = list(dict.fromkeys(hit["filename"] for hit in hits))
    gold = set(relevant)
    first = next((i for i, name in enumerate(documents, 1) if name in gold), None)
    return {
        "documents": documents,
        "recallAt5": len(gold.intersection(documents[:5])) / len(gold) if gold else None,
        "reciprocalRank": (1 / first if first else 0) if gold else None,
    }


def summarize(records, timings):
    positives = [r for r in records if r["recallAt5"] is not None]
    negatives = [r for r in records if r["recallAt5"] is None]
    return {
        "positiveQueries": len(positives),
        "recallAt5": statistics.mean(r["recallAt5"] for r in positives),
        "mrr": statistics.mean(r["reciprocalRank"] for r in positives),
        "emptyGoldQueries": len(negatives),
        "emptyGoldWithCandidates": sum(bool(r["documents"]) for r in negatives),
        "emptyGoldCandidateDocumentsAt5": sum(len(r["documents"][:5]) for r in negatives),
        "rankCalls": len(timings),
        "rankP95Ms": sorted(timings)[math.ceil(len(timings) * 0.95) - 1],
    }


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(repeats):
    if os.environ.get("LIBRARY_QDRANT_URL"):
        raise ValueError("This benchmark requires the local vector backend; unset LIBRARY_QDRANT_URL.")
    corpus = json.loads((FIXTURE / "corpus.json").read_text())
    questions = json.loads((FIXTURE / "queries.json").read_text())
    documents, digests = [], {}
    for source in corpus:
        name = source["filename"]
        if name in digests:
            raise ValueError(f"duplicate filename {name}")
        content = (ROOT / source["path"]).read_text() if "path" in source else source["content"]
        bundle = library.index({"filename": name, "content": content})
        documents.append({"filename": name, "index": bundle})
        digests[name] = bundle["contentSha256"]
    rows, scope = library.rows_and_scope({"documents": documents})
    queries = {}
    for item in questions:
        key = item["id"]
        gold = item["relevant"]
        if key in queries or len(gold) != len(set(gold)) or set(gold) - digests.keys():
            raise ValueError(f"invalid judgments for {key}")
        old, new = (f"# {item['heading']}\n\n{item[field]}" for field in ("before", "after"))
        change, = library.text.changes(old, new)
        queries[key] = change, gold

    jobs = [(key, mode) for key in queries for mode in MODES]
    result = {mode: {} for mode in MODES}
    shuffle = random.Random(20261124)
    # One untimed warm-up per pair; interleave the measured modes on each repetition.
    for iteration in range(repeats + 1):
        shuffle.shuffle(jobs)
        for key, mode in jobs:
            change, gold = queries[key]
            channels = MODES[mode]
            start = perf_counter_ns()
            if channels is None:
                hits = library.rank(change, rows, scope)
            else:
                hits = library.rank(change, rows, scope, channels=channels)
            elapsed_ms = (perf_counter_ns() - start) / 1_000_000
            record = assess(hits, gold)
            if iteration == 0:
                result[mode][key] = {**record, "rankMs": []}
            else:
                measured = result[mode][key]
                if record["documents"] != measured["documents"]:
                    raise RuntimeError(f"non-reproducible document order in {mode}/{key}")
                measured["rankMs"].append(elapsed_ms)

    modes = {}
    for mode, queries_result in result.items():
        records = list(queries_result.values())
        timings = [ms for record in records for ms in record["rankMs"]]
        modes[mode] = {"summary": summarize(records, timings), "queries": queries_result}
    encoder = library.vectors.encoder()
    packages = {}
    if encoder != "concept-hash-v1":
        packages = {name: metadata.version(name) for name in ("numpy", "onnxruntime", "tokenizers")}
    return {
        "protocol": 1,
        "encoder": encoder, "vectorBackend": "local", "platform": platform.platform(),
        "python": platform.python_version(), "packages": packages, "repeats": repeats,
        "warmupPerModeQuery": 1, "scheduleSeed": 20261124,
        "documents": len(documents), "chunks": len(rows), "queries": len(queries),
        "inputsSha256": {file: sha((FIXTURE / file).read_bytes()) for file in ("corpus.json", "queries.json")},
        "documentContentSha256": digests,
        "modes": modes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    report = run(args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({key: mode["summary"] for key, mode in report["modes"].items()}, indent=2))


if __name__ == "__main__":
    main()
