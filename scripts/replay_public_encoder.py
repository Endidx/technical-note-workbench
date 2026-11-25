"""Check the old and updated call shapes of six pinned public encoder migrations."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analyzer.library import OPERATIONS


def run():
    sources = {}
    for side, version in (("before", "1.1.3"), ("after", "1.4.2")):
        f = ROOT / "examples/batch-upgrade/sources" / f"sklearn-{version}.md"
        sources[side] = dict(name="scikit-learn", version=version, filename=f.name, content=f.read_text())
    rows = []
    for record in json.loads((ROOT / "examples/public-encoder/commits.json").read_text()):
        kwargs = ", ".join(f"{key}={value}" for key,value in record["keywords"])
        before = "# 类别特征转换\n\n目标环境为 scikit-learn 1.4.2。\n\n```python\nfrom sklearn.preprocessing import OneHotEncoder as Encoder\nfeatures = Encoder(" + kwargs + ")\n```\n"
        after = before.replace("sparse=", "sparse_output=")
        for side, note, expected in (("before", before, "edit"), ("after", after, "keep")):
            result = OPERATIONS["investigate_batch_note"](dict(filename="encoder.md", content=note, **sources))
            success = result["status"] == expected and result["proposed"] == (after if side == "before" else None)
            rows.append(dict(project=record["project"], source=record[side], expected=expected,passed=success,
                             action=result["status"], evidence=result["evidence"]))
    return dict(independentProjects=len(rows)//2, passed=sum(r["passed"] for r in rows), total=len(rows), rows=rows)


if __name__ == "__main__":
    print(json.dumps(run(),ensure_ascii=False,indent=2))
