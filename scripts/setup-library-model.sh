#!/bin/sh
# Prepare the pinned multilingual encoder. The workbench never downloads models on import.
set -eu
cd "$(dirname "$0")/.."
encoder_python="${PYTHON:-python3}"
"$encoder_python" -c 'import sys; assert sys.version_info >= (3,10), "Select Python 3.10+ with PYTHON=/path/to/python"'
mkdir -p .runtime/library-model
if [ ! -x .runtime/library-python/bin/python ]; then
  "$encoder_python" -m venv .runtime/library-python
fi
.runtime/library-python/bin/python -m pip install -r analyzer/requirements-onnx.txt
base=https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/resolve/2c4055b12046f11709e9df2c122e59ffbdc2f900
fetch_model_file() {
  src=$1
  dst=.runtime/library-model/$2
  digest=$3
  if [ -f "$dst" ] && "$encoder_python" -c 'import hashlib, pathlib, sys; sys.exit(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()!=sys.argv[2])' "$dst" "$digest"; then
    return
  fi
  curl -fL --retry 2 "$base/$src" -o "$dst.part"
  "$encoder_python" -c 'import hashlib, pathlib, sys; assert hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()==sys.argv[2], "checksum mismatch"' "$dst.part" "$digest"
  mv "$dst.part" "$dst"
}
fetch_model_file onnx/model_quantized.onnx model.onnx 66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc
fetch_model_file tokenizer.json tokenizer.json b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441
