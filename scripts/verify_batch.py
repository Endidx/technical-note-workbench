"""Replay a five-note migration against an isolated local workbench database."""
import io
import json
from pathlib import Path
import socket
import tempfile
import time
from urllib.request import urlopen
from zipfile import ZipFile

from verify_recovery import ROOT, request, workbench

FIXTURES = ROOT / "examples/batch-upgrade"


def import_materials(base):
    notes = [{"filename": path.name, "content": path.read_text(encoding="utf-8")}
             for path in sorted((FIXTURES / "notes").glob("*.md"))]
    for version in ("1.1.3", "1.4.2"):
        path = FIXTURES / "sources" / f"sklearn-{version}.md"
        source = dict(name="scikit-learn", version=version, filename=path.name,
                      content=path.read_text(encoding="utf-8"))
        job = request(base + "/api/library/import",
                      dict(notes=notes if version == "1.1.3" else [], source=source))
        for _ in range(160):
            overview = request(base + "/api/library")
            if overview.get("activeGeneration") == job["generation"]:
                break
            time.sleep(.25)
        else:
            raise AssertionError(f"index timed out: {job}")
    return job["generation"], {n["filename"]: n["content"] for n in notes}


def replay(base):
    generation, original = import_materials(base)
    api = base + "/api/library/batches"
    batch = request(api, dict(instruction="帮我更新到目标版本", generation=generation,
                              name="scikit-learn", fromVersion="1.1.3", toVersion="1.4.2"))
    task = api + "/" + str(batch["id"])
    for _ in range(240):
        page = request(task)
        if page["status"] in {"complete", "failed"}:
            break
        time.sleep(.25)
    assert page["status"] == "complete", page
    rows = {r["filename"]: r for r in page["items"]}
    expected = {"01-config.md": "ask", "02-clustering.md": "edit", "03-features.md": "edit",
                "04-ready.md": "keep", "05-stats.md": "irrelevant"}
    assert {name: row["status"] for name, row in rows.items()} == expected, page
    assert rows["01-config.md"]["question"] and rows["03-features.md"]["evidence"], page
    assert "n_init=10" in rows["02-clustering.md"]["proposed"].replace(" ", ""), page
    updated = original["03-features.md"].replace("sparse=False", "sparse_output=False")
    assert rows["03-features.md"]["proposed"] == updated
    accept = task + "/items/" + str(rows["03-features.md"]["id"]) + "/accept"
    # A single approval must not apply the other pending suggestion.
    request(accept, {})
    with urlopen(task + "/export", timeout=15) as response, ZipFile(io.BytesIO(response.read())) as zipfile:
        assert len(zipfile.namelist()) == len(original)
        for name, text in original.items():
            assert zipfile.read(name).decode() == (updated if name == "03-features.md" else text)
    print(json.dumps(expected, ensure_ascii=False), "ZIP verified")


if __name__ == "__main__":
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as temporary:
        with workbench(port, temporary, "http://127.0.0.1:1/v1") as (_, base):
            replay(base)
