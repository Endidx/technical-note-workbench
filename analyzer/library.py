"""Version-diff to cited Markdown passages, with lexical, vector and code evidence."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
import sys

from . import batch_note
from . import library_text as text
from . import library_vectors as vectors

MAX_BYTES = 512_000
MAX_CHUNKS = 4000
RRF_K = 60


def content(data):
    value = data.get("content") if isinstance(data, dict) else None
    if not isinstance(value, str) or len(value.encode()) > MAX_BYTES:
        raise ValueError("Markdown 文本不能为空类型，单篇最多 512 KB")
    return value


def filename(data):
    name = data.get("filename") if isinstance(data, dict) else None
    if not isinstance(name, str) or not name or len(name) > 255 or "\x00" in name:
        raise ValueError("需要有效的 Markdown 文件名")
    return name


def index(data):
    name = filename(data)
    original = content(data)
    chunks = text.chunks(original)
    if len(chunks) > MAX_CHUNKS:
        raise ValueError("单篇资料分块过多")
    inputs = [r["heading"] + "\n" + r["text"] for r in chunks]
    embeddings = vectors.encode(inputs)
    calls_by_line = defaultdict(list)
    for lineno, symbol, parameters in text.ast_evidence(original):
        calls_by_line[lineno].append((symbol, parameters))
    for chunk, embedding, passage in zip(chunks, embeddings, inputs):
        calls, keywords = set(), set()
        for lineno in range(chunk["startLine"], chunk["endLine"] + 1):
            for symbol, parameters in calls_by_line.get(lineno, []):
                calls.add(symbol)
                keywords.update(parameters)
        chunk.update(vector=embedding, calls=sorted(calls), keywords=sorted(keywords),
                     termCounts=dict(Counter(text.tokens(passage))), concepts=text.concepts(passage))
    return {
        "filename": name,
        "encoder": vectors.encoder(),
        "chunks": chunks,
        "contentSha256": hashlib.sha256(original.encode()).hexdigest(),
    }


def rows_and_scope(data):
    if not isinstance(data, dict):
        raise ValueError("请求须为 JSON 对象")
    docs, rows, manifest = data.get("documents"), [], []
    if not isinstance(docs, list) or len(docs) > 500:
        raise ValueError("一次最多检索 500 篇完整索引")
    indexed = set()
    for doc in sorted(docs, key=filename):
        name = filename(doc)
        bundle = doc.get("index")
        if not isinstance(bundle, dict) or bundle.get("encoder") != vectors.encoder():
            raise RuntimeError("资料索引与当前向量编码器不匹配，请重建代次")
        if name in indexed:
            raise ValueError("同一代次的笔记文件名不能重复")
        indexed.add(name)
        chunks = bundle.get("chunks")
        if not isinstance(chunks, list) or len(rows) + len(chunks) > MAX_CHUNKS:
            raise ValueError("索引分块超出范围")
        for row in chunks:
            if (
                not isinstance(row, dict)
                or not {"heading", "text", "startLine", "endLine", "vector", "calls", "keywords"}
                <= row.keys()
            ):
                raise ValueError("索引分块字段不完整")
            v = row["vector"]
            if (
                not isinstance(v, list)
                or len(v) != vectors.DIM
                or not all(isinstance(n, (int, float)) and math.isfinite(n) for n in v)
            ):
                raise ValueError("向量索引尺寸或数值无效")
            rows.append(dict(row, filename=name))
        manifest.append([name, bundle.get("contentSha256"), len(chunks)])
    key = [data.get("workspaceId", "local"), data.get("generation", ""), vectors.encoder(), manifest]
    return rows, hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()


def service():
    base = os.environ.get("LIBRARY_QDRANT_URL")
    return vectors.Qdrant(base) if base else None


def publish(data):
    rows, scope = rows_and_scope(data)
    store = service()
    if store:
        store.populate(scope, rows)
    return {
        "generation": data.get("generation"),
        "chunks": len(rows),
        "backend": "qdrant" if store else "local",
        "encoder": vectors.encoder(),
    }


def vector_distances(change, rows, scope, query, query_terms, q_concepts, row_concepts, pretrained):
    # Old and new clauses often contradict one another. Embedding them separately
    # preserves notes phrased like either version, as well as identifier context.
    query_views = {"条款上下文": query}
    if pretrained:
        for field, label in (("after", "新版条款"), ("before", "旧版条款")):
            if change[field].strip():
                query_views[label] = change[field]
        if len(q_concepts) == 1 and len(query_terms) <= 4:
            # Short option names carry little sentence context. Use the explicit
            # bilingual glossary for this auxiliary view and require a matching
            # concept on the retrieved side before accepting its score.
            concept = next(iter(q_concepts))
            query_views["条款术语·" + concept] = " ".join(text.CONCEPTS[concept])
    store = service()
    distances = {}
    for label, vector in zip(query_views, vectors.encode(list(query_views.values()))):
        scores = (
            store.scores(scope, vector, len(rows))
            if store
            else {i: sum(a * b for a, b in zip(vector, row["vector"])) for i, row in enumerate(rows)}
        )
        for i, score in scores.items():
            if label.startswith("条款术语·") and not q_concepts.intersection(row_concepts[i]):
                continue
            if i not in distances or score > distances[i][0]:
                distances[i] = (score, label)
    return distances


def rank(change, rows, scope, *, channels=frozenset({"BM25", "Vector", "AST"})):
    """Rank passages; internal offline ablations can select production channels."""
    query = "\n".join(change[k] for k in ("heading", "before", "after"))
    query_terms = set(text.tokens(query))
    # Older snapshots predate stored lexical statistics. Hydrate those only.
    words, row_concepts = [], []
    for row in rows:
        if "termCounts" in row and "concepts" in row:
            words.append(row["termCounts"])
            row_concepts.append(set(row["concepts"]))
        else:
            passage = row["heading"] + "\n" + row["text"]
            words.append(Counter(text.tokens(passage)))
            row_concepts.append(set(text.concepts(passage)))
    df = Counter(t for counts in words for t in counts)
    lengths = [sum(freq.values()) for freq in words]
    avg = max(1.0, sum(lengths) / max(len(rows), 1))
    q_concepts = set(text.concepts(query))
    pretrained = vectors.encoder() != "concept-hash-v1"
    distances = (vector_distances(change, rows, scope, query, query_terms, q_concepts, row_concepts, pretrained)
                 if "Vector" in channels else {})
    by_channel = defaultdict(list)
    for i, row in enumerate(rows):
        common = query_terms & words[i].keys()
        lexical = sorted(common, key=lambda t: (df[t], -len(t), t))
        semantic = sorted(q_concepts.intersection(row_concepts[i]))
        meaningful = any(t.isascii() for t in common) or len(common) >= 2 or bool(semantic)
        if "BM25" in channels and lexical and meaningful:
            score = 0.0
            for t in lexical:
                tf = words[i][t]
                idf = math.log1p((len(rows) - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * lengths[i] / avg))
            by_channel["BM25"].append((i, score, lexical[:7]))
        similarity = distances.get(i, (0, "条款上下文"))[0]
        # Concept vectors need genuine shared features, so hash collisions alone cannot retrieve.
        if (pretrained and similarity >= 0.52) or (
            not pretrained and similarity >= 0.16 and (semantic or (lexical and meaningful))
        ):
            terms = (["概念·" + c for c in semantic] + lexical)[:7]
            by_channel["Vector"].append((i, similarity, terms))
        if "AST" in channels:
            exact = sorted(s for s in row["calls"] if s.rsplit(".", 1)[-1].lower() in query_terms)
            named = sorted(w for w in row["keywords"] if w.lower() in query_terms)
            if exact or named:
                by_channel["AST"].append((i, len(exact) * 2 + len(named), exact + named))
    merged = {}
    for channel, records in by_channel.items():
        ordered = sorted(records, key=lambda item: (-item[1], item[0]))[:128]
        previous = None
        for position, (i, score, terms) in enumerate(ordered, 1):
            if previous != score:
                rank_no = position
                previous = score
            if i not in merged:
                merged[i] = dict(
                    {k: rows[i][k] for k in ("filename", "heading", "startLine", "endLine", "text")},
                    score=0.0,
                    channels=[],
                )
            hit = merged[i]
            hit["score"] += 1 / (RRF_K + rank_no)
            entry = dict(name=channel, rank=rank_no, score=round(score, 6), terms=terms)
            if channel == "Vector":
                entry["querySide"] = distances[i][1]
            hit["channels"].append(entry)
    hits = sorted(merged.values(), key=lambda h: (-h["score"], h["filename"], h["startLine"]))[:30]
    for h in hits:
        h["score"] = round(h["score"], 8)
        details = []
        for c in h["channels"]:
            label = {"BM25": "关键词", "Vector": "向量相似", "AST": "Python 调用或参数"}[c["name"]]
            if c["name"] == "Vector":
                label += "（" + c["querySide"] + "）"
            details.append(label + (" · " + "、".join(c["terms"][:3]) if c["terms"] else ""))
        h["reason"] = "；".join(details)
    return hits


def search(data):
    if not isinstance(data, dict):
        raise ValueError("请求须为 JSON 对象")
    changes = text.changes(content(data.get("before")), content(data.get("after")))
    requested = data.get("changeId")
    chosen = (
        next((c for c in changes if c["id"] == requested), None) if requested else next(iter(changes), None)
    )
    if requested and not chosen:
        raise ValueError("条款已变化，请重新选择")
    rows, scope = rows_and_scope(data)
    return {
        "changes": changes,
        "selectedChangeId": chosen["id"] if chosen else None,
        "hits": rank(chosen, rows, scope) if chosen and rows else [],
        "encoder": vectors.encoder(),
    }


def investigate_batch_note(data):
    note, name = content(data), filename(data)
    before, after = data["before"], data["after"]
    for source in (before, after):
        content(source)
        filename(source)
        if not isinstance(source.get("version"), str):
            raise ValueError("需要资料版本")
    return batch_note.investigate(name, note, before, after)


OPERATIONS = {"index": index, "publish": publish, "search": search,
              "investigate_batch_note": investigate_batch_note}
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=OPERATIONS)
    args = parser.parse_args()
    try:
        print(json.dumps(OPERATIONS[args.operation](json.load(sys.stdin)), ensure_ascii=False))
    except (KeyError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, OSError, ImportError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
