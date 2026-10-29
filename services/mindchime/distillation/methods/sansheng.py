from ..registry import Method, Stage

METHOD = Method(
    "sansheng",
    "三生 · 精读知识地图",
    "从章节精读形成全书骨架、核心论证、因果链与自检问题。",
    "中高",
    "https://github.com/sanshengai/sansheng-distill",
    "a411cc2c923eee070f0e77a44239ee58164a335c",
    (
        Stage(
            "reading",
            "逐章精读与骨架提炼",
            "沿原文论证顺序精读，提取事实→机制→观点及限定条件，保留内部张力。",
            "extract",
        ),
        Stage(
            "map",
            "知识地图与核心论证",
            "构建章节知识地图和核心论证；指出最关键的反直觉主张及其依据。不要为缺少论证的书硬造因果链。",
        ),
        Stage(
            "causal",
            "因果链与思维模型",
            "沿知识地图整理因果链、作者使用的思维模型，区分相关性与因果，注明每段链条的依据和缺口。",
        ),
        Stage(
            "selfcheck",
            "行动与自检",
            "依据已提取内容给出行动清单、自检问句、原书内部盲点；外部书评和科学事实核验明确未执行。",
        ),
    ),
)
