"""Crash/restart a disposable JVM, then race two approvals. Run after mvn package."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "backend/target/review-0.1.0.jar"
NOTE = "/api/notes/01-baseline/harness"


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


@contextmanager
def workbench(port, directory, model_url):
    bundled = ROOT / ".runtime/amazon-corretto-17.jdk/Contents/Home/bin/java"
    java = os.path.join(os.environ["JAVA_HOME"], "bin/java") if os.getenv("JAVA_HOME") else (
        str(bundled) if bundled.exists() else shutil.which("java"))
    if not java or not JAR.exists():
        raise SystemExit("Build backend/target/review-0.1.0.jar and provide Java 17 first.")
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, HARNESS_PLANNER="remote", HARNESS_MODEL="test-planner",
               HARNESS_BASE_URL=model_url, HARNESS_API_KEY="", HARNESS_CHECKPOINT_KEY="disposable-test-key-" * 3)
    db = f"jdbc:h2:file:{directory}/notes;MODE=MySQL;WRITE_DELAY=0"
    with open(Path(directory) / "server.log", "ab") as log:
        proc = subprocess.Popen([java, "-jar", str(JAR), f"--server.port={port}",
                                 f"--spring.datasource.url={db}"], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            for _ in range(150):
                if proc.poll() is not None:
                    raise RuntimeError(Path(log.name).read_text()[-4000:])
                try:
                    request(base + "/api/notes")
                    break
                except URLError:
                    time.sleep(.1)
            else:
                raise RuntimeError("Temporary workbench did not start.")
            yield proc, base
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=15)


def verify():
    entered_third_call = threading.Event()
    release_call = threading.Event()

    class Planner(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            trace = json.loads(body["messages"][-1]["content"])
            if len(trace) == 2 and not release_call.is_set():
                entered_third_call.set()
                release_call.wait(12)
            tool = body["tools"][0]["function"]["name"]
            reply = {"choices": [{"message": {"tool_calls": [{"type": "function",
                     "function": {"name": tool, "arguments": "{}"}}]}}]}
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(json.dumps(reply).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with ThreadingHTTPServer(("127.0.0.1", 0), Planner) as provider, tempfile.TemporaryDirectory() as directory:
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        model = f"http://127.0.0.1:{provider.server_port}/v1"
        with workbench(port,directory,model) as (process, base):
            # Read the client's committed SSE steps before killing the JVM mid-request.
            req=Request(base+NOTE+"/stream", data=b'{"revision":0}',headers={"Content-Type":"application/json"})
            with urlopen(req,timeout=15) as stream:
                steps=[]
                for line in stream:
                    if line.startswith(b"data:"):
                        event=json.loads(line[5:])
                        assert event["type"]=="step", event
                        steps.append(event["step"]["tool"])
                        if len(steps)==2:
                            break
                assert entered_third_call.wait(6), "Third tool selection never started."
                process.kill()
                process.wait(timeout=8)
                release_call.set()
        with workbench(port,directory,model) as (_,base):
            saved=request(base+NOTE)
            assert saved["status"]=="paused" and [s["tool"] for s in saved["trace"]]==steps, saved
            req=Request(base+NOTE+"/stream", data=b'{"revision":0}',headers={"Content-Type":"application/json"})
            with urlopen(req,timeout=15) as stream:
                events=[json.loads(line[5:]) for line in stream if line.startswith(b"data:")]
            new=[e["step"]["tool"] for e in events if e["type"]=="step"]
            final=events[-1]["result"]
            assert new==["read_intent","submit_result"] and final["status"]=="complete", events
            assert [s["tool"] for s in final["trace"]]==steps+new
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                replies=list(pool.map(lambda _:request(base+NOTE+"/apply",{"revision":0}),range(2)))
            receipts=[r["approvalReceipt"] for r in replies]
            assert sorted(r["replayed"] for r in receipts)==[False,True],receipts
            assert all((r["fromRevision"],r["toRevision"])==(0,1) for r in receipts)
        with workbench(port,directory,model) as (_,base):
            replay=request(base+NOTE+"/apply",{"revision":0})
            assert replay["approvalReceipt"]["replayed"] and replay["revision"]==1
            assert replay["current"].count("n_init=10")==1
        provider.shutdown()
    print("PASS: killed JVM after two durable steps; completed two remaining steps; concurrent and post-restart approvals wrote one revision.")


if __name__=="__main__":
    verify()
