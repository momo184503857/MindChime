# 蒸馏方法来源

MindChime 的五种方法为系统内书籍流程适配，参考以下开源项目。提示词、统一结果、任务与 UI 为本项目实现；不自动加载上游 SKILL.md 或执行上游代码，不代表上游官方集成。

- https://github.com/virgiliojr94/book-to-skill
- https://github.com/kangarooking/cangjie-skill
- https://github.com/sanshengai/sansheng-distill
- https://github.com/BlackFast/bolan-skill
- https://github.com/silentdog918/book-reader-skill

固定提交及当时 SKILL.md 的 SHA-256 见 distillation-sources.json。对应原始许可证保留在同目录的 *-LICENSE.txt。上游为 MIT；许可证适用于其代码和模板，不改变第三方书籍本身的权利。

适配差异：单书、单方法、仅书内证据；统一解析器、AI 服务、任务恢复、知识版本和结果契约。原版外部搜索、安装发布、多书与宿主 Agent 工具调用不执行。保留方法特有的阶段、成果和模型评审，不声称与原版行为完全一致。

女娲（alchaincyf/nuwa-skill）用于思想蒸馏的方法适配，固定提交、文件哈希与 MIT 许可同样记录在清单中。采用本地结构化画像和串行阶段，联网默认关闭；不执行上游脚本，不将其原有 Skill 输出作为平台数据库。
