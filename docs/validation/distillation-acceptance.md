# 模块化蒸馏验收矩阵

范围：2026-10-29 确认的单书、单方法、书内适配。六种方法共用输入和结果，新增五种保留独立阶段。模型与方法解耦。

| 项目 | 验证证据 | 状态 |
|---|---|---|
| 六种方法发现及共同输入输出 | test_methods_produce_isolated_results_and_validated_relations（六种参数） | 通过 |
| 方法并非仅换名称 | 各方法独立 prepare/extract/report/audit/test/repair 阶段断言及真实调用记录 | 通过：五种方法均真实完成 |
| 提交固定方法、模型配置；旧 focus 兼容 | test_submission_pins_model_and_method_snapshot_and_legacy_focus | 通过 |
| 结果独立保留，手动启用；部分结果不可启用 | test_partial_retry_reuses_successful_calls_and_stable_cards | 通过 |
| 当前结果切换不改变旧 Agent/会话 | test_result_binding_switch_does_not_change_old_agents_or_conversations | 通过 |
| 未选结果卡不能混入，支持仅原文 | 同上；三引擎 Agent 卡片选择用例 | 通过：隔离数据库及三引擎选择器 |
| 无引文、审核或压力测试未通过的能力不可用 | test_unverified_capabilities_cannot_be_used（引文/测试） | 通过 |
| 引用与真实片段一致，无效关系被剔除 | 公共参数测试、五种真实结果逐条 /evidence 校验 | 通过：五种方法均真实完成 |
| 长文本完整覆盖与重叠 | test_chunking_covers_every_character_with_overlap | 通过 |
| 部分章节失败，前序恢复后才运行后续阶段 | test_failed_extraction_blocks_dependent_reports_then_retry_covers_all_chapters | 通过 |
| 暂停、恢复与模板变化保护 | test_cancel_preserves_partial_output_and_method_version_is_pinned | 通过 |
| 选定结果不能扩展到未处理章节；原文变化不能启用旧结果 | test_result_cannot_expand_chapter_range_and_changed_source_cannot_activate | 通过 |
| 历史基础结果增量重建 | test_api_catalog_validation_and_legacy_backfill；现有历史页面回归 | 通过 |
| 结果资产包、绑定 ID 重映射与删除联动 | test_export_restore_remaps_result_bindings_and_delete_purges_results | 通过 |
| 方法来源、上游版本与许可证 | docs/third-party/ 五个固定提交与许可证 | 已记录 |
| 六方法选择、默认仓颉、提示词提交及 WCAG A/AA | distillation.spec.ts · 三浏览器引擎 | 通过 |
| 结果特色扩展、证据入口、导出与双主题 | distillation.spec.ts · 真实仓颉结果，三浏览器引擎 | 通过 |
| 旧工作台与核心流程 | workspace.spec.ts · 24 项 | 通过 |
| 同一原创演示书五方法真实模型调用 | distillation-live.json | 通过：5/5，67 条引用逐字核对 |

## 解释与限制

- 后端测试使用隔离数据库和模型边界替身注入故障；真实调用另行记录，未把替身输出算作真实验收。
- 浏览器测试覆盖 Chromium、Firefox、WebKit 引擎，非单独安装的所有品牌浏览器发行版。
- 真实验证为 PRD 的原创短演示资料，不代表长篇出版书语义质量已经全面基准测试。长文分段、分组和失败恢复有自动化覆盖。
- 本轮真实服务曾返回结构错误和无效 JSON。系统没有交付为成功；显式恢复失败阶段，并保留已有成功结果与原请求记录。供应商失败调用可能产生费用，最终用量不能仅由成功步骤推断。
- 模型审核与情境测试不等于独立事实认证；所有卡片仍待人工核对。

最终汇总：141 项后端测试、33 项三引擎浏览器测试通过；类型检查、生产构建通过。模型及逐阶段用量、候选状态见 distillation-summary.json 和 distillation-live.json。
