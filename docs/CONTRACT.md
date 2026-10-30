# Implementation contract — local v1

This is the shared implementation contract. All business endpoints use `/api/v1`; AI endpoints use `/ai/v1`. JSON dates are UTC ISO strings. Errors return `{detail: string}` with a meaningful HTTP status. No fake model outputs. Empty model configuration blocks generation with a useful error. Source PRD plus the accepted plan govern semantics.

## Storage contract

Business module `mindchime.db` supplies `db` and Record CRUD. An entity is `{id,kind,title,status,version,parent_id,data,created_at,updated_at}`. `db.create(kind,title,data,status='active',parent_id=None,id=None)`, `db.get(id,kind=None,include_deleted=False)`, `db.list(kind=None,parent_id=None,include_deleted=False)`, `db.update(id,data=None,title=None,status=None,expected_version=None,replace_data=False)`, `db.delete(id)`, `db.revisions(id)`, `db.revision(id,version)`, `db.emit(topic,event,data)`, `db.events(topic,after=0)`. get/revision return None when missing. Update merges top-level data by default, writes an immutable revision. All returned entities are plain dicts. `db.reset(path)` is available for isolated tests. `db.claim_job()` atomically claims queued work. `db.engine`, SQLAlchemy `Record`, `Revision`, `Event` are exposed for advanced transactions.

Kinds: source, chapter, card, agent, conversation, message, job, artifact, skill, run, memory, relation, settings, import_preview. Source/card/agent version references never float silently. Source ids in data are `source_ids`; card ids are `card_ids`. References are `{source_id,source_version,chapter_id,chapter_version,start,end,quote,label}`; start/end are offsets in immutable chapter text, not invented page numbers. Chapters carry source_id, text, locator, selected. Cards carry source_ids, chapter_ids, type, content, attribution, applicability, limitations, references, review_status. `deleted` records are not searchable. `disabled` enhanced assets remain visible but cannot be used in generation.

## Shared business task integration

`mindchime.jobs.enqueue(kind,payload,request_id=None)` returns a job entity, with input in `data.input`; same request_id with different input is a conflict. Worker handlers are async `(ctx, job)` and registered with `register_handler(kind, handler)` in `mindchime.jobs`. Context: `await ctx.generate(prompt, *, purpose='chat', messages=None, schema=None, step_key, profile_id=None)` returns generated text (or decoded JSON when schema is given); `await ctx.embed(texts, *, step_key, profile_id=None)` returns list of vectors. ctx persists AI request ids and successful results per step_key; `ctx.progress(stage, **fields)` updates durable job progress; `ctx.check_control()` raises on cancellation/pause as appropriate. Extensions expose `router` and `register_handlers()` from `mindchime.enhancements`; main and worker import these. Worker stores handler result as data.result and marks completion, preserving partial failure/interrupted states. No automatic replay of ambiguous in-flight calls.

## Core API (business implementer owns)

- `GET /health`, `GET /dashboard` (counts, recent sources/agents/conversations/jobs), `GET/PATCH /settings` (plain configuration map; purpose_profiles keyed by purpose).
- `GET /profiles`, `POST /profiles`, `PATCH/DELETE /profiles/{id}`, `POST /profiles/{id}/test`: proxy to AI service, masked credentials only. Profiles are described below.
- `GET /sources` -> entity array; `POST /sources/import` multipart `file,title?,author?,duplicate_action?` (`reject` default, `copy` or `version`, optional source_id). `POST /sources/paste` JSON `{title,text,author?,duplicate_action?,source_id?}`. Duplicate returns 409 with existing source id. `POST /demo/load` loads original PRD sample texts, clearly labelled, idempotently.
- `GET /sources/{id}` -> `{source,chapters,cards,versions,agents}`; `PATCH /sources/{id}` accepts `{title?,data?}`. `GET /sources/{id}/file`. `GET /sources/{id}/impact`. `DELETE /sources/{id}?mode=file|derived&history=keep|redact`.
- `PATCH /chapters/{id}` accepts `{title?,data?:{selected?,text?}}`; `POST /chapters/merge` `{ids}`; `POST /chapters/{id}/split` `{offset}`. Maintain real locators and revisions.
- `POST /sources/{id}/distill` `{chapter_ids,model_profile_id?,focus?,request_id}` -> job; `POST /sources/{id}/ocr` `{chapter_ids?,model_profile_id?,request_id}` -> job.
- `GET /cards?source_id=`, `POST /cards` `{title,data}`, `GET/PATCH/DELETE /cards/{id}`; PATCH `{title?,data?}`. `POST /cards/{id}/restore` `{version}`. `GET /evidence` query source_id,chapter_id,chapter_version,start,end -> actual source/chapter/quote or missing status.
- `GET /agents`; `POST /agents` `{title,data}`; data: source_ids,chapter_ids,card_ids,excluded_card_ids,purpose,perspective,framework,methods,boundaries,style,model_profile_id,general_knowledge. `POST /agents/generate` `{source_ids,chapter_ids?,card_ids?,purpose,count:1..3,model_profile_id?,request_id}` -> job creating draft agents. `GET /agents/{id}` -> `{agent,revisions,knowledge_summary}`; `PATCH /agents/{id}` `{title?,data?,status?}`; `POST /agents/{id}/copy`; `DELETE /agents/{id}`.
- `GET /conversations`; `POST /conversations` `{title,data:{mode:'single'|'group',agent_ids,background?}}`. `GET /conversations/{id}` -> `{conversation,messages,jobs}`; `PATCH /conversations/{id}` `{title?,data?,status?}`; DELETE.
- `POST /conversations/{id}/messages` `{text,agent_ids?,request_id}` -> job. `POST /conversations/{id}/discussions` `{topic,background?,mode:'ordered'|'challenge'|'dynamic',rounds:1..10,max_speeches?:1..60,max_minutes?:number,summary:boolean,request_id}` -> job. Snapshot agent versions and knowledge selections. `POST /conversations/{id}/interject` `{text}`. `POST /conversations/{id}/members` `{agent_ids}`. `POST /conversations/{id}/switch-version` `{agent_id,version}`. `POST /conversations/{id}/summary` `{request_id}` -> job. `POST /messages/{id}/feedback` `{type}`; `POST /messages/{id}/favorite` `{favorite:boolean}`.
- `GET /jobs`, `GET /jobs/{id}`; `POST /jobs/{id}/{pause,resume,cancel,retry,skip}`; skip removes failed participant from the rest of that discussion. `GET /events?topic=...&after=...` SSE; topic `jobs`, `job:{id}`, `conversation:{id}`. `GET /search?q=&kind=` -> entity array within allowed live personal assets.

## Enhancements API (root implementer owns)

- `GET/POST /artifacts`, `GET/PATCH/DELETE /artifacts/{id}`; body `{title,data:{content,type,conversation_id?,message_ids?,references?,source_ids?}}`. `POST /artifacts/generate` `{conversation_id,message_ids?,type,request_id}` -> job.
- `GET/POST /skills`, `GET/PATCH/DELETE /skills/{id}`; `{title,data:{description,inputs,steps:[{title,instruction,output}],card_ids,source_ids,agent_id?}}`. `POST /skills/generate` `{card_ids,agent_id?,purpose?,request_id}` -> job. `POST /skills/{id}/runs` `{inputs,agent_id?}` -> run. `GET /runs`, `GET/PATCH /runs/{id}`; `POST /runs/{id}/advance` `{answer,use_ai,request_id}` -> run or job; `POST /runs/{id}/review` `{reflection}`.
- `GET /memories`, `PATCH/DELETE /memories/{id}` accepts `{data?,status?:'active'|'disabled'|'candidate'}`; data content,agent_id,shared_agent_ids,source_message_ids,source_ids. `POST /memories/extract` `{conversation_id,agent_id?,request_id}` -> job. Candidates require explicit activation.
- `GET /graph?source_id=` -> `{nodes,edges}` (nodes are card/source entities, edges are relation entities). `POST /graph/generate` `{source_ids,request_id}` -> job. `POST /graph/relations` `{title,data:{from_id,to_id,type,evidence,source_ids,review_status}}`; `PATCH /graph/relations/{id}` `{data?,status?}`. Relation types support,limit,refute,apply,similar.
- `GET /export?kind=workspace|source|agent|conversation|artifact|skill&id=&format=markdown|zip&originals=false` returns attachment; zip includes versioned manifest and dependency closure, excludes credentials. `POST /imports/preview` multipart file -> `{id,counts,conflicts,missing,includes_originals}`; `POST /imports/{id}/restore` `{conflict:'copy'|'skip'}` -> counts and id mapping.

## AI API (AI implementer owns)

Service token `MINDCHIME_AI_TOKEN` in `X-Service-Token`; `/health` open. Storage under MINDCHIME_DATA_DIR/ai, independent of business. Bind loopback by launcher. `/ai/v1/profiles` GET list array, POST create; PATCH/DELETE `/{id}`; POST `/{id}/test`. Profile fields `{id,name,protocol:'openai_chat'|'openai_responses'|'anthropic'|'ollama',base_url,model,api_key?(write-only),capabilities:{stream,vision,json,embedding,context_tokens},parameters:{},enabled,version}`. Credentials never returned. Default profiles seeded from DEEPSEEK_API_KEY / DASHSCOPE_API_KEY only if provided; template profiles without keys may be shown with configured=false. purpose_profiles belongs to business settings. Profile version snapshots immutable.

`POST /ai/v1/requests` JSON `{request_id,operation:'generate'|'embed',profile_id,profile_version?,prompt?,messages?:[{role,content}],texts?:[string],output_schema?:object,max_tokens?:integer,timeout_seconds?:number,prompt_version?:string}` -> `{id,status,...}` immediately. `GET /requests/{id}` -> `{id,status,profile_id,profile_version,result?,error?,usage?,finish_reason?}`, result `{text?,json?,vectors?,model?}`. `GET /requests/{id}/events?after=` SSE. `POST /requests/{id}/cancel`; `POST /requests/{id}/ack` purges private payload/results and retains metadata; `DELETE /requests/{id}` purges data and cancels if active. terminal statuses completed,failed,cancelled,interrupted,acknowledged. Same request id + same payload returns original, changed payload conflicts. SSE normalizes started,text_delta (data.text),completed,failed,cancelled. JSON schema failure is failed, not fake success. Interrupted provider requests are never replayed automatically. Limit finite retries only before known nonaccepted errors; ambiguous requests need user retry. Input images use standard message content blocks. AI service stores no business entity ids other than opaque caller/request IDs.

## 模块化蒸馏

- `GET /distillation-methods` -> `{default_method_id:"cangjie",methods:[{id,name,version,description,cost,upstream,upstream_version,license,stages,external_sources:false,adaptation}]}`。
- `POST /sources/{id}/distill` 增加 `{method_id?,prompt?,chapter_ids?,model_profile_id?,request_id?}`。省略方法使用 `basic`；旧 `focus` 兼容，两字段冲突拒绝。模型配置和方法完整清单在提交时固定。
- `GET /distillations?source_id=` 返回独立结果；`GET /distillations/{id}` 附带固定版本 cards。data 包含 method、prompt、source_version、chapter_versions、card_ids/card_versions、integration、chapter_summaries、coverage、extensions、quality、warnings、model_calls。状态 running/incomplete/partial/completed。
- `POST /distillations/{id}/activate` 只允许完整、依赖和原文范围仍有效的结果，更新资料 active_distillation_id；不更改旧 Agent/会话。
- Agent data 增加 `distillation_ids:{source_id:result_id}` 与 `raw_source_ids:[]`。每来源选择一份完整结果或仅原文。省略结果时固定当前结果；存在新结果但尚未选定时要求明确选择。默认卡片不跨结果混用。
- `POST /skills/generate` 可带 `distillation_id`，校验卡片属于该完整结果，保存来源依赖；`POST /distillations/{id}/skills` 支持用户明确编写步骤并保存为 Skill。
- `/export` 支持 `kind=distillation`，Markdown/ZIP；结果和选择映射进入依赖闭包及恢复 ID 重映射。未知方法只作为数据阅读，包中无执行入口。
- 蒸馏任务支持 pause/resume/retry/cancel。pause 在当前模型调用完成后的检查点生效。

## 本地账号、发布与双蒸馏（2026-10-30）

以下业务接口均在 `/api/v1` 下。`POST /auth/login {username,password}` 返回账号并设置 HttpOnly Session Cookie；`GET /auth/me`、`POST /auth/logout` 获取或撤销登录。业务匿名请求 401，普通账号调用管理能力 403；普通账号不能覆盖模型、身份或一般知识策略。健康检查保持公开。

- 管理：`GET/POST /persons`，`PATCH/DELETE /persons/{id}`；`GET /cognitive-profiles?person_id=`，`GET /cognitive-profiles/{id}?version=`，`PATCH /cognitive-profiles/{id} {rules:[{id,review_status,review_note}],status?}`。读取受发布权限控制，写入仅管理员。
- 统一提交：`POST /distillations {distillation_type,method_id,source_ids,chapter_ids?,person_id?,allow_network:false,prompt?,model_profile_id?,request_id?}`。知识类型要求单份资料、禁止联网；思想类型要求人物、女娲方法，在无本地资料时需明确开启且已配置联网。旧 `POST /sources/{id}/distill` 仍是知识入口。
- 结果：`GET /distillations?source_id=&distillation_type=`；`source_id` 阅读页默认只列知识结果。思想结果包含画像 ID、来源版本、阶段报告、审核与问题集测试，不包含知识卡。`POST /distillations/{id}/continue-local` 明确跳过部分联网失败。
- 发布：`GET /publications`、`GET /publications/{id}/versions`、`GET /publications/{id}/version-detail?version=`、`GET /publications/{id}/preview?version=`、`POST /publications/{id}?version=`、`DELETE /publications/{id}`，全部仅管理员。预检返回 `ready/dependencies/blockers`；发布依赖不满足返回 409。知识卡历史版本审核用 `POST /reviews/{id} {version,decision,note?}`，不会改写该内容版本。
- 搜索配置：`GET/PATCH /research/config` 仅管理员，读取只返回 provider、configured、enabled、version。凭据与 `/ai/v1/research/{search|extract}` 均由服务令牌保护的独立 AI 服务管理。业务提交固定配置版本、请求编号与采集限制，失败不自动重发。
- 智能体增加 `agent_type`、`cognitive_profile_id`、`cognitive_profile_version`，至少绑定知识或思想之一。会话继续固定智能体版本；人物回答须区分来源支持与模拟分析。
- Skill 和实践的新请求拒绝 `agent_id`，使用 `skill_generate` / `skill_guidance` 用途；实践快照不加载人物配置。旧绑定只保留为历史记录，不再参与运行。

个人记录 envelope 增加 `owner_user_id`。数据库统一投影发布版本、限制私人记录，Worker 使用任务持久化账号身份。搜索不以未发布正文命中旧发布版本；版本读取只开放确实发布过的快照。全局事件流过滤任务归属，指定事件主题先校验访问权并随 Session 过期终止。

资产包兼容原格式，新增人物、思想画像、发布记录；恢复后不自动公开。普通用户仅能导出自己的 conversation/artifact/run，不能导出全局工作区或原始文件。
