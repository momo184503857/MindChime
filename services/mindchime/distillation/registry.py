"""Local, trusted strategies. Imported packages never register executable code."""

from dataclasses import asdict, dataclass
from importlib import import_module
from pkgutil import iter_modules


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    instruction: str
    mode: str = "report"  # extract, report, audit, test, repair


@dataclass(frozen=True)
class Method:
    id: str
    name: str
    description: str
    cost: str
    upstream: str
    upstream_version: str
    stages: tuple[Stage, ...]
    version: str = "1.0.0"
    license: str = "MIT"

    def manifest(self):
        return {
            **asdict(self),
            "stages": [asdict(stage) for stage in self.stages],
            "external_sources": False,
            "adaptation": "MindChime 书内适配；独立串行阶段，不自动搜索、安装或发布。模型评审不等于事实认证。",
        }


def methods():
    from . import methods as package

    return {
        m.METHOD.id: m.METHOD
        for item in iter_modules(package.__path__)
        if not item.name.startswith("_") and (m := import_module(f"{package.__name__}.{item.name}"))
    }


def get_method(id):
    method = methods().get(id)
    if method is None:
        raise ValueError("未知蒸馏方法，请重新选择。")
    return method
