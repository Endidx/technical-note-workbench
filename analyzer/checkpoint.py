"""Persistence boundary for an authenticated, revision-bound investigation snapshot."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile

from .engine import ROOT
from .model_intent import model_settings, requested_mode

# Bump for changes to tool semantics, state representation or resume policy.
SCHEMA = "kmeans-review-v18"
SOURCES = ("sklearn-1.1.md", "sklearn-1.4.md")
REFERENCE_SOURCES = ("sklearn-1.0.2.json",)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def signing_key():
    configured = os.environ.get("HARNESS_CHECKPOINT_KEY")
    if configured:
        if len(configured.encode("utf-8")) < 32:
            raise ValueError("检查点签名密钥至少需 32 字节")
        return configured.encode("utf-8")

    path = ROOT / "data" / "harness-checkpoint.key"
    try:
        key = path.read_bytes()
    except FileNotFoundError:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Publish a fully written key atomically; concurrent CLI workers share the winner.
        with tempfile.NamedTemporaryFile(dir=path.parent) as tmp:
            tmp.write(secrets.token_bytes(32))
            tmp.flush()
            os.fsync(tmp.fileno())
            try:
                os.link(tmp.name, path)
            except FileExistsError:
                pass
        key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("检查点签名密钥损坏")
    return key


def load_sources():
    base = ROOT / "examples" / "sources"
    return {name: (base / name).read_bytes() for name in (*SOURCES, *REFERENCE_SOURCES)}


def provenance(data, planner, budget, snapshots):
    versions = {name: hashlib.sha256(content).hexdigest() for name, content in snapshots.items()}
    engine = {"decisionGate":"v14", "planner": planner, "intentMode": requested_mode(data)}
    if engine["intentMode"] == "model":
        engine["intentVerifier"] = "independent-premises-v2"
        engine["intentModel"], engine["intentBase"] = model_settings()
    if planner == "remote":
        engine.update(model=os.getenv("HARNESS_MODEL", ""),
                      base=os.getenv("HARNESS_BASE_URL", "").rstrip("/"))
    return {
        "version": SCHEMA,
        "input_sha256": digest({field: data.get(field) for field in ("filename", "revision", "current", "answer", "configFacts")}),
        "sources_sha256": digest(versions),
        "planner": planner,
        "config_sha256": digest(engine),
        "budget": budget,
    }


def seal(key, origin, state, trace, terminal):
    fields = {name: value for name, value in state.items() if name not in ("input", "snapshots")}
    payload = dict(origin, state=fields, trace=list(trace), terminal=terminal)
    return dict(payload, seal=hmac.digest(key, encoded(payload), "sha256").hex())


def restore(key, origin, saved):
    if not isinstance(saved, dict) or not isinstance(saved.get("seal"), str):
        raise ValueError("检查点格式无效")
    payload = {name: value for name, value in saved.items() if name != "seal"}
    raw = encoded(payload)
    if len(raw) > 1_000_000:
        raise ValueError("检查点超过大小限制")
    expected = hmac.digest(key, raw, "sha256").hex()
    if not hmac.compare_digest(expected.encode(), saved["seal"].encode()):
        raise ValueError("检查点签名无效，请重新开始调查")
    if any(payload.get(k) != v for k, v in origin.items()):
        raise ValueError("检查点与当前笔记、回答、资料版本或规划器配置不匹配")
    trace = payload["trace"]
    if not 1 <= len(trace) <= origin["budget"]:
        raise ValueError("检查点中的步骤数无效")
    return dict(payload["state"]), list(trace), payload["terminal"]
