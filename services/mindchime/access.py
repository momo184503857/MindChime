"""Request/task identity. None is reserved for trusted local maintenance code."""

from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

principal = ContextVar("mindchime_principal", default=None)
PRIVATE_KINDS = {"conversation", "message", "artifact", "run", "memory", "job", "import_preview"}
PUBLIC_KINDS = {
    "source",
    "chapter",
    "card",
    "distillation",
    "person",
    "cognitive_profile",
    "agent",
    "skill",
    "relation",
}
UNAVAILABLE = {"deleted", "deleting", "disabled", "failed", "cleaning", "archived", "draft", "candidate"}


def current():
    return principal.get()


def is_admin():
    actor = current()
    return actor is None or actor["role"] == "admin"


@contextmanager
def identity(actor):
    token = principal.set(actor)
    try:
        yield
    finally:
        principal.reset(token)


def require_admin():
    if not is_admin():
        raise HTTPException(403, "仅管理员可以执行此操作")


def require_owner(record):
    actor = current()
    if actor and record.get("owner_user_id") != actor["id"]:
        raise HTTPException(404, "内容不存在或无权访问")
