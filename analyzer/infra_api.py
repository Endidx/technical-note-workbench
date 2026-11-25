from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import infra

router = APIRouter(prefix="/infra")


class Original(BaseModel):
    content: str = Field(max_length=infra.MAX_BYTES)


class Digest(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JobHint(BaseModel):
    jobId: int = Field(gt=0)
    generation: int = Field(gt=0)


def operate(action, *args):
    try:
        return action(*args)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "资料库存储或队列暂不可用，请检查服务连接") from exc


@router.post("/archive")
def archive(item: Original):
    return {"sha256": operate(infra.archive, operate(infra.object_store), item.content)}


@router.post("/restore")
def restore(item: Digest):
    return {"content": operate(infra.restore, operate(infra.object_store), item.sha256)}


@router.post("/enqueue")
def enqueue(item: JobHint):
    operate(infra.publish, item.jobId, item.generation)
    return {"queued": True}


@router.post("/dequeue")
def dequeue():
    return operate(infra.receive)
