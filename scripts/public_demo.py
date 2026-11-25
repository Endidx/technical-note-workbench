"""Build the public-case review snapshot, keeping provenance out of the Harness input."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analyzer.engine import analyze_note


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "examples/benchmark-public-migrations")
    directory = parser.parse_args().dataset
    rows = []
    for source in json.loads((directory / "sources.json").read_text(encoding="utf-8")):
        path = directory / "notes" / (source["id"] + ".md")
        try:
            row = analyze_note(path)
        except ValueError as exc:
            # The fixed-flow demo supports fewer call shapes than the Harness.
            original = path.read_text(encoding="utf-8")
            row = dict(id=path.stem, title=original.splitlines()[0].removeprefix("# "),
                       filename=path.name, original=original, proposed=None, kind="unsupported",
                       reason=f"固定流程无法处理这篇笔记，可切换到 Agent 调查。{exc}", evidence="")
        row["provenance"] = {key: source[key] for key in ("repo", "parentPermalink", "commitUrl", "inputMode")}
        rows.append(row)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
