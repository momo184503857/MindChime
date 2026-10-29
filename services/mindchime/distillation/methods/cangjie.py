from ..registry import Method, Stage

METHOD = Method(
    "cangjie",
    "仓颉 · 能力蒸馏",
    "整书理解、五路提取、三重验证、能力构造和压力测试，适合把书转为可实践方法。",
    "较高（五路提取及审核）",
    "https://github.com/kangarooking/cangjie-skill",
    "2.5.0 @ a28de55ba881b9928956a55048f743f7a9e3b23e",
    (
        Stage(
            "understanding",
            "全书理解",
            "分析整书结构、中央问题、关键术语、论证路径与可应用性。保留跨章条件，为后续五路提取建立共同理解。",
            "prepare",
        ),
        Stage(
            "frameworks",
            "框架提取",
            "只提取可复用决策框架、操作流程、计算规则；具体步骤和条件保留在 content 中。",
            "extract",
        ),
        Stage("principles", "原则提取", "只提取判断原则与适用条件，区分作者主张和模型推论。", "extract"),
        Stage("cases", "案例提取", "只提取支撑方法的案例和因果机制，不把个案包装成普遍规律。", "extract"),
        Stage(
            "counterexamples",
            "反例与边界提取",
            "只提取失败案例、反例、方法失效条件与代价。不存在则 cards 留空。",
            "extract",
        ),
        Stage(
            "glossary", "术语提取", "只提取原书特有或关键术语，保留作者定义和与日常用法的区别。", "extract"
        ),
        Stage(
            "verification",
            "来源、执行与用途验证",
            "逐卡核对引文能否支持结论、操作是否有完整条件、对用户用途是否有帮助。不能因有引文就判为 supported。缺依据 review，错误 reject。",
            "audit",
        ),
        Stage(
            "capabilities",
            "RIA 能力构造与链接",
            "只使用验证通过的单元构造能力：原文依据、解释、触发场景、执行步骤、正反案例、边界；建立依赖、对照与组合链接。未通过者列为候选。",
        ),
        Stage(
            "pressure",
            "诱饵与边界压力测试",
            "逐卡设计并作答一个容易误用或越界的情境题，检查条件、反例和拒用边界。答案只能依据提供的原文。存在问题 passed=false 并解释。",
            "test",
        ),
        Stage(
            "repair",
            "定点修复与复测",
            "仅针对审核或测试失败的卡片，提出基于原文的修正，重新检查引文、执行条件和失败情境；不确定则保持 review，不强行通过。",
            "repair",
        ),
    ),
)
