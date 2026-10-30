# 界面说明的展示方式

2026-10-30 确认：前台与后台的常规说明默认收起，用相邻的问号图标按需展示。页面不再为副标题、字段解释或操作规则单独铺设长段文字。

- 页面标题通过 `PageHeader.description` 提供问号说明，不常驻展示说明段落或英文装饰副题。
- 区块与字段使用共享 `HelpTip`，放在对应标题或操作旁；同一主题的多段说明合并到一个提示中。
- 使用者可悬停查看、移入浮层继续阅读，或通过聚焦、点击展开。移出后关闭；点击外部或按 Escape 关闭。弹窗内先关闭提示，再处理弹窗自己的 Escape。
- 图标具有描述性可访问名称，展开时通过 `aria-describedby` 关联提示。帮助按钮放在标题、单选标签或操作按钮旁，避免嵌套交互控件，保持原控件名称与行为。
- 书名、作者、原文、模型与生成结果、实践内容、引用、计数、版本、状态和错误是业务信息，正常展示。`PageHeader.descriptionIsMetadata` 用于作者、资料格式等真实元信息。
- 不使用全局 CSS 隐藏说明，不隐藏错误反馈或操作确认。

```vue
<div class="heading-with-help">
  <h2>默认模型与任务分配</h2>
  <HelpTip label="默认模型与任务分配说明" text="留空用途沿用默认模型，向量检索需配置对应能力。" />
</div>
```

实现：`web/src/components/HelpTip.vue`。专项浏览器测试：`web/tests/e2e/help.spec.ts`。验证记录：`docs/validation/help-summary.json`。
