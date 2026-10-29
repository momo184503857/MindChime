from ..registry import Method, Stage

METHOD = Method(
    "basic",
    "基础蒸馏",
    "片段提炼、章节摘要、跨章整合，适合快速整理。",
    "较低",
    "",
    "MindChime legacy-v1",
    (
        Stage(
            "extract",
            "章节提炼",
            "按实际内容提取概念、观点、方法、边界、案例与事实；不存在的内容留空。",
            "extract",
        ),
    ),
)
