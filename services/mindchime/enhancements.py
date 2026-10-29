"""Additional local workflows; mounted by the business app and worker."""
from fastapi import APIRouter
from .extra import artifacts, graph, memory, skills, transfer

router = APIRouter()
for module in (artifacts, graph, memory, skills, transfer):
    router.include_router(module.router)


def register_handlers():
    for module in (artifacts, graph, memory, skills):
        module.register()
