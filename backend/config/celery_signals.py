"""Carry the request id across the Celery boundary.

``before_task_publish`` runs in the web process with the request's contextvar still bound,
so the id is copied into the message headers. ``task_prerun`` runs in the worker, where
Celery exposes custom headers as attributes on ``task.request``; the id is rebound there so
every log line the task emits shares it with the request that enqueued the work.

Eager execution (``CELERY_TASK_ALWAYS_EAGER``) never publishes, but it also never leaves the
thread, so the contextvar is simply inherited and these handlers are harmless no-ops.
"""
from celery.signals import before_task_publish, task_postrun, task_prerun

from config.request_id import get_request_id, reset_request_id, set_request_id

HEADER = "spaceworks_request_id"
_TOKEN_ATTR = "_spaceworks_request_id_token"


@before_task_publish.connect
def propagate_request_id(headers=None, **_kwargs):
    request_id = get_request_id()
    if request_id and headers is not None:
        headers.setdefault(HEADER, request_id)


def _header_from_task(task):
    request = getattr(task, "request", None)
    if request is None:
        return None
    value = getattr(request, HEADER, None)
    if value:
        return value
    raw_headers = getattr(request, "headers", None) or {}
    return raw_headers.get(HEADER) if isinstance(raw_headers, dict) else None


@task_prerun.connect
def bind_request_id(task=None, **_kwargs):
    request_id = _header_from_task(task)
    if request_id:
        setattr(task.request, _TOKEN_ATTR, set_request_id(request_id))


@task_postrun.connect
def unbind_request_id(task=None, **_kwargs):
    request = getattr(task, "request", None)
    token = getattr(request, _TOKEN_ATTR, None) if request is not None else None
    if token is not None:
        reset_request_id(token)
        delattr(request, _TOKEN_ATTR)
