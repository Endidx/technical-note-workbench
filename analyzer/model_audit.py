"""Opt-in, request-local collection of model responses for reproducible evaluations."""

from contextlib import contextmanager
from contextvars import ContextVar

_active = ContextVar("model_audit", default=None)


@contextmanager
def capture():
    calls = []
    token = _active.set(calls)
    try:
        yield calls
    finally:
        _active.reset(token)


def record(call):
    records = _active.get()
    if records is not None:
        records.append(call)
