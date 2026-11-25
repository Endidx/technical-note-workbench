"""Internal Compose adapters; the SQL job row remains authoritative after delivery."""
import hashlib
import io
import json
import os
import re
from contextlib import contextmanager
from functools import lru_cache

BUCKET = "note-originals"
QUEUE = "note-index-jobs"
MAX_BYTES = 2 * 1024 * 1024


@lru_cache(maxsize=1)
def object_store():
    from minio import Minio
    from minio.error import S3Error
    from urllib3 import PoolManager, Timeout

    client = Minio(os.environ["LIBRARY_MINIO_ENDPOINT"],
                   access_key=os.environ["LIBRARY_MINIO_USER"],
                   secret_key=os.environ["LIBRARY_MINIO_PASSWORD"],
                   secure=os.getenv("LIBRARY_MINIO_TLS") == "true",
                   http_client=PoolManager(timeout=Timeout(connect=2, read=5), retries=False))
    if not client.bucket_exists(BUCKET):
        try:
            client.make_bucket(BUCKET)
        except S3Error as error:
            if error.code != "BucketAlreadyOwnedByYou":
                raise
    return client


def archive(client, content):
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("文件超过归档大小限制")
    digest = hashlib.sha256(data).hexdigest()
    client.put_object(BUCKET, digest, io.BytesIO(data), len(data), content_type="text/markdown; charset=utf-8")
    return digest


def restore(client, digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("归档标识无效")
    response = client.get_object(BUCKET, digest)
    try:
        data = response.read(MAX_BYTES + 1)
    finally:
        response.close()
        response.release_conn()
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise OSError("归档原文未通过完整性校验")
    return data.decode("utf-8")


@contextmanager
def channel():
    import pika
    settings = pika.ConnectionParameters(host=os.environ["LIBRARY_RABBIT_HOST"],
        credentials=pika.PlainCredentials(os.environ["LIBRARY_RABBIT_USER"], os.environ["LIBRARY_RABBIT_PASSWORD"]),
        connection_attempts=1, socket_timeout=2, stack_timeout=4, blocked_connection_timeout=3)
    connection = pika.BlockingConnection(settings)
    try:
        ch = connection.channel()
        ch.queue_declare(queue=QUEUE, durable=True)
        yield ch
    finally:
        if connection.is_open:
            connection.close()


def publish(job_id, generation):
    import pika
    body = json.dumps({"jobId": job_id, "generation": generation}).encode()
    with channel() as ch:
        ch.confirm_delivery()
        ch.basic_publish(exchange="", routing_key=QUEUE, body=body, mandatory=True,
                         properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"))


def receive():
    with channel() as ch:
        method, _, body = ch.basic_get(queue=QUEUE, auto_ack=False)
        if method is None:
            return {}
        try:
            hint = json.loads(body)
            if not isinstance(hint, dict) or any(type(hint.get(k)) != int or hint[k] < 1
                                                  for k in ("jobId", "generation")):
                raise ValueError("队列任务标识无效")
        except (UnicodeError, ValueError):
            ch.basic_reject(method.delivery_tag, requeue=False)
            raise
        # This is a wake-up hint: a lost HTTP response is covered by the DB lease scan.
        ch.basic_ack(method.delivery_tag)
        return hint
