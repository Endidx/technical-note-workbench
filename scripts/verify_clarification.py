"""Verify that supplying missing evidence affects only the reviewed ZIP entry."""
import io
import socket
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

from verify_batch import import_materials
from verify_recovery import request, workbench


def verify(base):
    generation, notes = import_materials(base)
    url = base + "/api/library/batches"
    job = request(url, dict(generation=generation, name="scikit-learn", fromVersion="1.1.3",
                            toVersion="1.4.2", instruction="帮我更新到目标版本"))
    url += "/" + job["id"]
    for _ in range(200):
        report = request(url)
        if report["status"] in ("complete", "failed"):
            break
        time.sleep(.2)
    assert report["status"] == "complete", report
    by_name = {item["filename"]:item for item in report["items"]}
    name = "01-config.md"
    question = by_name[name]
    assert question["status"] == "ask", question
    item = url + "/items/" + question["id"]
    step = dict(draft=notes[name] + "\n配置值待维护者确认。\n", revision=0)
    unresolved = request(item + "/clarify", step)
    assert unresolved["status"] == "ask" and unresolved["clarificationRevision"] == 1
    try:
        request(item + "/clarify", step)
    except HTTPError as conflict:
        assert conflict.code == 409
    else:
        raise AssertionError("Stale answer overwrote a newer investigation")
    draft = notes[name].replace("encoder = ", 'encoder_options = {"sparse": False}\nencoder = ')
    resolved = request(item + "/clarify", dict(draft=draft, revision=1))
    expected = draft.replace('"sparse":', '"sparse_output":')
    assert resolved["status"] == "edit" and resolved["proposed"] == expected, resolved

    def exported():
        with urlopen(url + "/export") as stream, ZipFile(io.BytesIO(stream.read())) as files:
            return {f:files.read(f).decode() for f in files.namelist()}

    assert exported() == notes
    request(item + "/accept", {})
    assert exported() == {**notes, name:expected}
    print("Passed: unanswered → follow-up → stale reply rejected → evidenced edit → selective ZIP export.")


if __name__ == "__main__":
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as directory:
        with workbench(port, directory, "http://127.0.0.1:1/v1") as (_, base):
            verify(base)
