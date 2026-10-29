from ..registry import Method, Stage

METHOD = Method(
    "bolan",
    "博览 · 思想框架",
    "提取书的中央问题、价值排序、判断标准与对话边界，适合思想 Agent。",
    "中高",
    "https://github.com/BlackFast/bolan-skill",
    "890e71ab0ee7a74999535d9d41ac714a6891e534",
    (
        Stage(
            "argument",
            "中央问题与论证路径",
            "提取本书追问的问题、论证路径、价值排序、关键判断标准及内部张力。",
            "extract",
        ),
        Stage(
            "thinking",
            "思想框架与表达方式",
            "根据原书组织思想框架、价值排序和表达特点；展示书的思考方式，不冒充作者本人。",
        ),
        Stage(
            "contract",
            "对话契约与提问方式",
            "依据思想框架写出如何分析用户问题、如何追问、何时拒答及如何说明不知道；保留原书内部张力，不抹平分歧。",
        ),
        Stage(
            "inner-evidence",
            "文本内证验证",
            "逐卡核查观点锚点、概念用法、内部张力和回答边界。无原文支持则 review 或 reject。外部接收与书评环节未执行，不声称双环通过。",
            "audit",
        ),
    ),
)
