# MindChime

本地知识工作台：导入资料，蒸馏可核对的知识卡，创建独立思想智能体，通过对话与有限讨论保存自己的判断和实践方法。

本次范围见 [需求补充](docs/local-requirements.md)，原始需求保留在根目录。当前提供桌面网页版，浅色与深色主题；托管、支付、手机端、网页和音视频导入不属于本次版本。

## 启动

需要 Node.js 22.12+、pnpm、uv 和 Python 3.12。uv 会按 `.python-version` 选择 Python；依赖由 `uv.lock` 和 `web/pnpm-lock.yaml` 锁定。

```sh
uv sync --python 3.12
pnpm --dir web install --frozen-lockfile
cp .env.example .env.local
# 编辑 .env.local 填入自己的模型凭据，不要提交到版本控制。
.venv/bin/python scripts/manage.py start
```

打开 http://127.0.0.1:5173 登录。首次启动生成 `admin` 和 `user` 两个本地测试账号，随机密码见 `data/local-accounts.json`（文件权限 0600，重启不重置）。普通账号进入前台；管理员默认进入后台，后台位于 http://127.0.0.1:5173/admin ，管理员也可从侧栏切换。普通账号仅使用明确发布的内容，模型由管理员配置。详见 [前后台使用说明](docs/frontend-areas.md)。启动器会执行数据库迁移，并启动四个独立进程：Vue 开发服务器、业务 API、业务 worker、AI 服务。所有监听地址均为本机回环地址；端口可在 `.env.local` 调整。

```sh
.venv/bin/python scripts/manage.py status
.venv/bin/python scripts/manage.py stop
.venv/bin/python scripts/manage.py restart
```

启动日志位于 `.runtime/`。停止时先停止业务调度并尽力取消在途调用；已经发送给模型供应商的调用仍可能产生费用。重启后在任务中心明确恢复中断任务。

## 第一次使用

完整流程、发布顺序和双蒸馏说明见 [账号与双蒸馏使用说明](docs/dual-distillation-and-access.md)。以下准备工作由管理员完成；普通用户登录后直接使用已发布内容。

1. 在后台“模型配置”检查模型配置和连接测试。`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 可以初始化可编辑的服务配置，也可直接在设置页新增其他服务。
2. 为蒸馏、Agent、对话、总结、OCR、记忆和向量选择用途配置。无可用模型时，仍可导入和阅读资料；生成操作会明确提示配置。
3. 在后台“资料与蒸馏”载入明确标注的原创演示资料，或导入 PDF、EPUB、TXT、Markdown、DOCX。检查章节、排除无关范围后再蒸馏。扫描 PDF 需要视觉模型。
4. 在后台核对知识卡及引用，创建一个或多个 Agent 草稿，试聊并保存；来源范围和视角均可编辑。
5. 返回前台创建单聊或群聊。手动发送只触发一批回复；多轮圆桌需要预览计划并单独启动。
6. 在成果、图谱、Skills 和长期记忆中继续整理与实践。记忆候选只有明确确认后才能在之后对话中使用。

模型名称和服务地址可以替换。独立 AI 层支持 OpenAI Chat Completions、Responses、Anthropic Messages、Ollama，以及兼容 Embeddings 接口。详细配置与能力边界见 [AI 服务说明](docs/ai-service.md)。

“连接成功”只代表接口可调用；不代表某本资料的分析质量已经核验。不同协议的本地契约测试与实际供应商联调分别记录。

## 数据与版本

- 业务数据：`data/business.sqlite3`；原文件：`data/originals/`。任务和事件保存在业务库。
- AI 配置与调用：`data/ai/`，与业务存储隔离；凭据加密，密钥不出现在普通接口、日志或导出中。
- 任务完成后先保存业务结果，再确认清理 AI 服务临时输入和结果；不确定状态不自动重发供应商调用。
- 来源、卡片、Agent 和会话使用版本记录。旧会话保持原版本，切换必须留下记录。
- 只删除原文件时保留知识卡及允许保留的短引用；删除资料及派生知识时，会删除所有使用该来源的混合知识卡。
- 相关图谱、Skill 和知识性记忆保留但置灰；修复来源并明确启用前，不得用于回答或实践。历史消息、成果、实践记录中的摘录另行选择处理。

这是本地应用，不自动同步官方服务。调用在线生成、OCR 或向量模型时，相关输入会发送到所选服务。

## 导出与恢复

在后台“数据备份与恢复”导出个人资产包，并在导入预览后选择另存副本或跳过冲突。也可分别导出资料、Agent、会话、成果和 Skill。

默认资产包保留可读内容、引用及版本关系，不包含整本原文、模型密钥或向量索引。需要完整原文件时，应明确选择携带；原文件缺失时，导入后的引用会说明不能重新核对原文。迁移后重新选择模型和重建向量索引，候选记忆需重新确认。

数据目录整目录备份仅适合自行保管的本机备份：先停止服务再复制 `data/`，避免文件与数据库版本不一致；该目录包括个人原文和本地加密材料。跨实例迁移建议使用资产包。

## 开发与验证

```sh
.venv/bin/python -m pytest -q
pnpm --dir web build
pnpm --dir web test:e2e
```

接口契约见 [CONTRACT.md](docs/CONTRACT.md)。业务 OpenAPI 位于 http://127.0.0.1:8765/docs；AI 服务 OpenAPI 位于 http://127.0.0.1:8766/docs，业务接口调用 AI 时使用本机服务令牌。

真实联调脚本只使用原创演示资料，**会调用已配置的在线模型并产生供应商用量**：

```sh
.venv/bin/python scripts/validate_live.py
# 明确检查失败原因后，恢复已经提交的请求；优先取回已完成结果。
.venv/bin/python scripts/validate_live.py --resume
```

测试结果与限制记录在 `docs/validation/`。密钥不可写入测试结果。发布许可证尚未确定，不将未授予的开源使用权作为既成事实。

## 蒸馏方法

后台资料详情支持六种知识蒸馏方法，默认仓颉；人物与思想蒸馏页面提供独立的女娲方法，支持多份资料、逐项审核和默认关闭的可选联网。每次结果独立保存，手动设为当前结果；旧 Agent 和会话保持绑定。详见 [方法与使用说明](docs/distillation-methods.md)。
