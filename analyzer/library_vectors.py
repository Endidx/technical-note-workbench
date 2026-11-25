"""Offline sentence-vector selection and version-scoped Qdrant REST transport."""

import hashlib
import json
import math
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from .library_text import features

DIM = 384
COLLECTION = "/collections/note_workbench_384_v1"


def encoder():
    selected = os.getenv("LIBRARY_ENCODER", "concept")
    if selected == "onnx":
        from . import library_onnx

        return library_onnx.identity()
    if selected == "concept":
        return "concept-hash-v1"
    raise ValueError("LIBRARY_ENCODER 仅支持 concept 和 onnx")


def encode(texts):
    if encoder() != "concept-hash-v1":
        from . import library_onnx

        rows = library_onnx.encode(texts)
        if len(rows) != len(texts):
            raise ValueError("本地编码器返回的向量数量错误")
    else:
        rows = []
        for text in texts:
            row = [0.0] * DIM
            for term, weight in features(text).items():
                digest = hashlib.blake2s(term.encode(), digest_size=8).digest()
                pos = int.from_bytes(digest[:4], "big") % DIM
                row[pos] += weight if digest[4] & 1 else -weight
            rows.append(row)
    normalized = []
    for row in rows:
        if len(row) != DIM or not all(math.isfinite(v) for v in row):
            raise ValueError("本地编码器需要 384 维有限向量")
        norm = math.sqrt(sum(v * v for v in row)) or 1.0
        normalized.append([round(float(v) / norm, 8) for v in row])
    return normalized


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Qdrant:
    def __init__(self, base):
        url = urlsplit(base)
        if (
            url.scheme not in ("http", "https")
            or url.hostname not in ("127.0.0.1", "::1", "localhost", "qdrant")
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Qdrant 地址只允许本机或 Compose 内部的 qdrant 服务")
        self.base = base.rstrip("/") + COLLECTION
        self.client = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, method, path="", body=None, allow=()):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(
            self.base + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with self.client.open(req, timeout=12) as response:
                return json.load(response)["result"]
        except HTTPError as exc:
            if exc.code in allow:
                return None
            raise RuntimeError(f"Qdrant 请求失败，HTTP {exc.code}") from exc
        except (KeyError, OSError, URLError, ValueError) as exc:
            raise RuntimeError("无法访问或解析 Qdrant 服务") from exc

    @staticmethod
    def point_id(scope, key):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "note-workbench/" + scope + "/" + key))

    def marker(self, scope):
        return self.call("GET", "/points/" + self.point_id(scope, "published"), allow=(404,))

    def populate(self, scope, rows):
        if self.call("GET", allow=(404,)) is None:
            self.call("PUT", body={"vectors": {"size": DIM, "distance": "Cosine"}}, allow=(409,))
        if self.marker(scope):
            return
        for start in range(0, len(rows), 64):
            points = [
                {
                    "id": self.point_id(scope, str(i)),
                    "vector": row["vector"],
                    "payload": {"generation": scope, "row": i, "kind": "chunk"},
                }
                for i, row in enumerate(rows[start : start + 64], start)
            ]
            self.call("PUT", "/points?wait=true", {"points": points})
        marker = {
            "id": self.point_id(scope, "published"),
            "vector": [0.0] * DIM,
            "payload": {"generation": scope, "kind": "marker"},
        }
        self.call("PUT", "/points?wait=true", {"points": [marker]})

    def scores(self, scope, vector, count):
        if not self.marker(scope):
            raise RuntimeError("当前资料代次尚未完成向量发布")
        if not count:
            return {}
        must = [{"key": k, "match": {"value": v}} for k, v in (("generation", scope), ("kind", "chunk"))]
        result = self.call(
            "POST",
            "/points/query",
            {
                "query": vector,
                "filter": {"must": must},
                "with_payload": ["row"],
                "params": {"exact": True},
                "limit": min(count, 128),
            },
        )
        return {r["payload"]["row"]: r["score"] for r in result["points"]}
