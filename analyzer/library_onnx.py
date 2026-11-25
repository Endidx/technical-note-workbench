"""Local 384-dimensional multilingual MiniLM, mean-pooled with the attention mask."""
import hashlib
import os
from functools import lru_cache
from pathlib import Path

REVISION = "2c4055b12046f11709e9df2c122e59ffbdc2f900"
FILES = {
    "model.onnx": "66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc",
    "tokenizer.json": "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441",
}


@lru_cache(maxsize=2)
def checked_model(directory):
    root = Path(directory)
    for filename, expected in FILES.items():
        digest = hashlib.sha256()
        with (root / filename).open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"向量模型文件校验失败：{filename}")
    return root


def identity():
    return "multilingual-minilm-l12:" + REVISION + ":int8-mean128-v1"


@lru_cache(maxsize=1)
def runtime(directory):
    import onnxruntime as ort
    from tokenizers import Tokenizer

    root = checked_model(directory)
    tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=128)
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
    settings = ort.SessionOptions()
    settings.intra_op_num_threads = 2
    settings.inter_op_num_threads = 1
    session = ort.InferenceSession(str(root / "model.onnx"), settings, providers=["CPUExecutionProvider"])
    return tokenizer, session


def encode(texts):
    import numpy as np

    directory = os.getenv("LIBRARY_MODEL_DIR") or str(Path(__file__).resolve().parents[1] / ".runtime/library-model")
    tokenizer, session = runtime(directory)
    vectors = []
    for offset in range(0, len(texts), 12):
        batch = tokenizer.encode_batch(texts[offset:offset + 12])
        ids = np.asarray([row.ids for row in batch], dtype=np.int64)
        mask = np.asarray([row.attention_mask for row in batch], dtype=np.int64)
        inputs = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        hidden = session.run(None, {field.name: inputs[field.name] for field in session.get_inputs()})[0]
        masked = hidden * mask[:, :, None]
        pooled = masked.sum(axis=1) / mask.sum(axis=1, keepdims=True).clip(min=1)
        normalized = pooled / np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-12)
        if normalized.shape != (len(batch), 384) or not np.isfinite(normalized).all():
            raise ValueError("本地模型输出无效")
        vectors.extend(normalized.tolist())
    return vectors
