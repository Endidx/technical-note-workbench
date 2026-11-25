"""Replay the frozen paired study against a dedicated local llama.cpp server."""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[1]
FROZEN = STUDY / "frozen"
MANIFEST = "22bd2705d2e0148e87fb41684d1a7ee9f057e63c5b28906413ad38e377b52532"
MODEL_SHA = "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"
sys.path.insert(0, str(ROOT))
from analyzer import checkpoint, harness, library, model_audit
from scripts.patch_score import verified_edit


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for piece in iter(lambda: f.read(1024 * 1024), b""):
            h.update(piece)
    return h.hexdigest()


def check_inputs():
    manifest = FROZEN / "SHA256SUMS"
    if digest(manifest) != MANIFEST:
        raise ValueError("Frozen manifest changed")
    for row in manifest.read_text().splitlines():
        expected, name = row.split("  ", 1)
        if digest(FROZEN / name) != expected:
            raise ValueError(f"Frozen file changed: {name}")
    for name, content in checkpoint.load_sources().items():
        if (STUDY / "sources/harness" / name).read_bytes() != content:
            raise ValueError(f"Harness built-in snapshot changed: {name}")


def family(note):
    blocks = re.findall(r"^\x60{3}python\n(.*?)^\x60{3}$", note, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError("Study requires one Python block per note")
    imports = {(node.module, item.name) for node in ast.walk(ast.parse(blocks[0]))
               if isinstance(node, ast.ImportFrom) for item in node.names}
    apis = {name for module, name in imports if (module, name) in {
        ("sklearn.cluster", "KMeans"), ("sklearn.preprocessing", "OneHotEncoder")}}
    if len(apis) != 1:
        raise ValueError(f"Expected one supported API, found {apis}")
    return apis.pop()


def sources(api):
    kind = "harness" if api == "KMeans" else "batch"
    versions = ("1.1.3", "1.4.2")
    filenames = ("sklearn-1.1.md", "sklearn-1.4.md") if kind == "harness" else (
        "sklearn-1.1.3.md", "sklearn-1.4.2.md")
    return {side: dict(name="scikit-learn", version=version, filename=filename,
                       content=(STUDY / "sources" / kind / filename).read_text())
            for side, version, filename in zip(("before", "after"), versions, filenames)}


def server_requests(log, offset, calls):
    # llama.cpp flushes an access line at response completion. Give it time to land.
    for _ in range(40):
        log.seek(offset)
        lines = [line.strip() for line in log.read().splitlines()
                 if "request: POST /v1/chat/completions " in line]
        if len(lines) >= len(calls):
            break
        time.sleep(.05)
    if len(lines) != len(calls):
        raise RuntimeError(f"Model audit recorded {len(calls)} requests, server logged {len(lines)}")
    return lines


def run_one(path, mode, log):
    note = path.read_text()
    api = family(note)
    pair = sources(api)
    offset = log.tell()
    error = None
    raw = None
    with model_audit.capture() as calls:
        try:
            if api == "KMeans":
                raw = harness.run(dict(filename=path.name, current=note, revision=0,
                                       intentMode=mode, librarySources=pair))
                status = raw["status"]
                if status == "complete":
                    action = "edit" if raw["proposed"] is not None else "keep"
                elif status == "question":
                    action = "ask"
                else:
                    action = status
            else:
                raw = library.investigate_batch_note(dict(filename=path.name, content=note, **pair))
                action = raw["status"]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            action = "error"
    http = server_requests(log, offset, calls)
    if (mode == "rule" or api == "OneHotEncoder") and calls:
        raise RuntimeError("Unexpected model invocation on shared rule path")
    return dict(id=path.stem, family=api, mode=mode, action=action, raw=raw, error=error,
                modelCalls=calls, serverAccess=http)


def score(records):
    cases = {case["id"]: case for case in json.loads((FROZEN / "gold.json").read_text())}
    summary = {}
    for mode in ("rule", "model"):
        counts = Counter(dict(total=0, actionCorrect=0, correctWithPatch=0, exactEdits=0,
                              validEdits=0, expectedEdits=0, incorrectProposals=0, missedEdits=0,
                              unnecessaryQuestions=0, missedQuestions=0, blocked=0, errors=0,
                              notesWithCalls=0, modelCalls=0, serverRequests=0))
        rows = [r for r in records if r["mode"] == mode]
        if len(rows) != len(cases) or {r["id"] for r in rows} != set(cases):
            raise ValueError("Unpaired corpus")
        for r in rows:
            case = cases[r["id"]]
            if r["family"] != case["family"]:
                raise ValueError("Gold and input disagree on API")
            original = (FROZEN / case["note"]).read_text()
            expected, action = case["expected"], r["action"]
            proposed = (r["raw"] or {}).get("proposed")
            exact = valid = False
            if expected == "edit":
                if original.count(case["old"]) != 1:
                    raise ValueError(f"Ambiguous edit target in {r['id']}")
                exact = proposed == original.replace(case["old"], case["replacement"])
                valid = exact or (r["family"] == "KMeans" and
                                  verified_edit(original, proposed, case["targetNInit"]))
            correct = action == expected and (valid if expected == "edit" else proposed is None)
            r["score"] = dict(expected=expected, actionCorrect=action == expected,
                              exactEdit=exact if expected == "edit" else None,
                              validEdit=valid if expected == "edit" else None, correct=correct)
            counts.update(dict(total=1, actionCorrect=action == expected, correctWithPatch=correct,
                expectedEdits=expected == "edit", exactEdits=action == "edit" and exact,
                validEdits=action == "edit" and valid, incorrectProposals=proposed is not None and not valid,
                missedEdits=expected == "edit" and not (action == "edit" and valid),
                unnecessaryQuestions=action == "ask" and expected != "ask",
                missedQuestions=expected == "ask" and action != "ask", blocked=action == "blocked",
                errors=action == "error", notesWithCalls=bool(r["modelCalls"]),
                modelCalls=len(r["modelCalls"]), serverRequests=len(r["serverAccess"])))
        summary[mode] = dict(counts)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-log", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--port", type=int, default=18087)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_inputs()
    if digest(args.weights) != MODEL_SHA:
        raise ValueError("Reference Qwen weights differ")
    base = f"http://127.0.0.1:{args.port}/v1"
    os.environ.update(HARNESS_PLANNER="offline", HARNESS_INTENT_BASE_URL=base,
                      HARNESS_INTENT_MODEL="notes-qwen-3b", HARNESS_INTENT_API_KEY="",
                      HARNESS_CHECKPOINT_KEY=secrets.token_hex(32))
    started = datetime.now(timezone.utc).isoformat()
    records = []
    with args.server_log.open(errors="replace") as log:
        log.seek(0, 2)
        for note in sorted((FROZEN / "notes").glob("*.md")):
            for mode in ("rule", "model"):
                row = run_one(note, mode, log)
                records.append(row)
                print(note.stem, mode, row["action"], len(row["serverAccess"]), flush=True)
    summary = score(records)
    report = dict(startedUtc=started, finishedUtc=datetime.now(timezone.utc).isoformat(),
                  engineCommit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  python=sys.version.split()[0], frozenManifestSha256=MANIFEST,
                  sourcesSha256={str(p.relative_to(STUDY)): digest(p) for p in sorted((STUDY / "sources").glob("*/*"))},
                  model="notes-qwen-3b", weightsSha256=MODEL_SHA, planner="offline", endpoint=base,
                  summary=summary, records=records)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
