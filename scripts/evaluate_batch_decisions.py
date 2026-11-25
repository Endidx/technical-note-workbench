"""Replay prelabelled notes through the public batch operation of a chosen checkout."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "examples/batch-decisions/cases.json"
SOURCES = ROOT / "examples/batch-upgrade/sources"


def source(version):
    filename = f"sklearn-{version}.md"
    return dict(name="scikit-learn", version=version, filename=filename,
                content=(SOURCES / filename).read_text(encoding="utf-8"))


def evaluate(engine):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    versions = dict(before=source("1.1.3"), after=source("1.4.2"))
    rows = []
    for case in cases:
        note = case["note"]
        payload = dict(filename=case["id"] + ".md", content=note, **versions)
        run = subprocess.run([sys.executable, "-B", "-m", "analyzer.library", "investigate_batch_note"],
                             cwd=engine, input=json.dumps(payload), text=True, capture_output=True, check=True)
        result = json.loads(run.stdout)
        expected_patch = None
        if case["expected"] == "edit":
            assert note.count(case["old"]) == 1, case["id"]
            expected_patch = note.replace(case["old"], case["replacement"])
        exact = result["proposed"] == expected_patch
        question = result.get("question", "")
        sufficient = all(token in question for token in case.get("questionIncludes", []))
        rows.append(dict(id=case["id"], expected=case["expected"], actual=result["status"],
                         proposed=result["proposed"] is not None,
                         exactProposal=exact, questionMatches=sufficient,
                         correct=result["status"] == case["expected"] and exact and sufficient))
    return dict(casesSha256=sha256(CASES.read_bytes()).hexdigest(),
                batchNoteSha256=sha256((engine / "analyzer/batch_note.py").read_bytes()).hexdigest(),
                total=len(rows), correct=sum(r["correct"] for r in rows),
                correctStatuses=sum(r["expected"] == r["actual"] for r in rows),
                expectedEdits=sum(r["expected"] == "edit" for r in rows),
                exactEdits=sum(r["expected"] == "edit" and r["actual"] == "edit" and r["exactProposal"]
                               for r in rows),
                incorrectProposals=sum(r["proposed"] and not r["exactProposal"] for r in rows),
                rows=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    report = evaluate(options.engine_root.resolve())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if options.check and report["correct"] != report["total"]:
        sys.exit(1)
