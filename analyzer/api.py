import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from . import harness
from .engine import analyze_all
from .infra_api import router as infra_router
from .library import OPERATIONS

app = FastAPI(title="技术笔记影响分析")
app.include_router(infra_router)


@app.get("/analysis")
def analysis():
    return analyze_all()


def validated(payload):
    try:
        harness.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/harness")
def run_harness(payload: dict):
    validated(payload)
    return harness.run(payload)


@app.post("/harness/stream")
def stream_harness(payload: dict):
    validated(payload)
    chunks = (json.dumps(item, ensure_ascii=False) + "\n" for item in harness.events(payload))
    return StreamingResponse(chunks, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})



@app.post("/library/{operation}")
def library_operation(operation: str, payload: dict):
    if operation not in OPERATIONS:
        raise HTTPException(status_code=404, detail="未知的资料库操作")
    try:
        return OPERATIONS[operation](payload)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
