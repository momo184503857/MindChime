from ..registry import Method, Stage

METHOD = Method(
    "book-reader",
    "Adler · 分析阅读",
    "检视、结构、解释、批判和个人应用；适配不同书籍类型。",
    "中高",
    "https://github.com/silentdog918/book-reader-skill",
    "f910584b7abdeb7f589dd3616e45252836bd71b4",
    (
        Stage(
            "inspection",
            "检视与书型识别",
            "检视目录与正文，判断书籍类型、中央问题、论证骨架和适合的阅读方式。文学按叙事理解，不套工具书标准。",
            "prepare",
        ),
        Stage(
            "analysis",
            "章节分析阅读",
            "依据检视阶段确定的书型，提取作者主张、术语、叙事或论证以及具体依据和边界。",
            "extract",
        ),
        Stage(
            "structure",
            "结构与解释阅读",
            "先回答整体谈什么、作者细部说什么及如何展开，再整理关键术语与论证；文学重点处理叙事、人物和意象。",
        ),
        Stage(
            "critical",
            "有依据的批判阅读",
            "基于上一步理解检查知识不足、不合逻辑和分析不完整，必须说明原书位置；无外部证据时不得声称事实错误。文学不套用工具书标准。",
        ),
        Stage(
            "application",
            "一页摘要与个人应用",
            "综合前述分析，交付一页摘要、精读笔记、思维导图骨架与行动清单；回应用户提示词，不强行把文学转成操作方法。",
        ),
    ),
)
