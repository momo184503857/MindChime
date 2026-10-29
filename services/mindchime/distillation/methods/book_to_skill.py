from ..registry import Method, Stage

METHOD = Method(
    "book-to-skill",
    "Book to Skill · 结构化方法",
    "保留章节结构、框架的准确名称、决策规则与反模式，适合技术书与工具书。",
    "中等",
    "https://github.com/virgiliojr94/book-to-skill",
    "7540eefbe74933f5fc84c86becac52486b347778",
    (
        Stage(
            "structure",
            "章节结构与框架识别",
            "识别整本书结构、技术或叙事类型、核心框架名称与章节参考路径。",
            "prepare",
        ),
        Stage(
            "frameworks",
            "框架与规则提取",
            "按原书准确名称提取框架、方法、决策规则及其必要条件和反模式。",
            "extract",
        ),
        Stage(
            "patterns",
            "方法模式与反模式",
            "针对每项有来源的方法写出触发条件、执行顺序和反模式；不要把描述性事实伪造成操作方法。",
        ),
        Stage(
            "index",
            "章节参考与术语索引",
            "建立术语表、章节参考索引和按任务查询的路由，概念定义必须尊重原书；注明关联卡片。",
        ),
        Stage(
            "cheatsheet",
            "决策速查表",
            "根据已有方法和索引构建情境→条件→行动→停止条件的决策表；不能新增原书未支持的规则。",
        ),
    ),
)
