#!/usr/bin/env python3
"""Measure the local Java/Python batch path and verify a crash against a durable H2 DB."""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
from statistics import median
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_recovery import JAR, request, workbench

FIXTURES = ROOT / "examples/batch-upgrade"
EXPECTED = {"01-config.md": "ask", "02-clustering.md": "edit", "03-features.md": "edit",
            "04-ready.md": "keep", "05-stats.md": "irrelevant"}
POLL_SECONDS = 0.025
CRASH_LEASE_MS = 4000


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def runtime_hashes():
    modules = sorted(p for p in (ROOT / "analyzer").glob("*.py") if not p.name.startswith("test_"))
    return {
        "jarSha256": hashlib.sha256(JAR.read_bytes()).hexdigest(),
        "analyzerSourcesSha256": digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in modules}),
    }


def corpus():
    originals, labels = {}, {}
    for group in range(1, 6):
        for name, status in EXPECTED.items():
            key = f"group-{group:02}-{name}"
            originals[key] = (FIXTURES / "notes" / name).read_text() + f"\n记录编号 {group:02}。\n"
            labels[key] = status
    return originals, labels


def wait_for(read, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read()
        if predicate(result):
            return result
        time.sleep(POLL_SECONDS)
    raise TimeoutError("Timed out waiting for " + str(read))


@contextmanager
def server(directory, width, poll_ms=25, audit=None):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    python = sys.executable
    if audit:
        # ZIP extractors may drop executable bits on scripts. Use an executable copy in the test DB directory.
        shim = directory / "record_invocation.py"
        shutil.copyfile(HERE / "record_invocation.py", shim)
        shim.chmod(0o700)
        python = str(shim)
    settings = {
        "REVIEW_BATCH_PARALLELISM": str(width),
        "REVIEW_BATCH_POLLMS": str(poll_ms),
        "REVIEW_BATCH_LEASEMS": str(CRASH_LEASE_MS if audit else 120000),
        "REVIEW_LIBRARY_PYTHON": python,
        "REVIEW_LIBRARY_URL": "", "REVIEW_ARCHIVE_URL": "", "REVIEW_RESTORE_URL": "",
        "REVIEW_ENQUEUE_URL": "", "REVIEW_DEQUEUE_URL": "",
        "LIBRARY_ENCODER": "concept", "LIBRARY_QDRANT_URL": "",
        "BATCH_AUDIT_LOG": str(audit) if audit else "", "BATCH_PYTHON": sys.executable,
    }
    with patch.dict(os.environ, settings):
        with workbench(port, directory, "http://127.0.0.1:1/v1") as live:
            yield live


def seed(base, originals):
    for version in ("1.1.3", "1.4.2"):
        path = FIXTURES / "sources" / f"sklearn-{version}.md"
        notes = [{"filename": k, "content": v} for k, v in originals.items()] if version == "1.1.3" else []
        job = request(base + "/api/library/import", {
            "source": {"name": "scikit-learn", "version": version, "filename": path.name, "content": path.read_text()},
            "notes": notes,
        })
        wait_for(lambda: request(base + "/api/library"), lambda p: p.get("activeGeneration") == job["generation"])
    return job["generation"]


def submit(base, generation):
    api = base + "/api/library/batches"
    created = request(api, {"instruction": "帮我更新到目标版本", "name": "scikit-learn",
                            "fromVersion": "1.1.3", "toVersion": "1.4.2", "generation": generation})
    return created["id"]


def status(base, batch):
    return request(base + "/api/library/batches/" + batch)


def completed(base, batch):
    page = wait_for(lambda: status(base, batch), lambda p: p["status"] != "running")
    if page["status"] != "complete" or page["done"] != page["total"]:
        raise AssertionError(page)
    return page


def measured(base, generation, originals, labels, reference):
    start = time.perf_counter()
    batch = submit(base, generation)
    page = completed(base, batch)
    elapsed = time.perf_counter() - start
    rows = page["items"]
    assert [r["filename"] for r in rows] == sorted(originals)
    assert [r["id"] for r in rows] == [str(i + 1) for i in range(len(originals))]
    assert {r["filename"]: r["status"] for r in rows} == labels
    assert {r["filename"]: r["original"] for r in rows} == originals
    assert all(not r["accepted"] for r in rows)
    assert all("此笔记的调查未完成" not in r["reason"] for r in rows)
    if reference is not None:
        assert rows == reference, "Returned ordered item payload differs from the serial run"
    return rows, {"batchId": batch, "seconds": round(elapsed, 6), "itemsSha256": digest(rows)}


def recover(directory, generation, reference):
    before_log = directory / "before.ndjson"
    after_log = directory / "after.ndjson"
    with server(directory, 4, audit=before_log) as (proc, base):
        batch = submit(base, generation)
        observed = wait_for(lambda: status(base, batch), lambda p: p["done"] > 0)
        assert 0 < observed["done"] < observed["total"]
        proc.kill()
        assert proc.wait(timeout=10) == -signal.SIGKILL
    # Snapshot the exact durable boundary. More commits can occur between GET and SIGKILL.
    with server(directory, 4, poll_ms=600000) as (_, base):
        durable = status(base, batch)
    assert durable["status"] == "running" and observed["done"] <= durable["done"] < len(reference)
    saved = {r["filename"]: r for r in durable["items"]}
    assert all(saved[r["filename"]] == r for r in observed["items"])

    start = time.perf_counter()
    with server(directory, 4, audit=after_log) as (_, base):
        final = completed(base, batch)
    elapsed = time.perf_counter() - start
    assert final["items"] == reference
    assert all(saved[r["filename"]] == r for r in final["items"] if r["filename"] in saved)
    before = before_log.read_text().splitlines()
    after = after_log.read_text().splitlines()
    expected = [r["filename"] for r in reference if r["filename"] not in saved]
    assert Counter(after) == Counter(expected), (after, expected)
    return {"batchId": batch, "signal": "SIGKILL", "leaseMs": CRASH_LEASE_MS,
            "observedBeforeKill": observed["done"], "durableAfterReopen": len(saved),
            "durableItemSha256": {k: digest(v) for k, v in saved.items()},
            "analyzerStartsBeforeKill": before, "analyzerStartsAfterRecovery": after,
            "previouslyDurableItemsReanalyzed": len(set(after) & saved.keys()),
            "finalItemsSha256": digest(final["items"]), "finalCount": final["done"],
            "recoverySecondsIncludingJVMStartAndShutdown": round(elapsed, 6)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()
    if args.pairs < 2:
        parser.error("use at least two paired runs")
    originals, labels = corpus()
    java = Path(os.environ["JAVA_HOME"]) / "bin/java" if "JAVA_HOME" in os.environ else shutil.which("java")
    artifact_hashes = runtime_hashes()
    runs, reference = [], None
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        with server(directory, 1) as (_, base):
            generation = seed(base, originals)
        for pair in range(1, args.pairs + 1):
            for width in ((1, 4) if pair % 2 else (4, 1)):
                with server(directory, width) as (_, base):
                    warmup, _ = measured(base, generation, originals, labels, reference)
                    if reference is None:
                        reference = warmup
                    _, result = measured(base, generation, originals, labels, reference)
                runs.append(dict(pair=pair, parallelism=width, **result))
                print(f"pair={pair} parallelism={width} {result['seconds']:.3f}s", flush=True)
        crash = recover(directory, generation, reference)

    durations = {n: median(r["seconds"] for r in runs if r["parallelism"] == n) for n in (1, 4)}
    assert artifact_hashes == runtime_hashes(), "Analyzer or JAR changed during the benchmark"
    report = {
        "measuredAtUTC": datetime.now(timezone.utc).isoformat(),
        "machine": {"system": platform.system(), "release": platform.release(), "macOS": platform.mac_ver()[0],
                    "arch": platform.machine(), "logicalCPUs": os.cpu_count(), "python": platform.python_version(),
                    "java": subprocess.check_output([java, "-version"], stderr=subprocess.STDOUT, text=True).strip()},
        **artifact_hashes, "notes": len(originals),
        "inputSha256": digest(originals), "sourceFilesSha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted((FIXTURES / "sources").glob("*.md"))},
        "fixtureFamilies": len(EXPECTED), "expectedCounts": dict(Counter(labels.values())),
        "backend": "Spring Boot + file H2 (WRITE_DELAY=0) + local Python subprocess per note; concept index",
        "timing": "Client monotonic wall clock from POST start through first complete GET, 25 ms polls; "
                  "one excluded full warmup per fresh JVM, same published DB generation, alternating pair order.",
        "parallelismConfig": "review.batch.parallelism", "runs": runs,
        "medianSeconds": durations, "ratioOfMedians": round(durations[1] / durations[4], 4),
        "pairedSpeedups": [round(next(r["seconds"] for r in runs if r["pair"] == pair and r["parallelism"] == 1) /
                                 next(r["seconds"] for r in runs if r["pair"] == pair and r["parallelism"] == 4), 4)
                           for pair in range(1, args.pairs + 1)],
        "allOrderedItemsEqual": True, "referenceItemsSha256": digest(reference),
        "referenceItems": {r["filename"]: {"id": r["id"], "status": r["status"], "sha256": digest(r)}
                           for r in reference},
        "crashRecovery": crash,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {args.output}  speedup={report['ratioOfMedians']}x", flush=True)


if __name__ == "__main__":
    main()
