FROM python:3.12-slim
WORKDIR /app
COPY analyzer/requirements.txt analyzer/requirements.txt
RUN pip install --no-cache-dir -r analyzer/requirements.txt
ARG LIBRARY_ONNX=0
COPY analyzer/requirements-onnx.txt analyzer/requirements-onnx.txt
RUN if [ "$LIBRARY_ONNX" = 1 ]; then pip install --no-cache-dir -r analyzer/requirements-onnx.txt; fi
COPY analyzer analyzer
COPY examples examples
RUN mkdir -p /app/data && chown nobody /app/data && chmod 700 /app/data
USER nobody
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "analyzer.api:app", "--host", "0.0.0.0", "--port", "8000"]
