#!/bin/sh
# Reproduce the reference run locally. Keep all downloads outside the source tree tracked by Git.
set -eu
cd "$(dirname "$0")/.."
cache="$PWD/.runtime/benchmark"
mkdir -p "$cache"
download() {
  url=$1 path=$2 digest=$3
  if [ ! -f "$path" ]; then
    partial=$(mktemp "$cache/download.XXXXXX")
    trap 'rm -f "$partial"' EXIT
    curl --fail --location --retry 2 "$url" -o "$partial"
    check "$partial" "$digest"
    mv "$partial" "$path"
    trap - EXIT
  fi
  check "$path" "$digest"
}
check() {
  python3 - "$1" "$2" <<'PY'
import hashlib, sys
digest = hashlib.sha256()
with open(sys.argv[1], 'rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
if digest.hexdigest() != sys.argv[2]:
    sys.exit("SHA-256 mismatch: " + sys.argv[1])
PY
}
server=${LLAMA_SERVER:-}
if [ -z "$server" ]; then
  if [ "$(uname -sm)" = 'Darwin arm64' ]; then
    download 'https://github.com/ggml-org/llama.cpp/releases/download/b6650/llama-b6650-bin-macos-arm64.zip' "$cache/llama.zip" 2d64805aa38c04687dbac6bb3245af5b800cfc1823f3c385473348a7de785404
    unzip -oq "$cache/llama.zip" -d "$cache"
    server="$cache/build/bin/llama-server"
  else
    server=$(command -v llama-server) || { echo 'Install llama.cpp b6650 and set LLAMA_SERVER to the llama-server executable.' >&2; exit 1; }
  fi
fi
case "${1:-0.5b}" in
  0.5b)
    download 'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf?download=true' "$cache/model.gguf" 74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
    weights="$cache/model.gguf"
    alias=notes-qwen
    port=18086
    ;;
  3b)
    download 'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/7dabda4d13d513e3e842b20f0d435c732f172cbe/qwen2.5-3b-instruct-q4_k_m.gguf?download=true' "$cache/intent-3b.gguf" 626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d
    weights="$cache/intent-3b.gguf"
    alias=notes-qwen-3b
    port=18087
    ;;
  *) echo 'Usage: start-eval-model.sh [0.5b|3b]' >&2; exit 2 ;;
esac
exec "$server" -m "$weights" --alias "$alias" --host 127.0.0.1 --port "$port" -c 8192 --jinja --temp 0 --seed 42
