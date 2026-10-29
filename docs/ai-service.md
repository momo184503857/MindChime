# 独立 AI 服务

AI 服务只接收显式上下文、提示词、输出约束和模型配置引用。它不导入 `mindchime` 模块，不读取业务数据库，不自行检索书籍或启动业务讨论。业务服务负责资料权限、版本、知识范围、检索和任务步骤；AI 服务负责协议适配、模型调用、结构检查和独立调用状态。

## 本地运行与存储

推荐使用项目统一启动入口。独立运行入口为 `PYTHONPATH=services .venv/bin/uvicorn ai_service.app:app --host 127.0.0.1 --port 8766`，启动前必须设置 `MINDCHIME_AI_TOKEN`。除 `/health` 外，API 需要 `X-Service-Token`；未设置令牌时受保护接口返回 503。

数据位于 `MINDCHIME_DATA_DIR/ai`（未设置时为 `.data/ai`），包含独立 SQLite 数据库、实例锁及 `encryption.key`。凭据、调用输入、结果和流事件均加密保存，密钥文件权限为 0600。数据库与加密密钥需要一起备份；仅复制数据库不能恢复密文。该机制保护本地文件内容，不声称可以防御拥有整个用户账户权限的访问。

同一 AI 数据目录只允许一个服务进程，禁止配置多个 Uvicorn worker。内部并发数可通过 `MINDCHIME_AI_CONCURRENCY` 设置为 1–8，默认 1；不依赖 Redis、Celery 或外部任务库。

## 配置与版本

- `/ai/v1/profiles` 支持列出与新增；`/{id}` 支持读取、修改、删除；`/{id}/versions` 返回历史配置，`/{id}/test` 发起真实的小请求。
- 密钥只可写入，任何配置响应均不返回密钥。`configured` 仅表示所需凭据齐全；`test_status`、`last_test_at`、`last_test_error` 保存当前配置版本的连接测试结果。测试成功不代表实际资料的分析质量通过验收。
- 修改配置产生新版本。已接受请求固定配置版本和凭据引用，后续修改不改变该请求。存在活动请求时不能删除配置；删除后清除该配置各版本的凭据，保留不含密钥的版本元数据。
- 未配置时展示 `deepseek-default`、`dashscope-default`、`dashscope-embedding` 模板。只有环境中提供相应密钥时才可调用。环境变量仅为未修改且未配置的模板补充密钥，不覆盖用户修改过的配置；结果通过 `credential_source` 和 `configuration_notice` 标明。
- DeepSeek 模板使用 `deepseek-flash`，支持图像输入，默认关闭 thinking。128k 上下文值是可编辑的保守值。百炼默认 embedding 为 `text-embedding-v4`，每批 10 条；服务地址可以通过 `DASHSCOPE_BASE_URL` 或设置页面修改，应使用账户实际所在地域和业务空间的地址。

## 协议和能力

| 协议 | 生成接口 | 流格式 | 向量接口 |
|---|---|---|---|
| `openai_chat` | `/chat/completions` | SSE delta；支持内容尾块或单独尾块中的 usage | `/embeddings` |
| `openai_responses` | `/responses` | 有类型的 SSE 事件 | 同一服务若提供 `/embeddings` 可配置 |
| `anthropic` | `/v1/messages` | 内容块 SSE；system 与普通消息分开 | 不支持 |
| `ollama` | `/api/chat` | NDJSON | `/api/embed`，显式禁止截断 |

协议支持不等于所有厂商或模型均已实测。能力是具体配置的声明，应通过连接测试和真实任务验证。文本生成、图像输入和 embedding 分别检查能力；不因模型名称相同就推断能力相同。

高级参数提供温度、采样、thinking/reasoning 等选项；`structured_output_mode` 可设 `json_object`、`json_schema` 或 `prompt`。业务指定的 JSON Schema 始终在服务端验证，无法满足结构时请求失败。`chat_token_parameter` 可在 `max_tokens` 与 `max_completion_tokens` 间选择；不支持 `stream_options` 的兼容服务可以设置 `include_usage:false`。向量请求按 `embedding_batch_size` 顺序分批，校验数量、索引顺序、维度与有限数值。

所有调用默认不自动重试、不自动更换模型、不启用搜索或工具执行。连接中断可能发生在服务商已接受请求之后，因此不能承诺外部服务未计费。需要由业务恢复流程明确确认新尝试。

## 请求生命周期

`POST /ai/v1/requests` 接受共享契约中的请求，立即返回 `queued`；状态查询、事件流、取消和确认清理分别位于 `/{id}`、`/{id}/events`、`/{id}/cancel`、`/{id}/ack`。

1. 相同请求 ID 和相同输入返回原请求；相同 ID 改变输入返回 409。接收时锁定模型配置版本。
2. 生成过程发送 `started`、`text_delta`，最终发送 `completed`、`failed` 或 `cancelled`。事件 ID 单调递增，可通过 `after` 或 `Last-Event-ID` 补取。
3. 只有正常结束且输出结构有效才标为完成。截断、拒绝、流断开、无正文、非授权工具调用均不会标为成功。失败前已经收到的文本事件保留供业务展示，但不冒充完整结果。
4. 进程停止或重启时，未完成请求标为 `interrupted`；不会自动重发。业务侧可查看已完成步骤并决定是否启动新请求。
5. 业务必须先保存结果，再调用 `ack`。确认后清除输入、结果、错误正文和旧事件，只保留幂等指纹及状态、模型版本、时间、用量等元数据。再次提交相同 ID 仍返回 `acknowledged`，不会重新调用模型。
6. `DELETE /requests/{id}` 先取消活动请求，再执行同样的私有内容清理。历史文件备份或文件系统层面的物理清除不由此接口承诺。

错误响应、模型错误体和校验错误不会回显密钥、提供商原始错误内容或私人输入。实际 token 用量以服务商返回为准，未提供时保持缺失，不填虚构的零值。

## 验证

`PYTHONPATH=services .venv/bin/pytest -q tests/test_ai_service.py tests/test_ai_protocols.py`

这些测试通过显式 HTTP 测试替身覆盖各协议请求与流格式、版本固定、并发幂等、取消、重启中断、凭据与日志保护、JSON 结构失败、embedding 分批顺序和确认清理。它们不是在线模型验收；在线调用结果需由集成验收另行记录。

实现核对资料：[OpenAI Chat/Responses 差异](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[DeepSeek Chat 与 usage 流](https://api-docs.deepseek.com/api/create-chat-completion/)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[Ollama 流格式](https://docs.ollama.com/api/streaming)、[百炼向量接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)。
