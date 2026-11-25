#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -z "${JAVA_HOME:-}" ] && [ -d .runtime/amazon-corretto-17.jdk/Contents/Home ]; then
  JAVA_HOME="$PWD/.runtime/amazon-corretto-17.jdk/Contents/Home"
  export JAVA_HOME
fi
java="${JAVA_HOME:+$JAVA_HOME/bin/}java"
javac="${JAVA_HOME:+$JAVA_HOME/bin/}javac"
jar=backend/target/review-0.1.0.jar
build=false
if [ ! -f "$jar" ] || [ -n "$(find backend/src/main backend/pom.xml examples/batch-upgrade -newer "$jar" -print -quit)" ]; then
  build=true
fi

java_version=$("$java" -XshowSettings:properties -version 2>&1 | awk '$1 == "java.specification.version" {print $3}')
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null ||
   ! [ "${java_version:-0}" -ge 17 ] 2>/dev/null ||
   { [ "$build" = true ] && ! "$javac" -version >/dev/null 2>&1; }; then
  if [ "$#" -eq 0 ] && command -v docker >/dev/null 2>&1 &&
     docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    exec docker compose up --build
  fi
  echo '本地启动需要 Python 3.9+ 和 JDK 17+。也可以启动 Docker 后运行 docker compose up --build。' >&2
  exit 1
fi

if [ "$build" = true ]; then
  if [ -x .runtime/apache-maven-3.9.9/bin/mvn ]; then
    mvn=.runtime/apache-maven-3.9.9/bin/mvn
  else
    mvn=./backend/mvnw
  fi
  "$mvn" -q -f backend/pom.xml package
fi
# A prepared local model is used entirely on this machine. Fresh checkouts also
# support the small, dependency-free concept encoder.
if [ -x .runtime/library-python/bin/python ] && [ -f .runtime/library-model/model.onnx ] && [ -f .runtime/library-model/tokenizer.json ]; then
  : "${LIBRARY_ENCODER:=onnx}"
  : "${REVIEW_LIBRARY_PYTHON:=$PWD/.runtime/library-python/bin/python}"
  : "${LIBRARY_MODEL_DIR:=$PWD/.runtime/library-model}"
  export LIBRARY_ENCODER REVIEW_LIBRARY_PYTHON LIBRARY_MODEL_DIR
fi
python3 -m analyzer.engine
exec "$java" -jar "$jar" "$@"
