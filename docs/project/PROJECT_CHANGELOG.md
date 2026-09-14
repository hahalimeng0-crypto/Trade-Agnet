# 项目修改记录

## 2026-08-27（项目目录第一轮整理）

| 项目 | 内容 |
|---|---|
| 整理范围 | 移动 36 个职责明确的文件：身份提示词、项目文档、示例 MCP、RAG 评估配置和说明。 |
| 新目录 | `prompts/`、`docs/{architecture,guides,project,reference,archive}`、`examples/mcp/`；评估配置并入 `rag_evaluation/config/`。 |
| 兼容调整 | 更新运行配置、真实 `.env`、Manager MCP 发现、RAG 评估测试、README 和文档路径引用。正式 MCP Server、业务数据和启动入口未移动。 |
| 风险控制 | 未移动高耦合的 `agent/business/`、根 Gateway/Config/Main 或任何业务数据库；避免仅为目录美观引入数据迁移和大面积导入兼容风险。 |
| 验证 | 路径、身份、MCP、RAG 评估及内部 Agent 专项 `45 passed`；全量 `472 passed, 5 skipped, 1 warning, 40 subtests passed`。 |
| 操作者 | Codex |

## 2026-08-27（内部员工 Agent 断点迁移到 Redis）

| 项目 | 内容 |
|---|---|
| 修改位置 | `employee_agent/` 配置与 runtime、启动装配、Compose、环境示例、依赖、架构文档及专项测试。 |
| 变更摘要 | 正式运行的 LangGraph Checkpointer 从本地 SQLite 改为 Redis；SQLite 保留为自动化和本地隔离测试后端。内部员工 Agent、客户 Agent 和确定性业务服务逻辑不变。 |
| Redis 隔离 | 客户产品缓存使用 DB 0；内部 Agent 断点使用 DB 1 和独立 key 前缀；异常断点默认 TTL 7 天，成功后主动删除。 |
| 运行要求 | LangGraph Redis Checkpointer 需要 RedisJSON 与 RediSearch，Compose 从普通 Redis 7 调整为 Redis 8。Redis 不可用时断点模式失败关闭，不静默降级到 SQLite。 |
| 验证 | Redis/SQLite/配置/装配专项 `20 passed`，无本机 Redis 时实连验收 `1 skipped`；全量 `472 passed, 5 skipped, 1 warning, 40 subtests passed`；依赖锁离线检查通过。 |
| 操作者 | Codex |

## 2026-08-27（内部员工 Agent 迁移到 LangGraph）

| 项目 | 内容 |
|---|---|
| 修改位置 | 新增独立 `employee_agent/` runtime；`agent/internal_langgraph_agent.py` 改为薄适配层；同步调整 `main.py`、依赖、环境示例、README、路由文档及专项测试。 |
| 变更摘要 | 使用显式 LangGraph `StateGraph` 替换内部员工 Agent 原有的手写模型—工具循环。独立 runtime 不引用 NanoClaw；薄适配层注入现有 Provider、ToolRegistry、MCP 工具、WorkflowService、会话和记忆生命周期。 |
| 状态边界 | 初始版本使用 SQLite 保存未完成请求的单轮编排断点，随后正式运行后端已迁移到 Redis，SQLite 仅保留测试用途。会话仍由 SessionManager/MySQL 保存，RFQ、报价、审批和邮件仍以业务数据库为权威。 |
| 等价行为 | 保留最大迭代次数、工具重复调用检查、通用 Provider 错误回复、工具消息持久化、`query_trade_data` 专用观察、询盘工作流观察和 MemoryLifecycle 工具结果事件。 |
| 验证 | 新增断点恢复、逐工具断点、成功清理、配置边界测试；相关定向 `36 passed`；全量 `468 passed, 4 skipped, 3 warnings, 40 subtests passed`；`uv lock --check --offline` 通过。 |
| 操作者 | Codex |

## 2026-08-09（外贸垂直 RAG 完整评估师）

| 项目 | 内容 |
|---|---|
| 修改位置 | `rag_evaluation/`、`rag_evaluation/config/trade_gate_v1.json`、`trade_rag/contracts.py`、`pipeline.py`、`retrieval.py`、`hybrid.py`、`generation.py`、`test/fixtures/rag_eval/`、专项测试与运行手册 |
| 变更摘要 | 新增统一 JSONL 评估契约、评估模式检索轨迹、逐主张引用绑定、检索/忠实度/业务/安全组合裁判、报价 Decimal 与 Incoterm 确定性规则、Judge 人工校准、报告回归比较、版本化硬门禁和聚合脱敏报告。新增静态知识、动态 MySQL、确定性计算、人工审批四类路由。 |
| 质量修复 | 混合检索对语义/关键词相关性分别归一化，RRF 与质量分分工；置信门按不同 Parent 比较并把最高相关性 0 判为无证据；抽取式生成器只采用最强 Parent，避免无条件拼接无关证据。 |
| 数据与门禁 | 新增 14 条外贸 dev 和 6 条 challenge 脱敏用例，覆盖 Incoterms、产品、MOQ、物流、HS/统计口径、RFQ、动态数据、报价路由、审批、ACL、撤回、无证据和提示注入；两套本地门禁均通过。 |
| 验证 | 评估/RAG 专项 `20 passed`；根回归 `438 passed, 4 skipped, 3 warnings, 40 subtests passed`。 |
| 生产边界 | 所有 fixture/Mock 报告强制 `production_ready=false`；真实盲测集、人工 Judge 校准、真实 Embedding/Reranker/生成模型、现场验收和线上监控尚未完成。 |
| 操作者 | Codex |

## 2026-07-27（PDF 异步导入与状态可见化）

| 项目 | 内容 |
|---|---|
| 修改位置 | PDF 知识仓库、共享导入协调器、Web API、知识库三语 UI 与异步专项测试 |
| 变更摘要 | manifest 升级为 v4；PDF 上传先原子保存源文件和 `draft/pending` 任务并返回 HTTP 202，再由 8765/8767 共享的单线程 Worker 串行执行解析、PaddleOCR、切块和 SQLite vector/FTS5 BM25/Parent 索引。页面每 2 秒刷新处理中任务，完成后显示已索引，失败时显示安全错误码并支持重试。 |
| 恢复与幂等 | 启动时只恢复 pending/running 任务；终态失败必须显式重试。处理中重复上传复用稳定 ID 且不重复排队；处理中撤回优先，Worker 不得重新发布或遗留索引。 |
| 安全边界 | 复杂布局、OCR 低置信度和无有效文字仍进入人工复核或 needs_ocr，不因异步化绕过 ACL、分类、审批或 revoked 过滤。 |
| 验证 | 异步专项 `4 passed`；完整 RAG `117 passed, 3 skipped`；根回归 `420 passed, 4 skipped, 1 warning, 40 subtests passed`；Python 编译和前端 JS 语法通过。 |
| 操作者 | Codex |

## 2026-07-27（外贸公开数据资料整理）

| 项目 | 内容 |
|---|---|
| 变更摘要 | 新增权威外贸数据来源指南、字段与指标口径说明，以及中国商品出口 2023-2024 可追溯示例 CSV。 |
| 核验范围 | 2026-07-27 实时核验 UN Comtrade、WTO Stats、World Bank WITS/API、ITC Trade Map、海关统计查询和商务部数据中心；海关查询站对自动请求返回 412，文档明确要求人工访问且禁止绕过。 |
| 数据边界 | 仅使用公开聚合数据；不包含买家联系方式、个人信息或来源不明的交易明细。World Bank 与 UN Comtrade 的同名年度指标分别保留，不做覆盖或平均。 |
| 验证 | 三个文件 UTF-8 无替换字符；示例 CSV 为 18 列、3 条数据记录，Python CSV 解析通过。 |
| 操作者 | Codex |

## 2026-07-27（本地 SQLite 持久知识索引）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/sqlite_store.py`、`trade_rag/sqlite_index.py`、Pipeline/配置工厂、启动协调、环境示例、依赖与专项测试 |
| 变更摘要 | 新增 `sqlite-vec==0.1.9` 余弦向量索引、SQLite FTS5 `bm25()` 关键词排序和持久 Parent Store；Child/Parent、稳定 ID、文档版本、ACL、状态、过期时间和引用元数据写入同一 `rag_index.db`。Web 启动和 MCP 查询按 manifest 增量协调，CLI 支持 check、dry-run 和显式 apply。 |
| 启用状态 | 当前本机 `.env` 已设为 `RAG_VECTOR_BACKEND=sqlite`、`RAG_KEYWORD_BACKEND=sqlite`；无项目 `.env` 时的代码兜底仍为 memory，pgvector/Milvus 保持可选且故障不回退。 |
| 数据结果 | 当前 manifest 的 8 条记录均为 revoked/withdrawn，没有活动文档；本地 SQLite 验收后 vector、BM25 和 Parent 行数均为 0，未恢复 trash 内容。 |
| 验证 | SQLite/配置专项 `13 passed`（含 PDF HTTP 导入后原文件、解析产物、manifest、vec0、BM25 与 Parent 持久化）；RAG `112 passed, 3 skipped`；根回归 `413 passed, 4 skipped, 1 warning, 40 subtests passed`；依赖锁检查和 SQLite check/dry-run 通过。 |
| 边界 | `mock-hash-v1` 只证明本地持久链路，不代表真实语义质量；SQLite 面向单机，不替代生产多实例 pgvector/Milvus 验收。 |
| 操作者 | Codex |

## 2026-07-27（PDF 扫描件与图片 OCR）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/` OCR、知识仓库、切块与引用；知识库 API/UI；OCR/PDF/向量后端测试；README 与状态文档 |
| 变更摘要 | PaddleOCR 处理扫描 PDF 页、PDF 内嵌图片和独立 PNG/JPEG/WebP；每份文档使用连续的一基图片索引。OCR 文字生成独立 Parent/Child 并进入语义与关键词索引，图片元数据随 Child 保存，回答引用增加结构化图片字段。 |
| 审批与失败边界 | 低置信度 OCR 必须人工确认后才入库，且不改变公开分类；无文字图片保留 `no_text` 和图片索引但不产生向量；缺页、识别失败和不安全 PDF 继续失败关闭。 |
| Docker 边界 | `.paddlex` 保存在项目目录且不提交 Git；现有 Compose 只包含数据服务，不启动 NanoClaw 或 OCR。 |
| 验证 | OCR/PDF/向量定向测试通过；真实 PaddleOCR 图片与扫描 PDF 冒烟 `1 passed`；根测试 `408 passed, 4 skipped, 40 subtests passed`；Python 编译、前端 JS 语法、112 包锁文件检查和 Compose 静态解析通过。 |
| 操作者 | Codex |

## 2026-07-27（工作空间独立地址）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web.py`、`main.py`、`config.py`、`.env`、`.env.example`、Web/配置测试和状态文档 |
| 变更摘要 | 保留 `127.0.0.1:8765` 营销首页和 `127.0.0.1:8766` 客户门户，新增 `127.0.0.1:8767` 独立工作空间。工作空间端口根路径直接返回完整 UI，并使用 `workspace_web` 渠道名隔离 WebSocket 出站路由；公共端口仍可保留 `/workspace` 兼容入口。 |
| 验证结果 | 相关专项 `33 passed`；根目录全量 `394 passed, 3 skipped, 40 subtests passed`。未启动常驻服务，配置生效需重启 NanoClaw。 |
| 安全边界 | 三个地址均绑定 `127.0.0.1`，只允许本机访问；没有开放局域网或公网监听。 |
| 操作者 | Codex |

## 2026-07-27（工作空间 Agent 记忆闭环）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/`、`session/bounded_manager.py`、`agent/loop.py`、`channels/workspace_memory_api.py`、`channels/web.py`、`main.py`、`config.py`、`.env.example`、工作空间记忆测试与文档 |
| 变更摘要 | 新增确认优先的工作空间长期记忆服务、受限 JSON Patch 工作记忆、成功工具钩子、最终回答单次持久化、独立 SQLite/关键词/向量/outbox、RRF+类型衰减、TTL/待确认审查、确定性命令、项目隔离管理 API、外部 Embedding fail-closed 门禁和 Markdown dry-run/apply 快照迁移。客户记忆和 `trade_rag` 未复用。 |
| 启用状态 | 工作空间总开关、自动提取、混合索引、治理、审查和外部传输默认关闭；legacy fallback 保留。未执行真实迁移，未开启本地运行时，未连接外部 Embedding。 |
| 验证结果 | 记忆专项现为 `81 passed`；后续独立工作空间路由修复后，根目录为 `394 passed, 3 skipped, 40 subtests passed`；`test2/rag_knowledge_base` 无分发测试目录，quickstart smoke 通过。local-hash 仅证明链路，不代表生产语义质量。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与代码变更；本次未代替用户执行 Git 提交或推送。

## 2026-07-26（Docker 数据服务 M6 本地受控发布）

| 项目 | 内容 |
|---|---|
| 修改位置 | Gateway/消息总线/WebSocket 关联、MySQL 005 迁移与可选会话 Repository、`trade_rag/m6_release.py`、M6 测试/Runbook/Acceptance及项目状态文档 |
| 变更摘要 | 增加全局16并发、同会话串行、任务排空、跨实例无正文请求账本和会话租约；新增10k向量、双后端1k Top-K、40会话混合负载、可逆故障和安全治理CLI。 |
| 实时验收 | `m6-20260726-live1` 通过；pgvector P95/P99 52.673/58.432ms，Milvus 401.177/402.459ms；1000原请求仅执行1000次、50重试均识别；各故障RTO低于12秒、RPO=0；根回归371 passed、3 skipped、40 subtests passed。 |
| 安全与边界 | 五服务最终healthy；默认memory；M6 generation保持非活动；不含真实数据/外部模型，未删除volume/旧collection。一次完整Compose诊断在任务输出中回显隔离凭据，需轮换并复验，因此M6操作安全验收暂未签署。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（Docker 数据服务 M4 向量后端应用集成）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/vector_runtime.py`、`trade_rag/pipeline.py`、`trade_rag/server.py`、Web/客户/工作空间入口、M4测试、健康/告警和状态文档 |
| 变更摘要 | 新增配置驱动ManagedVectorStore、启动前检查、自动恢复、liveness/readiness、受保护JSON/Prometheus指标、内容无关审计和告警规则；MCP移除对内存Store私有字段的运行时依赖。 |
| 验收结果 | 默认memory；pgvector/Milvus应用就绪通过；故障时live但not-ready且不回退；MCP、客户和工作空间返回空答案/引用。M4专项6 passed，RAG 76 passed，根回归354 passed、3 skipped、40 subtests passed。 |
| 安全与数据边界 | 指标只允许回环或Bearer；不记录actor、role、query、document、vector或秘密；业务层不直接导入数据库驱动；本地SQLite指纹一致，五个Docker服务healthy。 |
| 当前边界 | 本地单进程可观测性不代表多实例聚合、生产监控、HA、TLS、容量或生产就绪；M5未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（Docker 数据服务 M3 Milvus 隔离验收）

| 项目 | 内容 |
|---|---|
| 修改位置 | `deploy/docker/compose.yaml`、`trade_rag/milvus_store.py`、`trade_rag/milvus_admin.py`、配置/依赖/测试、`deploy/docker/M3_ACCEPTANCE.md` 及项目状态文档 |
| 变更摘要 | 固定 Milvus/etcd/MinIO digest并启动隔离栈；启用鉴权、轮换root密码、创建受限应用身份；新增64维MilvusStore及显式代次/alias管理命令；精确锁定`pymilvus==2.5.18`。 |
| 验收结果 | 五容器 healthy；Milvus live `6 passed`、pgvector `4 passed`、RAG `70 passed, 2 skipped`、根回归 `348 passed, 3 skipped, 1 warning, 40 subtests passed`；alias切换/回滚、跨代次撤回及三组件重启恢复通过。 |
| 数据边界 | 最终仅保留空的`trade_knowledge_v2`和活动alias；五个服务各自named volume，无bind；仅回环发布3307/5433/19530；本地SQLite前后指纹一致；未修改真实根`.env`或导入真实数据。 |
| 当前边界 | 默认后端仍为memory；单节点本地验收不证明HA、TLS、容量、备份恢复、真实向量质量或生产就绪。M4未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（Docker 数据服务 M2 PostgreSQL/pgvector 本地向量验收）

| 项目 | 内容 |
|---|---|
| 修改位置 | `deploy/docker/compose.yaml`、`trade_rag/`、`test/trade_rag/test_pgvector_m2.py`、`.env.example`、依赖/锁文件、`deploy/docker/M2_ACCEPTANCE.md` 及项目状态文档 |
| 变更摘要 | 固定 pgvector 镜像 digest，启动隔离 PostgreSQL；新增 64 维 VectorStore Protocol/PgvectorStore/默认 memory 工厂、显式迁移、配置校验和合同测试；精确锁定 psycopg/pgvector 依赖。 |
| 验收结果 | pgvector `0.8.5`、migration v1、`vector(64)`；live `4 passed`，RAG `65 passed, 1 skipped`，根回归 `343 passed, 2 skipped, 1 warning, 40 subtests passed`；重启恢复、fixture 清理和确定性排序通过。 |
| 数据边界 | 仅 Docker PostgreSQL Schema 被修改；未挂载初始化 SQL、未导入真实知识、未修改本地 SQLite/MySQL或真实根 `.env`。两份 SQLite 元数据未变，可读取的一份 SHA-256 未变。MySQL 与 PostgreSQL 最终均 healthy，只监听 loopback。 |
| 当前边界 | 默认 `RAG_VECTOR_BACKEND=memory`；M2 不证明生产检索质量、容量、Milvus 或生产就绪。M3 未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（Docker 数据服务 M1 隔离 MySQL 运行验收）

| 项目 | 内容 |
|---|---|
| 修改位置 | `deploy/docker/compose.yaml`、`deploy/docker/README.md`、`deploy/docker/M1_ACCEPTANCE.md`、Docker 计划及项目状态文档 |
| 变更摘要 | 拉取 `mysql:8.4` 并固定实际 digest；生成 Git 忽略且不回显的 Docker 专用随机凭据；仅启动 `business/mysql`，完成健康、应用用户查询、容器重启和 named-volume 持久性验收。 |
| 验收结果 | MySQL `8.4.10` healthy；`SELECT 1` 通过；重启后 server UUID 一致；仅存在 MySQL 容器、一个 MySQL volume 和隔离网络；宿主只监听 `127.0.0.1:3307`。 |
| 本地数据边界 | 未挂载/执行业务迁移，未切换 NanoClaw 后端；两份现有 SQLite 的大小和最后写入时间均未变化，可读取的一份 SHA-256 一致。未启动或拉取其他 profiles。 |
| 运行说明 | 全局 Docker `config.json` 仍不可读；使用任务专用 CLI 配置目录和批准的提升权限完成，没有修改全局 ACL。首次查询的短参数拼接失败后按策略停止容器，改用显式长参数复验成功，最终容器保持 healthy。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25 15:50:42 +08:00（Docker 数据服务 M0 静态验收）

| 项目 | 内容 |
|---|---|
| 修改位置 | `deploy/docker/M0_ACCEPTANCE.md`、`doc/DOCKER_DATABASE_VECTOR_SERVICES_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 正式收口隔离 Docker 服务 M0：记录 Docker/Compose 版本、四个 profiles 静态解析结果、named volume、端口、镜像标签及零本地数据库引用证据；将镜像 digest 冻结明确延后到 M1 联网拉取前。 |
| 验收结果 | Docker `29.6.1`、Compose `v5.2.0`；`business`、`vector-local`、`vector-milvus`、`all` 均退出码 0；五个挂载全为 volume，bind mount 为 0；端口只绑定 `127.0.0.1:3307/5433/19530` 且验收时未占用；无 `latest` 标签。 |
| 数据边界 | 未创建真实 Docker `.env`，未执行 `up`、`pull`、数据库连接、Schema、迁移、数据复制或 volume 操作；未修改任何现有本地数据库、Schema、数据和 NanoClaw 数据库配置。 |
| 待处理 | Docker CLI 报告用户 `config.json` 访问权限警告；不影响本次静态解析，但 M1 启动或拉取镜像前必须修复并复验。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（复杂版面 PDF 人工确认后切块）

| 项目 | 内容 |
|---|---|
| 根因 | `internal` 只是访问分类，不代表解析质量已批准；双栏/复杂版面 PDF 会安全停在 `review_required`/`chunk_status=pending`。原实现没有管理员复核后继续切块的状态迁移，且重新加载时切分器会再次拒绝已批准复杂版面。 |
| 修复 | 新增严格资格判定和“确认版面并继续切块”管理动作：仅全页文本覆盖、无 OCR、无空页/部分覆盖警告的复杂版面 PDF 可批准。批准后持久化 `review_approved_at`，执行 PDF-aware Parent/Child 切块、Parent/语义/关键词三路索引，并开放页码预览。 |
| UI 与隐私 | 详情页只在服务端返回 `review_approval_eligible=true` 时显示三语确认按钮；响应不暴露存储文件名、解析产物哈希或本地路径。扫描型和混合文本/扫描 PDF 批准仍返回 409。 |
| 验证方式 | 聚焦 PDF/知识管理/UI 回归 `25 passed`；项目根回归 `338 passed, 1 skipped, 40 subtests passed`；Python compileall 和 `node --check` 通过。实际工作区两份 PDF 已确认符合按钮显示条件，但未自动批准或改写 manifest。 |
| 运行边界 | 当前运行的旧服务进程需重启后才能加载新 API/UI；管理员必须先检查 PDF 文字顺序和完整性再点击确认。未调用外部 OCR/模型，仍是本地 Mock/内存索引验证，不代表生产验收。 |

## 2026-07-25（知识库历史重复 ID 撤回修复）

| 项目 | 内容 |
|---|---|
| 根因 | 旧版本允许相同内容撤回后重导时复用同一 `document_id`。详情和撤回等接口按 manifest 原始顺序取第一条，可能先命中旧 `revoked` 记录并直接返回，导致当前 `published` 记录继续显示。 |
| 修复 | 增加统一活动记录选择器：默认优先最新非 revoked 记录；无活动记录时返回最新历史；撤回重试精确选择 `revoke_pending`。解析产物、切块、索引、分类、详情、撤回和重试入口统一使用该选择规则。 |
| 验证方式 | 新增历史重复 ID 回归，确认详情返回活动记录、再次撤回后默认列表为空且两条历史均为 revoked；知识管理专项 `10 passed`，根回归 `337 passed, 1 skipped, 40 subtests passed`。 |
| 数据边界 | 未自动修改或删除现有知识数据；服务进程需重启后才会加载修复。撤回仍是可恢复操作，物理清理不在本次范围。 |
| 操作者 | Codex |

## 2026-07-25（RAG 知识库 PDF 检索 M6）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/release_gate.py`、`agent/tools/customer_public.py`、`test/fixtures/pdf/golden_questions.json`、`test/fixtures/pdf/performance_baseline.json`、`test/trade_rag/test_pdf_m6_release_gate.py`、`test/trade_rag/pdf_m6_benchmark.py`、`test2/rag_knowledge_base/pdf_portable_contract.json`、`test2/rag_knowledge_base/README.md`、`doc/RAG_PDF_M6_RELEASE_RUNBOOK.md`、PDF 计划及状态文档 |
| 质量门禁 | 建立 6 个脱敏金问题，覆盖中英术语、表格字段、条件说明与页码；本地 Recall@30、页码定位和事实引用覆盖均为 100%。无证据返回空引用；ACL 越权阻断率 100%，撤回后命中率 0。聚合报告不保存问题、答案、正文、哈希或路径，并始终声明非生产就绪。 |
| 客户公开边界 | 修复客户公开知识工具未装载显式 public PDF 的缺口；public PDF 通过稳定 Parent/Child 产物进入临时受控索引，internal PDF 和撤回 PDF 不可见。PDF 接口为可选能力，保持已有最小 Repository/公共记忆测试替身兼容。 |
| 性能与恢复 | 可重复 20/100/300 页合成基线均完成解析、重建和三路索引，单次观测解析约 871/1,576/3,323 ms，索引约 108/86/185 ms，300 页为 70 Parent/300 Child/300 Indexed。该门禁只防止本地数量级退化；父进程 tracemalloc 不含解析子进程 RSS，不是生产 P95/SLO。 |
| 验证方式 | M6 专项 `5 passed`；知识库、Web、客户公开读取及全部 trade_rag 组合 `106 passed`；根回归 `336 passed, 1 skipped, 40 subtests passed`；Python compileall、`node --check`、便携契约校验及 quickstart 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 实施边界 | test2 只同步 `contract_only` JSON，没有复制 PDF 运行实现。未调用外部 OCR/模型，未部署 PostgreSQL/pgvector、Milvus、Elasticsearch 或真实 Embedding；未测目标硬件解析子进程 RSS、并发、生产恢复、红队或真实获批企业 PDF。M6 通过只代表本地 PDF 检索 MVP 完成。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（Docker 数据库与向量服务实施计划）

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/DOCKER_DATABASE_VECTOR_SERVICES_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 新增 MySQL、PostgreSQL/pgvector 和 Milvus 的 Docker 服务实施计划，明确三库职责、Compose profiles、网络/卷/秘密、初始化迁移、统一 VectorStore 契约、M0-M6 阶段、功能/安全/并发/恢复验收及回滚策略。 |
| 原因 | 把仓库已有 MySQL Repository/迁移和“本地 pgvector、生产 Milvus”设计整理为可执行基础设施路线，同时避免把计划误报为已部署服务。 |
| 验证方式 | 对照 `pyproject.toml`、`requirements.txt`、`test2/docker-compose.mysql.example.yml`、`agent/business/migrations/`、`trade_rag/`、RAG 场景 C 计划及 MySQL 治理手册复核；检查 Markdown 表格、Mermaid、阶段边界和未实施声明。本轮未运行 Docker、未拉镜像、未连接数据库。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（隔离 Docker 数据服务定义）

| 项目 | 内容 |
|---|---|
| 修改位置 | `deploy/docker/compose.yaml`、`deploy/docker/.env.example`、`deploy/docker/README.md`、`.gitignore`、Docker 计划与进度文档 |
| 变更摘要 | 新增 MySQL、PostgreSQL/pgvector、Milvus/etcd/MinIO profiles；全部使用独立 bridge 网络与 named volumes，宿主端口仅绑定 `127.0.0.1`，Docker MySQL/PostgreSQL 分别默认使用 3307/5433。 |
| 本地数据边界 | 未挂载本地 SQLite、数据库目录、知识库、会话或 `agent/business/migrations/`；未修改根 `.env.example`、应用配置、Repository、数据库 schema 或数据。 |
| 验证方式 | 使用 Docker Compose 进行静态配置解析；未执行 `docker compose up`、镜像拉取、数据库连接或迁移。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M5）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/knowledge_repository.py`、`channels/web.py`、`channels/web_ui/index.html`、`channels/web_ui/static/app.js`、`channels/web_ui/static/app.css`、`test/trade_rag/test_pdf_m5_web_ui.py`、`test/test_email_admin_m2.py`、PDF 计划及项目状态文档 |
| 变更摘要 | Web 知识库开放 PDF 持久导入，列表展示文档类型、分类、parse/chunk/index、页数/字符数和 Parent/Child/Indexed 计数；详情展示 OCR/人工复核、警告、解析/哈希/模型/代次元数据和最多 12 个 Child 的页码预览。保留失败重试、可恢复撤回及 internal 默认分类，显式分类变更会重建 M4 ACL 索引。新增中英德文案和资源缓存版本。 |
| API 与隐私 | 新增 `GET /api/knowledge/documents/{document_id}/chunks-preview?limit=12`；只返回有界 Parent/Child 摘要和页码，不返回私有存储名、解析产物哈希、绝对路径或全文导出。OCR/复核文档返回 409 并保持不可索引。 |
| 浏览器验证 | 使用本地合成两页 PDF 验证 1280×720 桌面和 390×844 移动布局：六项汇总、2/2/2 计数、三阶段状态、详情页码预览、internal→public→internal 分类及索引代次均正确；移动详情全宽、无横向溢出。发现并修复非对话页业务流程浮窗覆盖知识列表；控制台无错误或警告。测试服务已停止，合成数据保留在 `.tmp/pdf-m5-browser-20260725` 便于复核。 |
| 验证方式 | M5/M4/M2 专项 `16 passed`；知识管理、Web 导入、既有 M5 验收与全部 `trade_rag` 组合 `82 passed`；项目根回归 `331 passed, 1 skipped, 40 subtests passed`；Python compileall 与 `node --check` 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 实施边界 | 浏览器只使用本地合成 PDF；未调用外部 OCR/模型，未部署 PostgreSQL/pgvector、Milvus、Elasticsearch 或真实 Embedding。M6 金问题、召回/引用、安全、性能、恢复和生产发布门禁未实施；`/api/files/read` 与持久 `/api/knowledge/import` 仍是不同语义。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M4）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/contracts.py`、`trade_rag/stores.py`、`trade_rag/pipeline.py`、`trade_rag/generation.py`、`trade_rag/server.py`、`trade_rag/knowledge_repository.py`、`channels/web.py`、`test/trade_rag/test_pdf_m2_repository.py`、`test/trade_rag/test_pdf_m3_chunking.py`、`test/trade_rag/test_pdf_m4_indexing.py`、PDF 计划及项目状态文档 |
| 变更摘要 | 实施 M4 本地 PDF 检索闭环：Parent、语义 Child、关键词 Child 在同一文档版本中写入并校验真实数量；失败时清理三类派生数据。manifest 显式记录 running/indexed/failed、实际 indexed_count、Embedding 模型和递增代次。Web 导入立即索引合格 PDF，MCP 重启可从权威解析产物和稳定块重建。 |
| 检索与引用 | 语义/BM25 近似混合召回、RRF、多查询和可选 Rerank 只处理 Child；按 Parent ID 去重后经业务单元/角色 ACL 从 Parent Store 扩展答案上下文。答案使用 Parent 正文，引用仍返回命中 Child ID 和准确 PDF 页码。分类变更重建 ACL 代次，撤回同步删除 Parent、语义和关键词索引。 |
| 失败与恢复 | Embedding 在写入前完成；任一 Store 写入或数量不一致均 fail closed，manifest 记录 `knowledge_index_failed` 和 `indexed_count=0`。既有 retry-index 可重新构建三类 Store；撤回失败仍保持不可搜索并可重试。 |
| 验证方式 | M0-M4 专项 `31 passed`；知识管理、Web 文件导入、M5 验收及 `trade_rag` 组合回归 `78 passed`；项目根测试 `327 passed, 1 skipped, 40 subtests passed`；Python compileall 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 实施边界 | 当前 Embedding、Parent/语义/关键词 Store 均为本地 Mock/内存实现，进程重启通过权威产物重建；未部署 PostgreSQL/pgvector、Milvus、Elasticsearch 或真实 Embedding。M5 管理 UI 与 M6 金集、性能、安全和生产发布门禁尚未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M3）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/contracts.py`、`trade_rag/chunking.py`、`trade_rag/stores.py`、`trade_rag/knowledge_repository.py`、`test/trade_rag/test_pdf_m2_repository.py`、`test/trade_rag/test_pdf_m3_chunking.py`、PDF 计划及项目状态文档 |
| 变更摘要 | 新增版本化 PDF-aware Parent/Child 切分器，依据章节、表格、段落和相邻页组织父子块，使用文档版本、切分版本、页范围、序号和内容哈希生成稳定 ID；保留完整页码/章节/块类型/ACL/分类/语言/源哈希 metadata。长表按行切分并重复表名/表头，标题与正文组合，页码/版权噪声丢弃。新增 ACL 感知的内存 Parent Store及按文档版本删除。 |
| 持久化与预览 | 可索引 PDF 在 M2 持久化后推进到 `chunk_status=ready`，记录准确 Parent/Child 数量、`splitter_version=pdf-aware-v1`、`index_status=pending` 和 `indexed_count=0`。Repository 可从权威解析产物重建并核对块计数，提供有界且不暴露本地路径的重启稳定预览；扫描/混合 PDF 不切块。 |
| 验证方式 | M0-M3 专项 `27 passed`；知识管理、Web 文件导入、M5 验收及 `trade_rag` 组合回归 `74 passed`；项目根测试 `323 passed, 1 skipped, 40 subtests passed`；Python compileall 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 实施边界 | M3 未把 PDF 写入语义/关键词索引，也未将 Parent Store 接入 Pipeline 检索；未实现父块上下文扩展、Child 页码引用、三路原子回滚、索引代次、撤回/重试闭环。这些属于 M4；M5 UI、M6 发布评估、外部 OCR/模型和生产存储也未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M2）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/knowledge_repository.py`、`channels/web.py`、`test/trade_rag/test_pdf_m2_repository.py`、`test/test_knowledge_admin.py`、PDF 计划及项目状态文档 |
| 变更摘要 | 将知识 manifest 升级为 v3，分离保存原 PDF 与页级解析 JSON，增加 source/content/parsed 三类哈希、解析器与 OCR 元数据及 parse/chunk/index 阶段状态。PDF 以原始二进制幂等，同正文不同二进制保留独立来源；支持 v1/v2 备份后惰性迁移、重启恢复、原子失败回滚、双产物可恢复撤回，并把安全解析元数据接入 Web 知识导入。 |
| 完整性与隐私 | 重启加载会验证原文件、解析产物和规范化正文；v3 文件被替换时保持原哈希并 fail closed，禁止静默重算信任。API 响应不暴露私有存储名和 `parsed_hash`。扫描/混合 PDF 保持 `review_required`，所有 PDF 在 M3/M4 前均不进入 RAG。 |
| 验证方式 | M2 专项 `8 passed`；知识管理、Web 文件导入、M5 验收及 `trade_rag` 组合回归 `69 passed`；项目根测试 `318 passed, 1 skipped, 40 subtests passed`；Python compileall 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 实施边界 | 未实施 M3 PDF-aware Parent/Child 切块、稳定块 ID 或 Parent Store；未实施 M4 PDF 索引/检索/页码引用、M5 前端 PDF 选择与状态 UI、M6 发布评估；未调用外部 OCR/模型，未部署 PostgreSQL、Milvus 或其他生产索引。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（客户门户登录入口文字化）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/customer.html`、`channels/web_ui/static/customer-preview.js`、`channels/web_ui/static/css/customer.css`、`test/test_customer_auth.py`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 将菜单栏中的“♙”客户账号图标按钮改为文字按钮。未登录时按语言显示“客户登录 / Sign in / Anmelden”，认证成功后显示“客户账号 / Customer account / Kundenkonto”；按钮保留原登录弹窗行为并同步可访问名称。新增折叠菜单、展开菜单和手机底栏样式。 |
| 响应式修复 | 浏览器验证发现菜单展开状态会在 390px 手机底栏重新显示品牌区并把登录按钮挤出视口；手机断点现明确隐藏重复品牌区，并为最长德语文本保留 66px 宽度。 |
| 验证方式 | `test_customer_auth.py`、`test_customer_identity.py`、`test_web_file_import.py` 共 39 项通过；JavaScript 语法通过；浏览器验证桌面 64×34、展开菜单 176×34、390px 窄屏 66×34，中文和德语均无文字溢出，点击可正常打开登录窗口。 |
| 操作者 | Codex |

### 2026-07-25 客户门户登录二次修复

- 根因修复：客户 HTML、CSS、JS 增加版本化 URL，门户页面与白名单静态资源返回 `Cache-Control: no-cache, must-revalidate`，避免浏览器继续运行缺少翻译与关闭逻辑的旧脚本。
- 登录入口改为独立的 `customerAccountLabel` 翻译节点，账号状态变化和中/英/德切换都直接刷新该节点及 `aria-label`。
- 登录弹窗重绘为桌面左右分栏、移动端上下分区的客户门户卡片；取消与右上角关闭均采用 `method="dialog"`/`formmethod="dialog"` 原生语义并带脚本兜底。
- 浏览器验证：英文 `Sign in` 切换中文 `客户登录`、德语 `Anmelden` 均同步；取消和右上角关闭后 `dialog.open=false`；390×844 德语弹窗无横向溢出。

## 2026-07-25（客户门户登录国际化与弹窗优化）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/customer.html`、`channels/web_ui/static/customer-preview.js`、`channels/web_ui/static/css/customer.css`、`test/test_customer_auth.py`、`test/test_customer_portal_contact.py`、进度文档 |
| 变更摘要 | 登录入口改为标准 `data-i18n` 与动态账号状态双重更新，中/英/德切换时同步可见文字和无障碍名称。重做登录弹窗：品牌标题区、独立关闭按钮、说明卡、带图标输入框、翻译占位符、错误态、主次操作、安全提示、暗色模式和 390px 窄屏布局。每次打开会恢复当前语言的普通提示，避免上次失败信息残留。 |
| 验证方式 | 浏览器实测德语 `Anmelden`，切换英文后可见文字与 `aria-label` 均为 `Sign in`；桌面弹窗视觉检查通过，390×844 下弹窗左右边界为 12px/约 12px且页面无横向溢出。专项测试与 JavaScript 语法通过，未提交真实登录凭据。 |
| 操作者 | Codex |

## 2026-07-25（双 Agent 记忆管理 M6）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/deletion.py`、`governance.py`、`backup.py`、`index_rebuild.py`、`stores/sqlite.py`、`working_memory.py`、`config.py`、`.env.example`、`test/test_memory_m6.py` 及状态文档 |
| 变更摘要 | 增加只处理显式到期的 TTL 审查、仅身份服务可调用的同租户账号合并与审计、保存步骤/重试/稳定错误码的账号删除编排。删除必须完成消息/对话、工作记忆、长期记忆擦除、派生索引 outbox 和外部缓存/peer 回调后才标记完成。增加 SQLite online backup、带 SHA-256/schema/源标识的 manifest、校验后 staging 恢复，以及从 active/有效同意/未过期权威行重建关键词和向量索引。 |
| 安全边界 | 稳定记忆没有 `expires_at` 时不按年龄删除；跨租户、客户/模型发起的账号合并 fail closed；主存失效后读取仍二次校验，关闭新读取开关不会恢复墓碑或正文；恢复不覆盖在线库。全部 M6 开关默认关闭。 |
| 验证方式 | M6 专项覆盖 TTL、无 TTL 保留、账号隔离、幂等/断点删除、索引未确认禁止完成、合并权限、备份损坏拒绝、重建排除失效行及失败不动旧索引；完整回归、编译和 JS 语法结果见本轮最终记录。 |
| 未完成门禁 | 30 天匿名保留、24 小时 peer TTL、72 小时删除 SLA 是本地占位值而非获批政策；生产 SSO/IdP、法务期限、备份加密/异地存储、恢复演练、数据库角色和生产向量后端未验收。M5 真实评估门禁仍未通过。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索实施计划）

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/RAG_PDF_RETRIEVAL_IMPLEMENTATION_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于参考 PDF 流程和当前 NanoClaw 实现新增 M0-M6 计划，覆盖 PDF 安全识别、页级解析、归一化、OCR 门禁、manifest v3 双哈希、PDF-aware 父子切块、Parent 回取、真实索引状态、页码引用、Web 管理、测试与发布门禁。 |
| 原因 | 当前知识导入仅支持 UTF-8 文本；同时 `index_status=ready` 只代表切块成功，`RagPipeline` 尚未保存/回取 Parent，不能直接通过增加 `.pdf` 后缀宣称实现 PDF small-to-big 检索。 |
| 验证方式 | 对照 `channels/web.py`、`channels/web_ui/index.html`、`trade_rag/knowledge_repository.py`、`loaders.py`、`contracts.py`、`chunking.py`、`stores.py`、`pipeline.py`、`server.py`、现有知识库测试及场景 C 计划；检查 Markdown 标题、表格、Mermaid、状态边界和依赖表述。 |
| 实施边界 | 本次仅修改文档；未安装 PDF 依赖，未实现解析/OCR/索引代码，未导入 PDF，未部署 PostgreSQL/pgvector/Milvus，也未调用外部服务。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M1）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/parsers/__init__.py`、`trade_rag/parsers/pdf.py`、`trade_rag/contracts.py`、`test/trade_rag/pdf_fixture_factory.py`、`test/fixtures/pdf/manifest.json`、`test/trade_rag/test_pdf_m1_parser.py`、PDF 计划及项目状态文档 |
| 变更摘要 | 实施 M1 安全解析：PDF 扩展名/MIME/魔数一致性、大小/页数/字符/加密/损坏门禁、受并发保护的可终止解析子进程和硬超时；接入 pdfplumber 主解析、pypdf 显式回退、页级归一化、重复页眉页脚移除、双栏检测、逐页质量统计及 index/review_required/needs_ocr 路由。 |
| 原因 | 仅能“读出文字”不足以安全进入知识库；必须先证明异常 PDF 有稳定错误、扫描/混合/复杂版面不会误报可索引，并保证第三方解析库卡住时可终止。 |
| 验证方式 | PDF M0+M1 14 项通过；PDF/RAG/知识管理/Web 文件定向回归 56 项通过；项目根测试 `310 passed, 1 skipped, 40 subtests passed`（1 条既有 Starlette TestClient/httpx 弃用警告）；Python compileall 通过。 |
| 实施边界 | M1 只返回内存 `ParseResult`，没有读取真实企业 PDF、调用外部 OCR/模型、写入 manifest、保存原文件/解析产物、修改 Web 上传接口或进入 RAG 索引；上述工作属于 M2 及以后。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-25（RAG 知识库 PDF 检索 M0）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/contracts.py`、`trade_rag/config.py`、`.env.example`、`requirements.txt`、`test/fixtures/pdf/manifest.json`、`test/trade_rag/pdf_fixture_factory.py`、`test/trade_rag/test_pdf_m0_contracts.py`、PDF 计划及项目状态文档 |
| 变更摘要 | 实施 PDF 计划 M0：冻结页级来源、解析块/结果、处理状态、四种导入路由、9 个错误码、6 个警告码和首版资源/OCR 阈值；建立 11 类脱敏 PDF 样本清单及可重复生成器，覆盖文本、中英、表格、双栏、重复页眉、扫描、混合、加密、损坏、超页和超大输入。同步已安装并锁定的 `pdfplumber==0.11.10`、`pypdf==6.14.2` 到运行依赖记录。 |
| 原因 | M1 解析器需要先依赖稳定、严格且可自动验证的输入输出契约，避免依据少量 PDF 的偶然解析结果反复修改 manifest、OCR 判定和引用位置模型。 |
| 验证方式 | M0 定向测试 5 项通过；PDF/RAG/知识管理定向回归 47 项通过；项目根测试 `301 passed, 1 skipped, 40 subtests passed`（1 条既有 Starlette TestClient/httpx 弃用警告）；Python compileall 通过；本地解释器确认 PDF 依赖版本。 |
| 实施边界 | M0 不解析用户或企业 PDF，不修改 Web 导入和索引运行链路；M1 的类型分派、魔数/限额执行、正文提取、归一化及 needs_ocr 判定尚未实现。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24（双 Agent 记忆管理 M5）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/stores/keyword.py`、`agent/memory_runtime/stores/vector.py`、`agent/memory_runtime/retrieval.py`、`agent/memory_runtime/outbox.py`、`agent/memory_runtime/stores/sqlite.py`、`agent/memory_runtime/models.py`、`agent/memory_runtime/services/customer_reader.py`、`main.py`、`config.py`、`.env.example`、`test/test_memory_m5.py`、M5 状态文档 |
| 变更摘要 | 增加物理独立的客户关键词/向量派生索引、版本化 Embedding 接口和无网络 local-hash 适配器；召回先精确作用域过滤，采用 RRF 融合并保留关键词/向量排名、贡献和索引版本解释，再由客户主存重新校验 active/同意/有效期。激活、纠正、撤回和删除与无正文 outbox 同事务；单例 Worker 幂等更新两类索引并对失败退避重试。Customer Agent 生命周期和 M4 Reader 使用只读索引连接，写入只由 Worker 执行。 |
| 安全边界 | 跨账号相同向量在索引查询前已隔离；即使手工污染派生索引账号字段，主存再校验仍返回 0 条越权结果。同意撤回后即使删除事件尚未消费也立即不可召回。outbox 不复制正文，Embedding/索引失败不破坏主存；外部 backend 未获批准时配置 fail closed，不发生网络或客户数据传输。local-hash 不是生产语义模型。 |
| 验证方式 | M5 专项 8 项通过；主项目全量 `288 passed, 1 skipped, 40 subtests passed`；Python compileall 和 JavaScript 语法检查通过。覆盖事务回滚、索引版本、模型维度不兼容、跨账号零泄漏、派生索引污染、同意撤回、纠正清旧索引、Embedding 超时重试、bootstrap 幂等、M4 只读融合索引。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 未完成门禁 | 未使用真实客户评估集校准 Top-K、阈值和权重；未批准外部 Embedding 数据边界或部署生产向量后端。因此 M5 只标记本地核心代码完成，不标记生产验收完成。记录本阶段时 M6 尚未实施；其后续本地状态见上方 M6 记录。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24（双 Agent 记忆管理 M4）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/models.py`、`agent/memory_runtime/services/customer_reader.py`、`agent/tools/read_customer_memory.py`、`agent/tools/registry.py`、`agent/tools/spawn.py`、`main.py`、`config.py`、`.env.example`、`test/test_workspace_customer_memory_reader.py`、M4 状态文档 |
| 变更摘要 | 实施工作空间到客户记忆的单向读取：新增 SQLite `mode=ro` + `query_only` 只读适配器、角色/用途门禁的 CustomerMemoryReader、只返回摘要/类型/置信度/生效时间的最小只读模型，以及工作空间独立审计库。允许和拒绝均记录 operator、tenant、目标账号、用途、结果 ID/数量和稳定错误码，不记录查询、记忆正文或客户端可控来源文本。新增 `read_customer_memory` 内部工具，仅主工作空间 Agent 在开关开启且可信进程身份齐备时注册。 |
| 安全边界 | 工具 schema 不包含 operator/tenant/top_k；客户数据库连接不能执行写 SQL，审计写入独立工作空间库；工具结果标记 `internal_only`、`supporting_memory_only`，不得作为报价/库存/审批/交易权威。该工具设置为不可继承，SpawnSubagent 不会复制；Customer Agent 即使配置对象带 M4 开关仍只有两个公开工具。缺少 M3、operator 或 tenant 时配置 fail closed。 |
| 验证方式 | M0-M4/客户定向测试 55 项通过；主项目全量 `278 passed, 1 skipped, 40 subtests passed`；Python compileall 和 6 个 JavaScript 文件语法检查通过。覆盖缺角色拒绝审计、错误租户零结果、非法用途拒绝、最小化输出、只读 SQL 失败、审计故障 fail closed、工具 schema、子 Agent 不继承、工作空间条件注册及 Customer Agent 负向边界。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 未实施 | M5 向量/Embedding、混合检索、索引版本和 outbox；M6 TTL、备份恢复、删除 SLA 与受控生产发布。生产 SSO/IdP、岗位映射和独立数据库角色尚未部署或验收。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24（双 Agent 记忆管理 M3）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/stores/sqlite.py`、`agent/memory_runtime/services/customer_memory.py`、`agent/memory_runtime/lifecycle.py`、`agent/memory_runtime/context_provider.py`、`channels/customer_memory_api.py`、`agent/tools/customer_public.py`、`channels/customer_portal.py`、`main.py`、`config.py`、M3 测试及状态文档 |
| 变更摘要 | 实施物理隔离的客户、工作空间和批准公开 SQLite 长期记忆主存。客户链路支持显式候选、用途/类别同意、激活、作用域词法 Top-K、乐观版本、纠正/替代、同意撤回、拥有者导出、单条 tombstone 删除及幂等作用域删除；认证 API 覆盖完整治理生命周期。结构化生命周期只注入工作状态和筛选后的 Top-K，不再同时注入完整 Markdown；`PUBLIC_MEMORY.md` 批准条目幂等导入独立公开 Store，并由公开知识工具按需读取。 |
| 安全边界 | 所有客户操作由认证会话产生 tenant/account，跨账号 UUID 统一拒绝；候选不会在同意前召回，同意撤回立即停止召回；单条删除清空正文、摘要与来源。工作空间表不含 `account_id`，Customer Agent 无工作空间 Store/工具。报价、库存、审批和交易状态不以记忆为权威。全部新能力默认关闭。 |
| 验证方式 | M0-M3/客户定向测试 34 项通过；主项目全量 `269 passed, 1 skipped, 40 subtests passed`；Python compileall 和 6 个 JavaScript 文件语法检查通过。覆盖结构化 prompt 注入、公开 Store 工具读取、purpose/conversation 作用域、纠正 API、版本冲突、跨账号拒绝及幂等删除。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 未实施 | M4 内部操作者身份、只读数据库角色、CustomerMemoryReader 与审计；M5 向量/Embedding、混合检索、索引版本和 outbox；M6 TTL、备份恢复、删除 SLA 与受控生产发布。未创建或启用真实客户、工作空间或公开记忆数据库。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24 21:00:00 +08:00（双 Agent 记忆管理 M2）

| 项目 | 内容 |
|---|---|
| 修改位置 | `session/bounded_manager.py`、`agent/memory_runtime/compaction.py`、`working_memory.py`、`services/working_memory.py`、`context_provider.py`、`lifecycle.py`、`models.py`、`agent/context.py`、`agent/loop.py`、`session/customer_conversation.py`、`channels/customer_conversation_api.py`、`channels/customer_portal.py`、`gateway.py`、`main.py`、`config.py`、`.env.example`、`test/test_memory_m2.py`、M2 设计/进度文档 |
| 变更摘要 | 实施 M2 有界会话与工作记忆：按最后 N 个 `role=user` 起点保留完整轮次并校验 tool-call/result 配对；摘要成功后将原始冷消息按 compaction ID fsync 到归档，再用临时文件 fsync + `os.replace` 原子替换活动 JSONL并写最小审计，任一步失败均保留或回滚原活动历史。新增物理分离的客户/工作空间 SQLite 工作记忆、来源/确认状态和乐观版本；AgentLoop 注入可选 prepare/observe/complete/abort 生命周期，结构化工作状态按作用域注入且不同时加载工作空间 Markdown 长期记忆。删除客户对话同步删除工作记忆、清理请求缓存并通知 Gateway 释放 Customer/peer Agent。 |
| 安全边界 | M2 不创建长期记忆候选、不启用向量检索；任意模型/工具文本不会自动升级为 confirmed。客户 Store 所有读取和删除包含 tenant/account/conversation；工作空间 Store 物理表不含 account_id。新工作空间和客户会话记忆开关默认关闭，现有会话不会批量迁移或改写。 |
| 验证方式 | M0-M2/客户定向测试 57 项通过；主项目全量 `254 passed, 1 skipped, 40 subtests passed`；Python compileall 和客户门户 JavaScript 语法通过。专项覆盖首次作用域状态初始化、跨轮 assistant 历史连续性、结构化工作记忆注入及异常 abort；仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 未实施 | 匿名对话认领仍待单独完成；M3-M6 的长期记忆主存、同意/候选/纠正/导出、工作空间单向读取、混合检索和治理未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24 20:10:00 +08:00（双 Agent 记忆管理 M1）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/customer_identity/`、`session/customer_conversation.py`、`channels/customer_auth_api.py`、`channels/customer_conversation_api.py`、`channels/customer_portal.py`、`channels/web_ui/customer.html`、`channels/web_ui/static/customer-preview.js`、`gateway.py`、`main.py`、`.env.example`、`test/test_customer_auth.py`、`test/test_customer_portal_contact.py`、M1 设计/进度文档 |
| 变更摘要 | 实施 M1 客户账号与服务端历史：SQLite 账号/标识/认证会话表只保存随机 token 哈希；增加可注入 PasswordHasher 与 Argon2id 适配器、统一登录失败、锁定计数、会话撤销/轮换、双提交 CSRF；实现所有公开方法强制 `CustomerOwner(tenant_id,account_id)` 的对话/消息 Repository、不透明签名 cursor、乐观版本、幂等消息和删除任务；增加登录/历史 HTTP Router，并让认证 WebSocket 从 HttpOnly Cookie 解析服务端身份、逐条校验对话所有权后发布可信上下文。客户门户登录后从服务端恢复本账号对话和消息。 |
| 安全边界 | 客户负载中的伪造 `account_id` 被忽略；跨账号资源统一 404；Cookie/token/密码不进入消息、模型或日志。新认证默认关闭；生产启用要求环境会话密钥和已批准的 Argon2id 依赖，当前未安装或锁定该依赖，未创建工作区认证数据库。 |
| 验证方式 | M0/M1/客户门户定向测试 45 项通过；主项目全量 `242 passed, 1 skipped, 40 subtests passed`；JavaScript 语法及 Python compileall 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 未实施 | M2 有界活动上下文、冷归档、结构化工作记忆、匿名认领与 peer/cache 删除级联；M3-M6 长期记忆、单向读取、混合检索和治理。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24 19:17:39 +08:00（双 Agent 记忆管理 M0）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/memory_runtime/`、`config.py`、`.env.example`、`test/test_memory_scope_policy.py`、`test/test_memory_lifecycle.py`、`test/test_memory_runtime_config.py`、`docs/architecture/双Agent记忆管理代码设计.md`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按设计迁移顺序完成 M0：新增 Actor/Scope/Memory/Consent/WorkingMemory/turn 事件模型，稳定错误合同、确定性 MemoryPolicy、MemoryStore/ContextProvider/AgentMemoryLifecycle Protocol，以及不注入、不写入的 no-op 实现；增加配置合同并保持账号、工作空间记忆、客户长期记忆和工作空间读客户记忆四类开关默认关闭。 |
| 原因 | 先冻结跨 realm、租户和账号的服务端安全合同，同时避免在账号方式、密码哈希依赖、内部操作者身份及同意策略未确认前越过 M0 实施 M1。 |
| 验证方式 | M0 定向测试 13 项通过；主项目全量 `237 passed, 1 skipped, 40 subtests passed`；`python -m compileall -q agent/memory_runtime config.py` 通过。仅有既有 Starlette TestClient/httpx 弃用警告。 |
| 状态边界 | 未创建账号/记忆数据库，未增加登录或历史 API，未接入 `AgentLoop`，未启用结构化记忆读写；M1-M6 未实施。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-24（双 Agent 记忆管理代码设计）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/architecture/双Agent记忆管理代码设计.md`、`docs/architecture/工作空间与客户Agent记忆管理设计.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 将双 Agent 记忆架构下钻为可实施代码设计：新增 `agent/memory_runtime/`、客户身份模块、账号级会话模块、客户 API Router 和工作空间只读客户记忆工具的目标目录；定义 Actor/Scope/Memory/WorkingMemory 模型、四个隔离数据库、SQLite DDL、Repository/Service/Policy/Lifecycle 接口、HTTP/WebSocket 合同、AgentLoop/ContextBuilder/main 装配、前端拆分、单向 ACL 测试矩阵、故障测试和 M0-M6 迁移顺序。 |
| 关键边界 | 现有 `agent/memory.py` 在迁移期仅作为 Legacy 压缩器；客户身份一律来自服务端认证会话，账号查询必须带 tenant/account owner 条件；Customer Agent 不具备工作空间 Store 凭据或工具；工作空间只读客户记忆依赖尚未实现的内部操作者身份、只读数据库角色、用途门禁和审计。 |
| 依赖核验 | 当前锁定 Python 3.11.9、FastAPI 0.136.1、Starlette 1.3.1、Pydantic 2.13.4、Uvicorn 0.46.0、HTTPX 0.28.1、WebSockets 15.0.1、Cryptography 49.0.0；Argon2/Passlib/Bcrypt 均未锁定，设计明确标为实施前待选，不虚构版本。 |
| 验证方式 | 对照当前记忆、上下文、AgentLoop、SessionManager、ConversationService、CustomerAgent、peer、Portal、Gateway、配置、SQLite Repository 和测试结构核验代码落点；检查 Markdown 围栏、Mermaid、SQL、表格、精确依赖版本和“设计未实施”状态。本次仅修改 Markdown。 |
| 操作者 | Codex |

## 2026-07-24（客户账号长期记忆、历史恢复与单向 ACL 设计补充）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/architecture/工作空间与客户Agent记忆管理设计.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 在双 Agent 记忆设计中增加客户账号/认证模型、服务端认证会话、账号级对话元数据、登录后分页恢复历史、匿名对话显式认领、按 `account_id` 保存长期记忆及账号注销删除合同；增加单向 ACL 矩阵和 `CustomerMemoryReader`，允许具备内部角色、客户归属和明确用途的工作空间 Agent 审计式只读客户记忆，同时从 Customer Agent 的进程身份、数据库角色、工具、配置、召回器和缓存路径上禁止读取工作空间私有记忆。 |
| 状态边界 | 当前客户门户仍只有匿名签名 Cookie、前端对话状态和独立客户目录，没有账号 Repository、登录 API、服务端历史列表或账号级长期记忆；本文更新仍是设计，M0-M7 均未实施。 |
| 验证方式 | 对照 `channels/customer_portal.py`、客户前端脚本、`gateway.py`、`main.py`、`agent/customer_agent.py`、`agent/peer_coordination.py`、`agent/context.py` 与 `session/manager.py` 核验当前边界；检查账号所有权、单向 ACL、Mermaid、配置、阶段和验收项是否一致。本次仅修改 Markdown。 |
| 操作者 | Codex |

## 2026-07-24（工作空间与客户 Agent 记忆管理设计）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/architecture/工作空间与客户Agent记忆管理设计.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 以 `docs/archive/记忆管理更新.md` 的三层记忆模型为基础，结合当前 `CustomerAgent`、独立客户会话/公开记忆、匿名签名 Cookie 和 `WorkspacePeerCoordinator` 实现，完成工作空间私有域、客户对话域、认证客户私有域、批准公开域的双 Agent 记忆设计；补充作用域合同、工作记忆模型、统一数据模型、生命周期、物理隔离、bridge 级联删除、M0-M6 路线和验收标准。 |
| 关键判断 | `PUBLIC_MEMORY.md` 是组织级批准公开资料而非客户画像；匿名 Cookie 不足以建立跨设备客户长期记忆；客户历史未挂载压缩器且前端删除只影响 DOM；peer 历史持久化客户原文但缺少 TTL 和级联删除。设计因此默认匿名客户只保留有界对话/询盘工作记忆，个人长期记忆延后到生产身份与显式同意完成后。 |
| 验证方式 | 对照记忆、上下文、AgentLoop、CustomerAgent、peer 协作、SessionManager、Gateway、客户门户、客户前端脚本、配置和测试核验现状；检查 Mermaid、表格、代码围栏和设计/实现状态边界。本次仅修改 Markdown，未改运行代码。 |
| 操作者 | Codex |

## 2026-07-24（客户门户独立 Agent、独立记忆与强制防泄露）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/customer_agent.py`、`agent/customer_security.py`、`workspace/customer_memory/PUBLIC_MEMORY.md`、`customer_identity.md`、`config.py`、`config.json`、`.env.example`、`main.py`、`agent/context.py`、`agent/loop.py`、`gateway.py`、`channels/customer_portal.py`、客户 HTML/JS、客户测试、README 及同步的 `test2` 客户配置/说明 |
| 变更摘要 | 客户门户不再只是通用 Agent 的条件分支，而由显式 `CustomerAgent` 独立组装；Provider、会话目录、身份和经人工批准的公开记忆均独立。新增两个服务器控制的只读工具：仅检索显式 `public` 知识资料，以及仅返回产品公开字段/MOQ/询盘数量可供结论的产品目录查询。客户 Agent 仍不创建 MCP 管理器、SkillsLoader、内部记忆压缩器、WorkflowService 或任何文件/命令/Web/邮件/原始数据库工具。zh/en/de 仍由服务端可信上下文控制。 |
| 安全边界 | 主边界是企业私密数据从源头不可达；知识资料默认 `internal`，必须由内部管理端显式改为 `public`，客户检索不返回内部文档。产品工具不返回精确库存、内部价格、成本、客户、报价、原始 SQL 或运营记录。客户会话目录禁止复用 `workspace/sessions`，公开记忆禁止复用 `workspace/memory/MEMORY.md`，越出工作区或身份缺失均 fail closed。第二层在模型调用前拒绝中英德提示注入及内部数据索取；第三层在持久化前检查模型输出，命中凭据、内部路径、内部记忆/技能/MCP/邮件正文或堆栈信息时整条替换成本地化拒绝。客户端口的 `/api/email/*`、知识库及管理资源继续为 404。 |
| 验证方式 | 客户定向测试 24 项通过；主项目完整测试 221 项通过、1 项跳过、40 个子测试通过；Python compileall 通过。覆盖独立路径、公开/内部记忆隔离、只读公开知识/产品工具、三语提示注入不调用模型、敏感输出和伪造工具调用不落盘、知识分类门禁及正常 RFQ 放行。此前浏览器三语身份和客户端口白名单验证继续有效。未进行真实外部模型数据传输、生产鉴权或专业红队/渗透测试。 |
| 操作者 | Codex |

## 2026-07-24（客户需求转交同级工作空间 Agent）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/peer_coordination.py`、`agent/tools/workspace_peer.py`、`agent/customer_agent.py`、`agent/context.py`、`main.py`、`agent/customer_security.py`、`test/test_customer_identity.py`、README 与项目进度 |
| 变更摘要 | 客户 Agent 对每条正常需求调用同级 `workspace_peer:<hash>` 分析会话；两者不是 MCP、Skill 或 SpawnSubagent 父子关系。工作空间 peer 只注册只读知识库/产品分析工具，可读取内部数据做判断，但不能写文件、执行命令、审批报价或发送邮件。分析结果必须是 `status/public_answer/basis` 结构化信封，客户 Agent 只接收经过门禁的公开结论。 |
| 安全边界 | 客户原文仅通过内部协作通道传递；peer 输出若不是严格 JSON、包含内部文档、精确库存、价格、成本、客户、邮件或其他敏感字段，则降级为本地化人工确认。客户侧仍不能访问 peer 会话、内部工具或内部原始结果。 |
| 验证方式 | 同级协作、结构化结果、私密结果 fail-closed、客户 Agent 注入 peer 结果且不产生子 Agent 的定向用例通过；完整主项目测试为 224 通过、1 跳过、40 子测试通过。首次完整运行出现一个既有 WebSocket 队列时序抖动，单测与再次完整运行均通过。未进行真实模型、生产鉴权或红队验收。 |
| 操作者 | Codex |

## 2026-07-24（修复 RAG 删除显示和删除后重导）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/knowledge_repository.py`、`channels/web.py`、`channels/web_ui/static/app.js`、`test/test_knowledge_admin.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 原删除已正确撤回索引并把源文件移入回收目录，但默认列表仍返回 `revoked` 审计记录，造成页面看似删除失败；同时内容哈希去重仍命中已撤回记录，导致相同资料不能重新导入。列表现默认隐藏已撤回资料，管理接口可用 `include_deleted=true` 查看审计记录；去重只阻止仍有效或删除中的内容，已撤回内容重导会创建带 `-vN` 后缀的新活动记录。前端删除成功后关闭详情、刷新列表并提示结果。 |
| 安全边界 | 保持可恢复删除，不执行不可逆物理清空；`revoke_pending` 失败项继续显示并允许重试，已撤回内容不再参与检索。未改写现有三条撤回记录或回收目录。 |
| 验证方式 | 当前真实清单只读核对为 3 条 `revoked/withdrawn`；修复后默认可见 0、`include_deleted=true` 为 3。新增删除后同内容重导用例，确认 `duplicate=false`、新记录 published、旧记录仍 revoked；知识库、Web 文件和 M5 定向测试 27 项通过，JavaScript 语法检查通过。 |
| 操作者 | Codex |

## 2026-07-24（精简 test2 分发包）

| 项目 | 内容 |
|---|---|
| 修改位置 | 删除 `test2/acceptance/`、`test2/tests/`、各包 `tests/`、邮件 `.eml` 测试 fixtures、`requirements-acceptance.txt`、`requirements-dev.txt` 及测试缓存；更新各包 README、`TEAM_USAGE_GUIDE.md`、`PROJECT_PROGRESS.md` |
| 变更摘要 | M6-M7 隔离验收已完成并留存结果后，移除仅用于测试/验收的文件，降低其他成员导入项目时的文件和依赖压力。运行时代码、示例知识、迁移 SQL、统一 `.env.example` 和 Mock/IMAP/SMTP 实现保留。 |
| 安全边界 | 未删除任何运行时业务、邮件分层、BusinessPort 或前端入口；测试删除不表示生产就绪，真实 MySQL、IMAP/SMTP、外部 LLM、Secret Store、TLS/部署仍未验收。 |
| 验证方式 | 删除前 M6-M7 结果已记录于本文件和 `test2/README.md`；删除后检查 `test2` 不再包含测试目录、验收目录或测试依赖清单，并更新使用说明为 import/compile smoke。 |
| 操作者 | Codex |

## 2026-07-24（新增 test2 团队使用与迁移说明）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/TEAM_USAGE_GUIDE.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 明确推荐保留 `test2/` 命名空间使用，并说明只有在目标项目必须使用根级包时才取出子目录；列出扁平化必须同步修改的导入、验收脚本路径、快照测试、PYTHONPATH、环境模板和 CI 文档。 |
| 安全边界 | 指南明确禁止复制 secret、真实邮件、生产数据库，禁止让 mail_service 直接导入 business 或绕过 BusinessPort；生产 MySQL、IMAP/SMTP、外部 LLM 和运维部署仍需单独验收。 |
| 验证方式 | 对照当前 `integration/business_adapter.py` 的双包名兼容分支、各包测试导入和 M6-M7 隔离验收布局编写；未改变运行时代码。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 F：M6-M7 隔离验收）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/acceptance/run_acceptance.py`、`test2/frontend/tests/test_apps.py`、`test2/tests/test_m0_contracts.py`、`test2/README.md`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 新增离线验收编排：在临时 `bundle/test2` 副本建立独立 venv，安装 `requirements-acceptance.txt`，导入并启动两个 UI-only FastAPI 入口，依次验证无邮件业务、Mock 邮件和完整本地集成；为源 UI/根 `channels` 不随包复制的场景，将仅用于主项目快照对比的测试改为明确 skip，保留包内独立断言。补充统一环境模板、四模式结果、实际命令和生产验收边界。 |
| 安全边界 | 所有 secret、MySQL 凭据、BFF 上游 URL 和 RAG API key 为空；强制 SQLite、`RAG_REMOTE_DATA_TRANSFER_APPROVED=false`，只访问 `127.0.0.1` 临时 HTTP。Mock source/SMTP 和 Fake BusinessPort 是唯一邮件路径；未实例化真实 IMAP/SMTP，未调用外部 LLM，未连接生产 MySQL。`rag_knowledge_base/.env.example` 仅指向 `../.env.example`。 |
| 验证方式 | `run_acceptance.py` 返回 `status=passed`：UI-only 200/200 + 邮件 503；无邮件业务 11 产品、`pending_approval`；Mock fixture 2、accepted 1；完整集成唯一投递 1、accepted 1。独立测试 frontend 18 passed/1 skipped、mail_service 20 passed、integration 10 passed、RAG 22 passed、M0 8 passed/1 skipped；`compileall` 通过。临时副本路径为 `E:\agent\nanoclaw\.tmp\test2-task-f-20260724\bundle\test2`。 |
| 未完成项 | 这只证明可移植的本地/离线候选，不代表生产就绪。真实 MySQL 迁移与并发/备份回退、IMAP/SMTP 账号和最终送达、Secret Store、TLS/鉴权部署、Router/常驻 Worker、外部 LLM 同意与运维监控均未验收。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 E）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/integration/`、`test2/business/public_facade.py`、`business/__init__.py`、`business/database.py`、`sqlite_database.py`、`mysql_database.py`、`seed_data.py`、`tools/calculate_quote.py`、迁移映射及项目状态文档 |
| 变更摘要 | 新增唯一同时依赖 business/mail_service 的 `BusinessPortAdapter`，把邮件审核、报价草稿、人工审批、可发送报价和哈希复核委托给 business 公开服务。原 business 没有稳定的“当前已批准版本 + 审批时内容哈希”入口，因此新增最小 `BusinessFacade` 及 additive `mail_quote_bridge`/`quote_approval_hash` 表；复用既有产品、MOQ、库存和确定性报价计算，补充同一 review 幂等建单、当前版本和哈希门禁。将 facade 涉及的包内导入改为相对导入，使 `test2.business` 与独立复制后的 `business` 两种包名均兼容。 |
| 原因 | 让 mail_service 只依赖冻结的 `BusinessPort`，禁止直接读取业务数据库；同时保证只有当前人工批准且内容未变化的报价能够进入邮件 Mock 队列。新增 facade 是因现有工具函数没有公开审批哈希查询能力，且 SQLite 旧审批表未绑定内容哈希；新增表不改已有行或原审批状态含义。 |
| 安全边界 | 未修改价格、折扣、MOQ、库存或审批规则；未修改已有业务表数据。产品不唯一、低于 MOQ、库存不足、未批准/已拒绝、旧版本及批准后内容变化全部 fail closed。测试只使用临时业务 SQLite、独立内存邮件 SQLite、`example.test` 数据和 Mock SMTP，未连接真实邮件、MySQL、外部 LLM 或生产服务。 |
| 验证方式 | 任务 E 集成测试 10 项通过；任务 E + 邮件 + M0 边界共 39 项通过；Python 编译通过。覆盖 adapter Protocol、review/建单幂等、产品歧义、MOQ、库存、未批准/拒绝、过期版本、内容哈希变化、重复入队和批准后 Mock acceptance。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 D）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/mail_service/contracts/`、`domain/`、`application/`、`persistence/`、`transport/`、`workers/`、`tests/`、`requirements*.txt`、`README.md`、迁移映射及项目状态文档 |
| 变更摘要 | 将邮件核心提取为六层独立包：迁移有界 MIME、无网络 Mock、只读 IMAP 和 SMTP_SSL 适配器；新增 `pending_confirmation` 审核门禁、精确收件人许可、投递状态机、邮件自有 SQLite schema/SQL、静态 MySQL 候选迁移、UIDVALIDITY+UID 幂等游标、审核/投递幂等、lease/retry/outcome_unknown、最小审计及一次性 Worker。业务报价只经注入的 `BusinessPort` 调用。 |
| 安全边界 | IMAP/SMTP 网络默认关闭；IMAP 只读选择并使用 `BODY.PEEK[]`；SMTP 密钥只由 resolver 注入，账户仅保存 `secret_ref`。未导入 `business`、`agent`、根 `channels`、MCP 或数据库驱动，未打开业务数据库。未修改 `test2/business`、前端共享资产或主项目原文件。fixtures 全部使用 `example.test`，Mock SMTP 不保存正文或收件人。 |
| 验证方式 | 邮件包 20 项测试及 M0 边界 9 项测试共 29 项通过；连同前端回归共 48 项通过，Python 编译通过。覆盖 MIME 大小/层级、脱敏附件、UIDVALIDITY 重置、BODY.PEEK、网络默认关闭、审核/投递幂等、pending 门禁、收件人许可、报价版本/哈希二次校验、并发 lease、有界 retry/dead-letter/outcome_unknown、假 SMTP 及 MySQL migration 静态边界。未连接真实 IMAP、SMTP、MySQL、外部 LLM 或生产服务。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 C）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/frontend/bff/`、`apps/workspace.py`、`apps/customer.py`、`tests/test_bff.py`、`requirements.txt`、`README.md`、迁移映射及项目状态文档 |
| 变更摘要 | 新增仅由服务端环境变量配置的薄 BFF：工作空间分流核心 HTTP/WS 与邮件 HTTP，客户入口仅代理公开配置及客户 WS；加入流式请求/响应大小门禁、连接/读取超时、稳定 413/502/503/504 错误、WebSocket 消息大小与关闭码映射。两个 app 改为可注入 transport/connector 的工厂，同时保留模块级 `app` 和 UI-only 回退。 |
| 安全边界 | 核心上游可按合同接收内部会话；浏览器 `Authorization` 不会进入邮件或客户上游，邮件请求还会剥离浏览器 Cookie，并只注入服务端 Bearer 凭据。代理不记录 body、token、授权码、邮件正文或地址；客户邮件、知识库和内部会话路由继续为 404。未修改 `test2/business`、`test2/mail_service` 或根 `channels/`。 |
| 验证方式 | `test2/frontend/tests` 与 M0 边界共 28 项通过；Python 编译通过。测试使用 `httpx.MockTransport` 和假 WebSocket connector，覆盖转发头、ETag、凭据替换、敏感配置 repr、超时/断连、请求/响应限额、客户越权负向路由、1013 失败关闭及非法上游关闭码映射；未连接真实邮箱、外部网络或生产服务。只有既有 Starlette/httpx 弃用警告。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 B）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/frontend/apps/`、`pages/`、`static/`、`tests/`、`server.py`、`README.md`、M0 迁移映射及项目进度文档 |
| 变更摘要 | 将 `channels/web_ui` 最新工作空间、客户门户和 13 个现有 CSS/JS 资源机械复制到可移植前端，并新增 2 个 portable-mode 提示资源；新增 workspace/customer 两个独立 FastAPI UI-only 入口、稳定后端未配置响应、独立端口、客户 API/静态资源白名单及可见 UI-only 提示；兼容入口 `frontend.server` 指向工作空间。 |
| 安全边界 | 前端不导入 `business`、`mail_service`、数据库或 MCP；客户入口不能访问邮件、知识库、内部会话或内部 `app.js`；没有连接业务后端、邮件服务或外部 LLM。Contact Us 在 UI-only 中只有环境变量/安全回退显示，活动邮箱持久化同步仍待 M2 公共后端适配。 |
| 验证方式 | M1 前端与 M0 边界共 17 项测试通过（含 Node.js 全部 JS 语法检查）；独立复制 `frontend/` 后双 app HTTP smoke 通过且无 `business` 包；应用内浏览器验证 1280×720 工作空间和客户门户、390×844 客户窄屏均无横向溢出，UI-only 提示可见、无后端时发送禁用。只有既有 Starlette/httpx 弃用警告。 |
| 操作者 | Codex |

## 2026-07-24（执行 test2 迁移任务卡 A）

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/frontend/contracts/`、`test2/mail_service/contracts/`、`test2/tests/test_m0_contracts.py`、迁移计划与进度文档 |
| 变更摘要 | 冻结当前工作空间 39 条 HTTP/WS 路由和客户门户 5 条路由，分别记录 HTTP/API 与工作空间/客户 WebSocket v2 合同；新增邮件侧唯一允许调用的 `BusinessPort` Protocol、源文件到目标包的迁移映射，以及源路由漂移、合同字段、运行时 Protocol、前端/邮件/业务反向导入边界测试。明确 `/api/email/v1/*` 尚未实现，当前兼容表面仍为 `/api/email/*`。 |
| 安全边界 | 未迁移运行实现，未修改 `test2/business`，未读取 `.env`、真实邮件、授权码或数据库数据，未连接 IMAP、SMTP、外部 LLM 或生产服务；公共合同显式排除 secret/token/credential 字段。 |
| 验证方式 | M0 独立合同测试 9 项通过；现有 WebSocket、会话、邮件 M0、Contact Us 和 Web 文件/门户定向回归 58 项通过，只有既有 Starlette/httpx 弃用警告。 |
| 操作者 | Codex |

## 2026-07-24（test2 前端与邮件团队迁移计划）

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/TEST2_FRONTEND_EMAIL_TEAM_MIGRATION_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于当前仓库盘点，提出 `frontend`、`business`、`mail_service`、`rag_knowledge_base` 平级和 `integration` 统一装配的目标结构；记录最新双端前端迁移、邮件领域抽取、BusinessPort 桥接、隔离副本验收的 M0-M7 顺序，并提供六张可直接交给团队成员 agent 的代码任务卡。 |
| 安全边界 | 本次只修改计划、进度和变更记录，没有复制或重构运行代码，没有读取或写入真实凭据、邮件正文和业务数据，没有连接 IMAP、SMTP 或外部 LLM；计划继续要求人工审核、报价批准和显式入队三道门禁。 |
| 验证方式 | 依据当前 `test2/frontend`、`channels/web_ui`、`channels/email`、`agent/business/email_*`、`channels/web.py`、配置/启动代码和邮件/Web 测试清单进行交叉核对；随后执行 Markdown 结构与 Git status 检查。 |
| 操作者 | Codex |

## 2026-07-24（移除业务工作台并合并邮箱运行概览）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web.py`、`channels/web_ui/index.html`、`channels/web_ui/static/app.js`、`channels/web_ui/static/app.css`、邮件与 Web 测试 |
| 变更摘要 | 移除主工作区“业务工作台”入口和视图，并删除独立 `/ops` 页面；将“今日运行指标”和“邮箱工作台”运行状态卡迁入邮箱页面。删除业务工作台“真实邮件记录”卡，真实投递记录继续由邮箱“投递记录”页签展示。运行指标合并到既有 `/api/email/metrics`，不再使用 `/api/ops/dashboard`。 |
| 安全边界 | 邮箱中的 RFQ 审核、报价批准/驳回、确认发送、账户健康和收件人白名单门禁保持不变；未启用真实发件，也未执行 SMTP。 |
| 验证方式 | JavaScript 语法检查及 Web、M2/M3、报价闭环、M4 定向测试 41 项通过；应用内浏览器受宿主本地端口隔离，未将视觉 E2E 标记为通过。 |
| 操作者 | Codex |

## 2026-07-24（NanoClaw RFQ 检查与业务员确认职责收敛）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_review_service.py`、`channels/web_ui/static/app.js`、`channels/web_ui/static/app.css`、`channels/web_ui/index.html`、M2/M3/报价闭环测试 |
| 变更摘要 | 服务端为每封 RFQ 输出 NanoClaw 字段检查摘要、已检查字段数和待补正字段；前端将已有证据的字段设为只读，仅对 `pending_confirmation` 字段开放业务员补正。字段完整时自动预检，业务员直接“确认审核”；确认后生成报价进入审批，批准后由业务员“确认发送”进入受控投递队列。 |
| 安全边界 | NanoClaw 不推断缺失字段；业务员确认不能绕过待补正字段、报价版本/内容哈希审批、发件账户和收件人白名单门禁。 |
| 验证方式 | M2/M3/报价闭环定向测试覆盖 NanoClaw 检查状态、字段完整自动可确认、缺失字段需补正、审批和受控投递。 |
| 操作者 | Codex |

## 2026-07-24（邮件确认入口与旧审批错误修复）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/static/app.css`、`channels/web_ui/static/app.js`、`channels/web_ui/index.html`、`agent/business/email_quote_workflow.py`、邮件前端与闭环测试 |
| 变更摘要 | 移除隐藏收件字段和确认操作区的旧样式；将确认操作移到邮件标题下方，并在字段完整时自动预检启用确认按钮；为静态资源增加版本参数避免浏览器继续使用旧 CSS/JS。旧版未绑定内容哈希的审批不再显示可点击的批准按钮，而是明确进入报价阻塞状态。 |
| 安全边界 | 不迁移或自动批准旧审批；只有绑定当前不可变报价版本与 `content_hash` 的审批才允许业务员批准。 |
| 验证方式 | 使用真实本地邮件数据在浏览器确认字段区为 `grid`、操作区为 `flex`、确认按钮可见且可用；接口回归覆盖旧审批阻断。 |
| 操作者 | Codex |

## 2026-07-24（邮件报价审批与投递闭环）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_quote_workflow.py`、`channels/web.py`、`channels/email/admin_contracts.py`、`channels/web_ui/index.html`、`channels/web_ui/static/app.js`、`test/test_email_quote_approval_flow.py` |
| 变更摘要 | 将已确认邮件与报价、审批和 Outbox 串联：系统按产品库、MOQ、库存和确定性价格规则生成不可变报价草案及待审批记录；邮箱待发送页和业务工作台同时展示字段待确认、报价阻塞、待审批状态；业务员批准后仍须再次选择健康发件账户和白名单收件人才可入队；投递状态继续在两个界面同步展示。 |
| 安全边界 | 不唯一产品、缺字段、低于 MOQ、库存不足、缺少非 EXW/FOB 运费均 fail-closed；审批绑定报价版本与内容哈希；拒绝浏览器提交任意主题、正文或金额；Agent 仍无 SMTP 工具。 |
| 验证方式 | 新增无网络闭环测试，覆盖确认邮件、自动报价、双端待审批、批准、人工入队、mock accepted 和双端投递回显，并覆盖未知产品阻断。 |
| 操作者 | Codex |

## 2026-07-24（邮箱收件可见性与 Agent 查询）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_repository.py`、`email_ingestion.py`、`managed_email_ingestion.py`、`email_review_service.py`、`agent/tools/query_email.py`、`main.py`、`channels/web.py`、`channels/web_ui/`、邮箱测试 |
| 变更摘要 | 修复启用账户卡在 `validating` 后不再轮询的问题；邮件页默认展示全部入站记录；普通非 RFQ 信息保留在本机，安全通知、自发邮件和白名单外来信仍采用 body-free 持久化；新增 NanoClaw 原生只读邮箱查询工具。 |
| 安全边界 | IMAP 继续使用只读 `BODY.PEEK[]`；Agent 工具只返回脱敏列表和本地结构化 RFQ 结果，不返回原始正文，不注册 SMTP/发信能力。 |
| 验证方式 | 196 个根测试通过、1 个环境测试跳过、40 个子测试通过；真实只读 IMAP 单轮同步成功，账户恢复为 `healthy`，拉取 5 条未同步邮件且 0 条解析失败。 |
| 操作者 | Codex |

## 2026-07-24（客户门户对话头像）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/static/customer-preview.js`、`channels/web_ui/static/css/customer.css`、`test/test_customer_portal_contact.py`、项目状态文档 |
| 变更摘要 | 将容易退化为普通文字的 `N`、`客/You` 标识替换为本地内联 SVG 图形头像：NanoClaw 使用品牌机器人/爪形图标，客户使用人物轮廓；消息行改为明确的双列 Grid，客户 DOM 顺序固定为“气泡、右侧头像”，不再依赖 `order` 调序，并统一头像与气泡顶部基线。 |
| 验证方式 | JavaScript 语法检查、客户门户定向测试及本机 Chromium 桌面/窄屏截图和元素边界测量；应用内浏览器受宿主端口隔离，不将其标为在线 E2E。 |
| 操作者 | Codex |

## 2026-07-24（Agent Markdown 回复可读化）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/static/js/markdown.js`、`channels/web_ui/static/css/markdown.css`、`channels/web_ui/index.html`、`customer.html`、两端消息脚本及定向测试 |
| 变更摘要 | 新增仓库内共享 Markdown 渲染器，工作空间和客户门户的 Agent 回复统一渲染标题、粗体、斜体、删除线、列表、引用、行内代码、代码块、表格和链接；用户消息继续按纯文本显示。 |
| 安全边界 | 渲染器先转义原始 HTML；链接只允许 HTTP、HTTPS、mailto、站内绝对路径和锚点，其他协议降级为 `#`；不依赖公网 CDN，不执行回复中的脚本或 HTML。 |
| 验证方式 | Node 语法检查与包含标题、列表、表格、代码块、HTML 转义和危险链接降级的渲染样例通过；Web 定向测试覆盖资源加载顺序和两端渲染入口。 |
| 操作者 | Codex |

## 2026-07-23（客户对话、流程窗与业务工作台运行修复）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/customer_portal.py`、`channels/web.py`、`channels/web_ui/`、`test/test_web_file_import.py`、`test/test_email_admin_m2.py`、项目状态文档 |
| 变更摘要 | 客户门户从静态预览接入独立 WebSocket/消息总线并显示客户询盘流程；工作空间流程窗拆分坐标和指针状态，支持整窗自由拖动、边界约束、复位和停靠；业务工作台加载真实邮件审批/投递聚合；邮箱移除管理令牌输入，并隐藏 RFQ 人工字段编辑区。 |
| 安全边界 | 客户使用签名 HttpOnly 匿名会话，回复按当前 conversation ID 隔离；本机回环地址可免令牌访问邮箱，非本机仍要求服务端 Bearer 且校验 Origin；RFQ 字段由 Agent 自动审核，但报价审批、投递入队和真实邮件发送仍必须走原有人工门禁。 |
| 验证方式 | JavaScript 语法、Python 编译、61 项定向测试通过；客户 WebSocket 入站实测通过；本机无令牌 `/api/ops/dashboard` 返回 200。宿主 `8765/8766` HTTP 返回 200；内置浏览器与宿主端口隔离，未将视觉拖拽标为 E2E 通过。 |
| 操作者 | Codex |

## 2026-07-23 16:05:41 +08:00（邮件改进 M3：Web 收件审核设计）

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/EMAIL_M3_WEB_REVIEW_DESIGN.md`、`docs/project/邮件改进.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于现有邮件入库、RFQ v2、CLI 审核和 M0-M2 能力，完成 M3 Web 收件审核详细设计：摘要/详情/预检/确认 API、不可变 review revision、可信审核人、人工确认来源、精确 evidence、乐观锁、幂等、最小化审计、失效规则、报价门禁、桌面/移动交互、错误码、测试矩阵和 M3.0-M3.5 实施顺序。 |
| 原因 | 现有 `list_reviews()/confirm()` 缺少分页安全响应、RFQ v2 人工审核重校验、版本冲突和幂等，不能直接开放给浏览器。 |
| 安全边界 | 本次只修改设计与状态文档；未实现或调用审核 API，未修改 SQLite/MySQL，未确认邮件、创建询盘/报价、发送邮件或处理真实数据。设计明确正文纯文本渲染、草稿不进 storage、浏览器不得自报 reviewer、pending 服务端门禁和 Agent/LLM 无确认权限。 |
| 验证方式 | 交叉核对 `email_repository.py`、`rfq_extractor.py`、`channels/web.py`、M2 邮箱页签和现有邮件测试；检查设计的 Mermaid、API JSON、事务顺序、错误码、实施状态和 M3/M4/M6 边界。 |
| 待确认项 | reviewer ID 形式、operator input 允许范围/reason code、item 增删、正文保留责任和报价页面跳转范围。 |
| 操作者 | Codex |

## 2026-07-23 15:48:33 +08:00（邮件改进 M1：账户与 DPAPI 密钥存储）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_account_repository.py`、`agent/business/email_account_service.py`、`agent/business/email_secret_store.py`、`agent/business/migrations/003_email_accounts.mysql.sql`、`channels/email/imap_source.py`、`channels/email/admin_contracts.py`、`channels/web.py`、`channels/web_ui/`、`.gitignore`、`test/test_email_admin_m*.py`、邮件与项目文档 |
| 变更摘要 | 实现 QQ、网易 163、网易 126 多账户 SQLite Repository 和安全响应；新增 Windows 当前用户作用域 DPAPI Secret Store、字段级审计、乐观锁配置更新、授权码轮换、启停、健康状态、IMAP 只读连接测试及可选 SMTP 认证测试；提供显式且幂等的 legacy 环境变量迁移命令，并让工作空间调用真实 M1 API。 |
| 原因 | 完成邮件改进方案 M1，使 M2 配置窗口具备真实账户管理能力，同时不提前实施 M3 审核或 M4 发件。 |
| 安全边界 | SQLite 和审计只保存 `secret_ref` 与变更字段名；授权码仅在 API 请求内存、DPAPI 和连接适配器之间流动。DPAPI 不可用时 fail-closed，不降级明文。连接测试只执行 TLS、认证、`EXAMINE INBOX` 和可选 SMTP 登录，不发送邮件；legacy 迁移必须由管理员显式执行。 |
| 验证方式 | M1 专项 11 项通过，包含真实 Windows DPAPI 往返与文件零明文；主项目全量测试 153 项、40 个子测试通过；JavaScript 语法和相关 Python 编译检查通过。 |
| 未完成项 | 未使用真实 QQ/163/126 授权码联调；MySQL 仅增加目标 DDL，M6 运行时 Repository 尚未实现；M3 Web 审核和 M4 SMTP Outbox 未实施。 |
| 操作者 | Codex |

## 2026-07-23 15:20:00 +08:00（邮件改进 M2：工作空间邮箱窗口）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/index.html`、`channels/web_ui/static/app.js`、`channels/web_ui/static/app.css`、`test/test_email_admin_m2.py`、`docs/project/邮件改进.md`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 在内部工作空间增加“邮箱”导航和独立视图；提供 QQ、网易 163、网易 126 Provider 表单、账户列表与健康状态、连接测试入口，以及账户配置、收件审核、待发送、投递记录四个页签；补齐中英德文案和 900px/680px 响应式布局。 |
| 原因 | 落实邮件改进方案 M2，同时保持 M1/M3/M4 尚未实现时的真实能力边界。 |
| 安全边界 | 管理令牌仅保存在页面运行内存；授权码输入禁用自动填充，仅随新增/轮换请求使用，请求结束或页面隐藏时清空；不写入 localStorage、sessionStorage、URL 或回显。后端 501 明确显示为未实施，不伪造保存、连接、审核或发送成功。 |
| 验证方式 | M0/M2 定向测试 27 项通过；主项目全量测试 142 项、40 个子测试通过；`node --check channels/web_ui/static/app.js` 通过；临时本地服务 `/api/email/providers` 返回 200。内置浏览器受宿主端口隔离且 Chrome 控制未连接，因此未把桌面/窄屏视觉 E2E 标为通过。 |
| 操作者 | Codex |

## 2026-07-23 14:36:50 +08:00（邮件改进 M0：契约与内部鉴权）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/email/admin_contracts.py`、`channels/web.py`、`config.py`、`.env.example`、`test/test_email_admin_m0.py`、`test/test_privacy.py`、邮件与项目文档 |
| 变更摘要 | 固定 `email-admin.v1` provider/account/route/error 契约；公开无敏感信息的 QQ/网易 provider preset；为其余邮件管理端点增加环境变量 Bearer 管理令牌、常量时间比较、浏览器同源/allowlist 校验和 fail-closed 占位响应。 |
| 原因 | M1-M4 开发前先固定边界，并确保尚未实现的账户、审核和发送端点既不能匿名访问，也不会被误认为已经可用。 |
| 安全边界 | 管理令牌只接受环境变量；空令牌返回 503，缺失/错误令牌返回 401，跨源返回 403，鉴权通过的未实现能力返回 501；M0 不解析、不保存、不回显邮箱授权码，也不连接 IMAP/SMTP。 |
| 验证方式 | `python -m pytest -q`：137 项通过、40 个子测试通过；新增邮箱管理契约、全路由未授权、Origin、空配置和密钥零回显测试。 |
| 操作者 | Codex |

## 2026-07-23 14:26:50 +08:00（邮件配置与受控外发改进方案）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/project/邮件改进.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于当前邮件模块提出 QQ、网易 163/126 多账户支持方案；设计工作空间邮箱窗口、密钥引用、Web 审核、审批绑定的 SMTP Outbox、状态机、API、数据流、测试矩阵与 M0-M6 路线。 |
| 原因 | 参考文档来自另一份源码，所述单文件 EmailChannel、发送数据层和工作台 API 不等同于当前仓库实现；需要保留现有只读收件及保守 RFQ 边界并补齐人工受控外发。 |
| 当前边界 | 本次仅修改文档；未新增邮箱配置 API、前端窗口、密钥存储、Web 审核、SMTP Sender 或真实邮件发送。网易 163 只读收件联调不能作为 QQ/126 或 SMTP 外发验收。 |
| 验证方式 | 静态核对 `channels/email/`、`agent/business/email_*.py`、`channels/web.py`、`channels/web_ui/`、邮件迁移、测试与现有邮件设计/运维文档；复核 Mermaid、表格、路径和已实现/未实现边界。 |
| 操作者 | Codex |

## 2026-07-23（业务流程拖拽与客户门户改造计划）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/architecture/WORKFLOW_WINDOW_CUSTOMER_PORTAL_UI_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于当前代码制定业务流程窗口自由拖拽、浅蓝色工作空间式客户门户、客户新建/删除/切换对话及中英德语言设置的 M0-M6 实施计划。 |
| 安全边界 | 本次只输出计划，未修改运行代码；计划禁止客户门户直接复用内部 `owner_id=local` 会话 API，并要求服务端客户身份、软删除、跨客户权限负向测试和客户/内部浏览器状态隔离。 |
| 验证方式 | 对照 `channels/web_ui/`、`channels/customer_portal.py`、`channels/web.py`、`session/conversation.py` 及现有会话/前端测试逐项核对现状与差距。 |
| 操作者 | Codex |

## 2026-07-23（工作空间业务台与独立客户门户端口）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web_ui/index.html`、`channels/web_ui/static/app.css`、`channels/web_ui/static/app.js`、`channels/customer_portal.py`、`channels/web.py`、`config.py`、`config.json`、`main.py`、`.env.example`、测试及前端交付文档 |
| 变更摘要 | 业务工作台改为当前工作空间内的 `opsView`，不再跳转 `/ops`；工作空间客户门户入口改为独立端口 URL；新增默认监听 `127.0.0.1:8766` 的客户门户服务、健康检查、配置发现和公开 URL 覆盖。 |
| 安全边界 | 客户门户服务不提供 `/ops`；当前仍为视觉预览，客户 WebSocket/BFF、业务审批、报价、认证和邮件发送未实现，不会自动批准或发送。 |
| 验证方式 | 定向测试 11 passed；全量测试 112 passed、40 subtests passed；JavaScript 语法和 Python 编译通过；浏览器确认业务台原地切换及独立客户门户可打开。 |
| 操作者 | Codex |

## 2026-07-23（项目更新计划 M0）

| 项目 | 内容 |
|---|---|
| 修改位置 | `pyproject.toml`、`README.md`、`test/test_mcp.py`、`test/test_privacy.py`、`channels/web_protocol.py`、`channels/web.py`、`channels/web_ui/static/app.js`、`session/snapshot.py` 及 M0 测试 |
| 变更摘要 | 根目录 pytest 只收集主项目；异步 MCP 测试真实执行；隐私测试隔离进程凭证与项目 `.env`；服务端回复冻结为含 `type`/`protocol_version` 的 WebSocket v2 信封，前端兼容旧纯文本；新增强制 `--dry-run` 的匿名会话快照。 |
| 安全边界 | 未输出凭证值；快照不输出会话文件名、路径或正文；未改写、移动或删除现有 JSONL；M1-M5 未实施。 |
| 验证方式 | 主项目 75 passed、40 subtests passed；隔离 RAG 22 passed；新增定向测试 11 passed；快照 3 个文件/33 条记录合法；JavaScript 语法和 Python 编译通过。 |
| 操作者 | Codex |

## 2026-07-23（项目更新计划 M1）

| 项目 | 内容 |
|---|---|
| 修改位置 | `session/conversation.py`、`session/conversation_migrate.py`、`session/manager.py`、`bus/queue.py`、`channels/web.py`、`gateway.py`、`channels/web_ui/`、`test/test_conversations.py`、README 与项目状态文档 |
| 变更摘要 | 新增本地单用户 ConversationService、原子元数据索引和旧 Web JSONL 幂等迁移；提供清单/搜索/分页/详情/消息白名单/重命名/软删除/恢复 API；WebSocket v2 先绑定稳定 conversation ID，再发送带 request ID 的消息；Gateway 会话键与连接路由解耦；前端改为真实多对话清单并隔离消息与附件。 |
| 安全边界 | `owner_id=local` 仅代表当前本地单用户边界，不宣称多租户；消息 API 不返回工具消息；伪造 ID 返回稳定错误；QQ 会话不进入 Web 清单；删除只写 `deleted_at`，不擦除正文；迟到的旧对话回复不会渲染到当前对话。 |
| 数据迁移 | 已为 2 个可识别的旧 Web JSONL 建立索引，未改写正文；1 个 QQ JSONL 未索引。迁移命令支持 `--dry-run`/`--apply`，重复执行不新增记录。 |
| 验证方式 | 主项目 81 passed、40 subtests passed；隔离 RAG 22 passed；JavaScript 语法与 Python 编译通过。真实浏览器视觉/E2E、登录后的 owner 鉴权和跨进程幂等仍待后续验收。 |
| 操作者 | Codex |

## 2026-07-23（项目更新计划 M3）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/workflow.py`、`agent/loop.py`、`main.py`、`channels/web.py`、`channels/web_ui/`、`test/test_workflow.py` 及项目状态文档 |
| 变更摘要 | 新增原子 WorkflowRun 索引与 append-only 事件日志；七个外贸工具节点由 AgentLoop 统一插桩；增加运行清单、按 sequence 补拉、取消 API，以及 WebSocket 快照/实时事件；前端增加可缩小、左右停靠、多 run 切换的流程窗口。 |
| 安全边界 | 业务状态仍以 SQLite/MySQL 和现有工具结果为准；事件不驱动金额、库存、审批或外发，仅提供观察；只记录内部 ID、缺失字段数量和稳定错误码，不记录客户正文、工具参数、完整结果或内部堆栈；真实外发权限未扩大。 |
| 验证方式 | 完整七节点顺序、待确认、失败、取消、重启恢复、`after_sequence` 补拉、对话隔离广播和隐私字段测试通过；主项目 87 passed、40 subtests passed，隔离 RAG 22 passed，JavaScript 语法和 Python 编译通过。 |
| 当前边界 | 当前覆盖主 Agent/MCP 工具调用；邮件 Worker 或直接 Repository 调用尚未插桩。真实浏览器视觉/E2E、真实模型端到端和生产多进程事件总线待 M5。 |
| 操作者 | Codex |

## 2026-07-23（项目更新计划 M4 固定查询 MVP）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/analytics.py`、`agent/tools/query_trade_data.py`、`mcp_servers/foreign_trade_inquiry_server.py`、`agent/workflow.py`、`agent/loop.py`、`channels/web_ui/static/app.js`、`test/test_trade_analytics.py`、MCP 契约测试及状态文档 |
| 变更摘要 | 增加四个固定运营分析查询与 MCP 入口；SQLite/MySQL 分别使用固定参数化模板；增加 query/filter allowlist、50 行和 64 KiB 结果上限、SQL 哈希与匿名审计；分析运行以独立 `trade_data_analysis` 流程展示。 |
| 安全边界 | 不接受 SQL 文本，不调用 LLM 生成 SQL；未知查询码/过滤器、超限和任意 SQL fail closed；审计不保存筛选值或结果行；数据源标记为 `trade_ops_demo` 并明确不是 `trade_dw`；查询不能修改报价、审批、库存或外发状态。 |
| 验证方式 | 库存 Top-N、询盘/报价状态和待跟进汇总金样本通过；SQL 注入作为普通参数处理，任意 SQL/未知字段/超限阻断；分析事件顺序与隐私测试通过；主项目 95 passed、40 subtests passed，隔离 RAG 22 passed。 |
| 未完成项 | `trade_dw`/`trade_metadata`、元数据/值召回、正式指标配置、AST/EXPLAIN、只读数仓账号和生产授权未落地，因此受限 NL2SQL 仍为 0%。 |
| 操作者 | Codex |

## 2026-07-23（项目更新计划 M2）

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/knowledge_repository.py`、`trade_rag/stores.py`、`trade_rag/pipeline.py`、`trade_rag/server.py`、`channels/web.py`、`channels/web_ui/`、`test/test_knowledge_admin.py` 及状态文档 |
| 变更摘要 | manifest 升级为 v2，导入时复用同一次规范化与 ParentChildSplitter 结果生成父/子计数；v1 惰性补算；增加文档清单、汇总、详情、撤回、重试 API 与三语知识库页面；双内存 Store 支持按文档版本删除。 |
| 删除状态机 | manifest 先写 `revoke_pending` 使文档立即不可搜索，再删除语义/关键词索引，成功后源文件移入受控 trash 并写 `revoked/withdrawn`；失败保持不可搜索和稳定错误码，可重试。MCP 每次查询前 reconcile，重启后也只加载 published/ready 文档。 |
| 安全边界 | API 不返回绝对路径或 stored_name，详情默认不返回全文；损坏/缺失 v1 文档显示 failed，不伪造成 0；没有物理清理源文件；生产 pgvector/Milvus 尚未适配或验证。 |
| 验证方式 | 真实 splitter 计数、内容哈希去重、v1 升级、损坏源、双 Store 删除、删除失败重试、回收目录、MCP 当前进程 reconcile 和重启不召回测试通过；主项目 102 passed、40 subtests passed，隔离 RAG 22 passed。 |
| 操作者 | Codex |

## 2026-07-22（前端文件导入）

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web.py`、`channels/web_ui/`、`gateway.py`、`trade_rag/knowledge_repository.py`、`trade_rag/server.py`、`.gitignore`、`test/test_web_file_import.py`、项目进度文档 |
| 变更摘要 | 在聊天输入区新增“导入”按钮并展开“读取文件”和“导入知识库”两个菜单；读取文件只随当前对话发送，新建对话同步清理浏览器文件和服务端历史；知识库导入持久保存、按内容哈希去重，RAG MCP 查询前自动增量索引。 |
| 安全边界 | 仅支持 UTF-8 TXT/Markdown/HTML/JSON/CSV；限制单文件和当前上下文大小；清理客户端路径与 HTML 脚本；知识库运行目录加入 `.gitignore`；文件内容按不可信参考数据发送，不授予工具权限。 |
| 验证方式 | Web HTTP/DOM、文件解析、知识库持久化/去重/检索、新对话清理及 RAG 回归测试通过；JavaScript 语法和 Python 编译通过。除既有环境性测试外共 63 项通过、40 个邮件金数据子用例通过。释放端口后在真实 `127.0.0.1:8765` 服务复验：页面/样式 200、两个菜单存在、当前对话读取成功、知识库首次导入成功/重复导入命中去重、RAG 返回 `ANSWERED` 和 1 条引用；验收数据随后清理。Codex 内置浏览器与宿主机本地网络隔离，仍未将此记录为视觉验收。 |
| 操作者 | Codex |

## 2026-07-22（M2B）

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/rfq_extractor.py`、`email_ingestion.py`、`email_repository.py`、`migrations/002_email_ingestion.mysql.sql`、邮件专项测试及项目文档 |
| 变更摘要 | 完成 M2B：默认完整/紧凑模型均失败后执行保守的本地确定性抽取；统一经过证据校验和缺失字段重算；持久化 `extraction_mode`/`extractor_version`；已发送 QQ 摘要被纠正时新增通知版本，不覆盖旧记录。 |
| 安全边界 | 确定性结果只进入 `needs_review`，没有新增报价、审批或邮件外发路径；国家不按域名推断，范围数量、MOQ、冲突日期/条款、转发链数量保持待确认。 |
| 验证方式 | 40 封脱敏 `.eml` 的项目行数、精确证据回指、预期待确认字段和 `missing_fields` 一致性回归通过；完整成功、紧凑成功、双失败降级、全待确认、通知纠正版均由本地测试覆盖。生产 MySQL 和真实外部发送未执行。 |
| 操作者 | Codex |

## 2026-07-22 21:40:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/EMAIL_RFQ_INGESTION_DESIGN_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 写入网易 163 真实收信、SQLite 入库、模型抽取、QQ Outbox/C2C 通知的联调结论；新增完整提示、紧凑提示、本地确定性降级三级策略，以及七类字段规则、证据门禁、缺失字段重算、抽取/通知版本化和验收指标。 |
| 当前边界 | 本次仅修改文档；`deterministic_fallback` 抽取器尚未实现，生产 MySQL Repository、Web 审核、生产加密/保留和纠正通知版本化仍待完成。未修改数据库、模型配置、邮箱状态或 QQ 外部状态。 |
| 验证方式 | 静态复核当前模型为 `deepseek-ai/DeepSeek-V4-Flash`；重新运行邮件专项测试 25 项全部通过。该测试结果不代表真实邮件字段抽取质量已通过验收。 |
| 操作者 | Codex |

## 2026-07-22 21:20:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/rfq_extractor.py`、`email_ingestion.py`、`email_repository.py`、`email_notification.py`、邮件测试 |
| 变更摘要 | 支持 Markdown 围栏 JSON、完整 RFQ v2 模板、未知状态保守降级、模型超时/中断恢复、显式重开失败任务、紧凑提示回退和解析失败 QQ 告警 Outbox。 |
| 验证方式 | 新模型 `deepseek-ai/DeepSeek-V4-Flash` 对脱敏样本约 14.7 秒通过；真实邮件主/紧凑请求均超时，邮件保持 retry_wait，并成功创建不含正文的 pending QQ 告警；22 项本地测试通过。 |
| 操作者 | Codex |

## 2026-07-22 20:40:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/email/imap_source.py`、邮件测试与运行手册 |
| 变更摘要 | 网易 163/126 登录后发送固定、无凭证的 IMAP `ID` 客户端标识，满足网易客户端识别要求并解除 `EXAMINE Unsafe Login`。 |
| 验证方式 | 16 项邮件测试通过；真实网易 163 只读连接完成 ID 握手，`EXAMINE INBOX` 从 NO 变为 OK，服务器报告 4 封邮件；未下载正文。 |
| 操作者 | Codex |

## 2026-07-22 20:20:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/email/imap_source.py`、`main.py`、邮件测试与运行手册 |
| 变更摘要 | 将笼统的 EmailWorker `RuntimeError` 细化为稳定安全错误码；网易风控响应现记录为 `imap_select_unsafe_login`。 |
| 诊断证据 | 网易 TLS/授权码登录成功，但只读 `EXAMINE INBOX` 返回 `NO Unsafe Login`；当前游标 `(0,0)`、邮件 0、QQ Outbox 0，未读取或入库邮件。 |
| 验证方式 | 邮件专项 15 项测试通过；编译通过；未信任或调用服务器错误文本中的联系方式。 |
| 操作者 | Codex |

## 2026-07-22 20:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_notification.py`、`email_repository.py`、`email_ingestion.py`、`email_config.py`、`channels/qq.py`、`main.py`、邮件迁移/测试/文档 |
| 变更摘要 | 邮件解析入库后原子创建脱敏 QQ 通知 Outbox；主程序启动 IMAP 轮询并直接等待 QQ API 投递结果，成功标记 sent，失败退避重试；支持明确 c2c/group 目标。 |
| 安全边界 | QQ 仅发送内部 ID 和必要业务摘要，不含完整邮箱、原文或附件；通知不触发报价审批或邮件回复。 |
| 验证方式 | Outbox 单例幂等、隐私摘要、成功投递状态和失败重试均加入自动测试。真实 QQ 目标未提供，本轮未发送外部消息。 |
| 操作者 | Codex |

## 2026-07-22 19:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/config.py`、`agent/business/rfq_extractor.py`、`agent/business/business_config.json`、环境变量示例、黄金集评测和 `test2/business/` 副本 |
| 变更摘要 | 删除独立 `BUSINESS_LLM_API_KEY`，RFQ 抽取与 NanoClaw 主 Agent 统一读取 `NANOCLAW_API_KEY`；业务抽取仍可使用独立的模型名和 Base URL。 |
| 安全边界 | 仍只从进程环境或本地 `.env` 读取密钥；JSON 配置和示例不保存真实密钥。 |
| 验证方式 | 全仓旧变量/旧字段零残留；统一密钥配置测试、邮件黄金集和编译检查通过。 |
| 操作者 | Codex |

## 2026-07-22 18:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `test/email_ingestion/generate_gold_corpus.py`、`test/email_ingestion/evaluate_gold.py`、`test/email_ingestion/test_gold_corpus.py`、`test/email_ingestion/golden/`、邮件计划与进度文档 |
| 变更摘要 | 生成 40 封脱敏 RFQ 黄金邮件、预期清单和可重复评测器，覆盖 MIME、安全、证据回指和幂等；执行网易 163 只读连接诊断。 |
| 验证方式 | 40/40 MIME 成功、证据回指率 100%、40 个唯一 Message-ID、重复入库新增 0，邮件专项 12 项测试通过。网易 TLS/登录/LIST 成功，但 `EXAMINE INBOX` 返回 `Unsafe Login`；未读取正文。 |
| 未完成项 | 当时尚未统一模型密钥，未运行真实模型准确率评测；网易安全限制需在邮箱侧解除。后续密钥统一见 19:00 记录。 |
| 操作者 | Codex |

## 2026-07-22 18:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/email_config.py`、`test/email_ingestion/test_email_ingestion.py`、`doc/EMAIL_RFQ_OPERATIONS.md` |
| 变更摘要 | 邮件 Worker 可直接读取仓库根目录 `.env`；进程环境保持更高优先级；补充网易 163/126 可填写示例和配置加载测试。 |
| 安全边界 | 未创建、读取或覆盖真实 `.env` 内容；`.env` 已由 `.gitignore` 排除，`.env.example` 保持空凭证。 |
| 验证方式 | 邮件专项 11 项测试通过，编译通过，`git check-ignore -v .env` 确认本地凭证文件被忽略。 |
| 操作者 | Codex |

## 2026-07-22 17:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/email/`、`agent/business/email_*.py`、`agent/business/rfq_extractor.py`、`agent/tools/extract_rfq.py`、`agent/business/migrations/002_email_ingestion.mysql.sql`、`test/email_ingestion/`、`.env.example`、`docs/reference/schema/rfq_v2.schema.json`、`doc/EMAIL_RFQ_OPERATIONS.md`、邮件计划与进度文档 |
| 变更摘要 | 实现只读 Mock/QQ/网易 IMAP 接入、受限 MIME 解析、RFQ v2 纯抽取与证据校验、SQLite 幂等/游标/租约/重试/审核审计、MySQL 迁移、CLI 审核和运行手册；旧聊天抽取工具复用新核心。 |
| 安全边界 | 不含 SMTP/自动回复；附件不送 LLM；未确认字段无法确认；真实凭证仅允许进程环境注入；生产正文/联系人加密与对象存储仍需管理员落地。 |
| 验证方式 | 标准库 `unittest` 9 项邮件测试通过，Python 编译通过；未连接真实邮箱/MySQL/LLM。全仓已有隐私测试受当前 `.env` 自动加载的既有 API Key 影响仍有 1 项失败。 |
| 操作者 | Codex |

## 2026-07-22 14:46:43 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/EMAIL_RFQ_INGESTION_DESIGN_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 将真实邮箱接入目标从通用 Provider 选择收敛为 QQ/网易共用 IMAP Source；补充 QQ、网易 163/126 主机预设、993 SSL、授权码、UIDVALIDITY+UID 幂等、UID 增量轮询、只读命令边界、标准库实现和配置项。 |
| 原因 | QQ 与网易均支持标准 IMAP，没有必要维护两套接入代码；IMAP UID 的稳定范围和用户“已读”状态需要在设计阶段明确，否则容易重复处理或漏收邮件。 |
| 验证方式 | 对照 Python 3.11 标准库能力、当前异步 Gateway、现有环境变量加载方式和邮件设计文档静态复核；未连接真实邮箱、未使用授权码、未启用 SMTP、未安装依赖。平台开关名称仍需在实际邮箱设置页确认。 |
| 操作者 | Codex |

## 2026-07-22 14:38:27 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/EMAIL_RFQ_INGESTION_DESIGN_PLAN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 新增 NanoClaw 邮件询盘接入设计：基于只读 `EmailSource`、统一邮件信封、MIME/HTML 安全规范化、RFQ v2 多产品与规格抽取、字段证据和待确认状态、数据库幂等/游标/重试、人工审核及 M0-M7 实施路线。 |
| 原因 | 当前项目已有聊天渠道和 RFQ 抽取工具，但尚无邮箱入口；现有 Gateway 会丢失邮件元数据，现有抽取契约缺独立规格、多行项目和证据状态，不能直接形成安全可靠的邮件处理闭环。 |
| 验证方式 | 对照 `main.py`、`bus/queue.py`、`gateway.py`、`agent/tools/extract_rfq.py`、`agent/models/schemas.py`、`agent/business/`、`pyproject.toml` 和 `uv.lock` 静态核对；检查 Mermaid、表格、状态和“设计未实施”边界。本次未连接邮箱、未创建凭证、未安装依赖、未运行外部服务。 |
| 操作者 | Codex |

## 2026-07-22 14:28:15 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `agent/business/`、`agent/models/`、`agent/tools/`、`mcp_servers/foreign_trade_inquiry_server.py`、`test/test_business_migration.py`、`test/test_manager_mcp_discovery.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 将 `test2/business` 的运行代码按本项目现有分层迁入：配置与 Repository 放入 `agent/business`，复用已有 `agent/models` 与七个 `agent/tools`，并将外贸 MCP Server 的全部导入切换为 `agent.*`；迁移 SQLite/MySQL 后端、种子数据、配置和 MySQL DDL。 |
| 原因 | 消除当前 MCP 服务引用不存在的顶层 `business` 包导致的启动失败，使聊天链路能够发现并调用本地业务工具。 |
| 验证方式 | Python compileall 通过；外贸 MCP stdio 握手可发现 7 个工具；临时 SQLite 中完成建表、11 个产品种子、产品搜索、库存检查与确定性报价回归测试。全量基础测试仅既有隐私测试因运行环境已注入 API Key 而失败。 |
| 操作者 | Codex |

## 2026-07-22 13:20:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `channels/web.py`、`channels/web_ui/index.html`、`channels/web_ui/static/app.css`、`channels/web_ui/static/app.js`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `docs/guides/前端界面.md` 完成 Cherry Studio 风格 NanoClaw Web 工作区：左侧对话/汇率双标签、中文/英文/德语实时切换、明暗主题持久化、WebSocket 对话、ExchangeRate-API 汇率换算、响应式断点、交互动画与连接/错误状态。 |
| 验证方式 | `node --check channels/web_ui/static/app.js`；`.venv\\Scripts\\python.exe -m compileall -q channels`；FastAPI TestClient 验证 `/`、`/static/app.css`、`/static/app.js` 均返回 200。 |
| 操作者 | Codex |

## 2026-07-22 14:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/business/web_app.py`、`test2/business/web_ui/`、`test2/requirements-business.txt`、`test2/.env.example`、`test2/README.md` |
| 变更摘要 | 将前端迁移到独立业务包：增加 FastAPI 静态页面服务、健康检查和服务端 WebSocket 代理；聊天默认安全提示，配置 `BUSINESS_AGENT_WS_URL` 后可接入 NanoClaw WebChannel；保留汇率、三语和主题能力。 |
| 原因 | 让 `test2/business` 可独立启动前端，同时不让浏览器直接访问业务数据库、MCP 工具或任何密钥。 |
| 验证方式 | `node --check business/web_ui/static/app.js`；`python -m compileall -q business`；FastAPI TestClient 验证页面、静态资源、`/health` 和未配置 Agent 的 `/ws` 提示均通过。 |
| 操作者 | Codex |

## 2026-07-22 14:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/frontend/`、`test2/business/`、`test2/requirements-business.txt`、`test2/README.md` |
| 变更摘要 | 按团队迁移需求将 Web 前端从 `business` 包内移至平级的 `test2/frontend/`；前后端分别维护依赖和 README，不互相 import，通过可选的服务端 Agent WebSocket 地址组合。 |
| 原因 | 支持项目组成员按 `frontend/ + business/` 的稳定目录结构整体复制，也支持两者独立迁移、安装和启动。 |
| 验证方式 | 从 `test2/` 导入 `frontend.server`，验证页面、静态资源、健康检查和未配置 Agent 的 WebSocket 提示；检查 `frontend` 不导入 `business`。 |
| 操作者 | Codex |

## 2026-07-22 15:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `test2/rag_knowledge_base/`、`test2/business/`、`test2/README.md`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 将独立 RAG 知识库从 `test2/business/rag_knowledge_base/` 提升到平级的 `test2/rag_knowledge_base/`；补齐固定运行依赖、空环境模板、平级/嵌入式迁移布局及 MCP 注册说明，删除旧位置。 |
| 原因 | 让项目组成员能够整体复制独立 RAG 包，并可选择与自己的 `business/` 平级或原样嵌入其中，而不修改内部导入和知识路径。 |
| 验证方式 | 在新目录运行 22 项单元测试、quickstart、Python 编译检查；扫描确认运行代码不导入 `business` 或 `frontend`，旧路径不存在。 |
| 操作者 | Codex |

## 2026-07-22 12:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | usiness/rag_knowledge_base/、docs/project/PROJECT_PROGRESS.md |
| 变更摘要 | 生成独立可迁移 RAG 副本，包含自身包、依赖元数据、知识 manifest、脱敏样例、MCP 入口、测试与迁移说明。 |
| 验证方式 | 副本目录 22 项测试通过、编译检查通过、脱敏样例查询成功。 |
| 操作者 | Codex |

## 2026-07-22 10:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/hybrid.py`、`trade_rag/stores.py`、`trade_rag/pipeline.py`、`test/trade_rag/test_hybrid.py`、`test/trade_rag/test_pipeline.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `HYBRID_RETRIEVAL_DESIGN.md` 增加可替换关键词 Store、内存 BM25 近似检索、语义/关键词双路加权 RRF、稳定 Child ID 去重、单路失败降级、检索模式及来源标记；多查询继续执行第二层 RRF，融合后只精排一次。 |
| 原因 | 让当前仅向量召回的框架具备与未来 Milvus + Elasticsearch 适配器一致的混合检索契约。 |
| 验证方式 | `.venv` 运行 19 项 `trade_rag` 单元测试全部通过，Python 编译检查通过。 |
| 操作者 | Codex |

## 2026-07-21 15:40:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `doc/DATA_WAREHOUSE_DESIGN.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 明确当前 SQLite 仅用于本地开发和功能测试，生产业务权威库使用 Docker MySQL 8 `trade_ops`；补充环境开关、优先级、迁移边界、架构图、分阶段验收和当前真实状态。 |
| 原因 | 避免把 SQLite 测试结果误认为生产数据库能力，同时说明后续 Docker MySQL 的无代码切换方式。 |
| 验证方式 | 扫描文档中 SQLite/MySQL/当前状态表述；确认 Mermaid 和代码围栏成对，`trade_dw` 与 `trade_metadata` 仍保持 MySQL 权威设计。 |
| 操作者 | Codex |

## 2026-07-21 16:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/chunking.py`、`test/trade_rag/test_chunking.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `TEXT_SPLITTER_DESIGN.md` 实现递归分隔符栈、字符级兜底、Markdown 围栏代码块原子保护、标题正文粘合、尾部 overlap、参数规范化及父子块复用。 |
| 原因 | 将原有粗粒度切分替换为可验证的文档切割设计，保留语义边界和检索上下文连续性。 |
| 验证方式 | `python -m unittest discover -s test/trade_rag -v`：5 项通过；`python -m compileall -q trade_rag` 通过。 |
| 操作者 | Codex |

## 2026-07-21 17:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/query_rewriter.py`、`trade_rag/contracts.py`、`trade_rag/retrieval.py`、`trade_rag/pipeline.py`、`test/trade_rag/`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `QUERY_REWRITER_DESIGN.md` 实现历史感知、多查询改写、严格 JSON/代码块解析、长度校验、顺序去重和失败回退；接入多查询检索及稳定 Child ID 的 RRF 融合，融合后仅精排一次。 |
| 原因 | 提升指代、省略和同义表达场景的召回覆盖率，同时保持原始问题路由、服务端 ACL 和安全降级边界。 |
| 验证方式 | `python -m unittest discover -s test/trade_rag -v`；`python -m compileall -q trade_rag`。 |
| 操作者 | Codex |

## 2026-07-21 17:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `trade_rag/reranker.py`、`trade_rag/contracts.py`、`trade_rag/retrieval.py`、`trade_rag/pipeline.py`、`test/trade_rag/test_reranker.py`、`test/trade_rag/test_pipeline.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `RERANKER_DESIGN.md` 实现一次 Listwise 精排序、候选预览、严格评分校验、RRF 稳定同分、失败降级、独立分数字段、来源标签、候选池扩容及最终父块去重。 |
| 原因 | 在不降低粗召回可用性的前提下提高最终候选相关性，并避免重复父块浪费生成上下文。 |
| 验证方式 | `python -m unittest discover -s test/trade_rag -v`：13 项通过；`python -m compileall -q trade_rag` 通过。 |
| 操作者 | Codex |

## 2026-07-21 18:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `.env.example`、`trade_rag/config.py`、`test/trade_rag/test_config.py` |
| 变更摘要 | 增加 Embedding 与 Rerank API 的环境变量模板、项目根 `.env` 安全加载、数值校验、配置完整性检查和远程数据传输授权门禁。 |
| 原因 | 允许用户通过环境变量填写两个 API，同时避免密钥进入代码、日志或版本控制。 |
| 验证方式 | 运行 `trade_rag` 单元测试和 Python 编译检查；测试只使用虚构密钥。 |
| 操作者 | Codex |

## 2026-07-21 18:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `manager/launcher.py`、`manager/ui/js/mcp.js`、`config.json`、`config.py`、`agent/tools/mcp_server.py`、`test/test_manager_mcp_discovery.py` |
| 变更摘要 | Manager 增加项目 MCP 入口发现状态；注册 `trade_rag`；使用 `{python}` 绑定 Gateway 当前解释器；启用开关在配置加载时生效；UI 区分已配置与已发现未注册服务。 |
| 原因 | 修复 Manager 只读取配置、不发现 RAG MCP，以及子服务误用系统 Python 导致缺少 `mcp` 包的问题。 |
| 验证方式 | Manager 发现列表测试、`trade_rag` stdio MCP 握手测试和现有 RAG 回归测试。 |
| 操作者 | Codex |

## 2026-07-21 19:15:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `config.py`、`manager/launcher.py`、`manager/ui/js/api.js`、`manager/ui/js/gateway.js`、`.env.example`、`test/test_manager_gateway_startup.py` |
| 变更摘要 | 修复 Gateway 未加载项目 `.env` 导致 API Key 丢失；增加 `NANOCLAW_WEB_HOST/PORT`；Manager 增加 Web 端口就绪探测、动态 Web URL 和按钮状态。 |
| 原因 | Launcher 之前把 Gateway 子进程误判为可用，实际 Web 端口绑定失败后仍允许打开固定 8080。 |
| 验证方式 | 配置读取确认 API Key 已加载；RAG 16 项测试通过；Gateway 启动复现确认 8080 的 `WinError 10013` 并记录日志。 |
| 操作者 | Codex |

## 2026-07-21 19:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `.env`、`.env.example`、`config.json`、`config.py`、`manager/launcher.py`、`manager/ui/index.html`、`agent/tools/mcp_server.py` |
| 变更摘要 | 将本地 Web 端口切换为已验证可绑定的 8765；Manager/Gateway 统一读取 `.env`；修正重复变量最后一项生效；前端缓存版本更新；MCP 上下文按 LIFO 关闭。 |
| 原因 | 实际日志确认 8080 被 Windows 拒绝绑定，旧 Gateway 因 WebChannel 返回而整体退出；同时 `.env` 中 API Key 当前为空。 |
| 验证方式 | 8765 本机绑定成功；配置解析为 `127.0.0.1:8765`；进程环境 API Key 优先验证通过；RAG 16 项测试通过。 |
| 操作者 | Codex |

## 2026-07-21 19:45:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `manager/ui/js/gateway.js`、`manager/ui/index.html`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 将“打开 Web UI”改为点击调用栈内同步打开已缓存的动态 URL，避免异步 fetch 后调用 `window.open` 被浏览器弹窗策略拦截；更新前端缓存版本。 |
| 原因 | 服务端、Manager API 和浏览器实测均确认 Web 可用，剩余故障是异步按钮处理触发弹窗拦截。 |
| 验证方式 | `http://127.0.0.1:8765/` 返回 200；浏览器页面标题 NanoClaw、状态在线、输入框可用且无控制台错误；Manager v4 脚本已生效。 |
| 操作者 | Codex |

## 2026-07-21 20:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `manager/ui/js/gateway.js`、`manager/ui/index.html` |
| 变更摘要 | 将网关页“打开 Web UI”改为原生同页链接，Web 就绪时直接设置 `href`，不再依赖 `window.open`、异步事件或新标签页策略；缓存版本更新为 v6。 |
| 原因 | 实测链接地址正确，但目标浏览器仍阻止 `target=_blank` 创建标签页；同页导航具有最高兼容性。 |
| 验证方式 | Manager 状态 API 返回 `web_ready=true`、`web_url=http://127.0.0.1:8765`；链接 href 正确，服务端 8765 返回 200。 |
| 操作者 | Codex |

## 2026-07-21 15:30:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `business/config.py`、`business/business_config.json`、`business/database.py`、`.env`、`.env.example`、`.env.docker.example` |
| 变更摘要 | 增加 `BUSINESS_DATABASE_BACKEND` 数据库开关，支持 `sqlite`/`mysql`；根 `.env` 可用于本地默认配置，Docker 进程环境变量优先覆盖；增加 SQLite 路径和 Docker MySQL 示例。 |
| 原因 | 本地无需 MySQL 即可运行，后续 Docker 部署 MySQL 时无需改代码即可切换。 |
| 验证方式 | 验证默认解析为 SQLite；环境变量切换后解析为 MySQL 和容器主机名；非法后端值被拒绝；SQLite 11 个产品读取正常。 |
| 操作者 | Codex |

## 2026-07-21 15:20:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `business/database.py`、`business/sqlite_database.py`、`business/mysql_database.py`、`business/seed_data.py`、`business/business_config.json`、`mcp_servers/foreign_trade_inquiry_server.py`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 增加 SQLite 本地开发后端；通过数据库 Facade 在 SQLite 与 MySQL `trade_ops` 间切换。默认开发模式使用 `business/data/business.db`，保留 MySQL 迁移和生产 Repository。 |
| 原因 | 当前电脑未安装 MySQL，需要先验证业务流程和 MCP 工具可用性。 |
| 验证方式 | SQLite 初始化、11 个种子产品、USD/CNY 汇率、库存校验、MCP 7 工具注册和 Python 编译均通过；未连接 MySQL。 |
| 操作者 | Codex |

## 2026-07-21 15:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `business/database.py`、`business/migrations/001_trade_ops_core.mysql.sql`、`business/config.py`、`business/business_config.json`、`business/seed_data.py`、`business/tools/*.py`、`mcp_servers/foreign_trade_inquiry_server.py`、`requirements.txt`、`.env.example`、`docs/project/PROJECT_PROGRESS.md` |
| 变更摘要 | 按 `DATA_WAREHOUSE_DESIGN.md` 将业务目标切换为 MySQL `trade_ops`；新增 `ops_*` 规范化核心迁移表，替换 SQLite Repository，加入 Decimal/哈希/版本锁定/审批绑定，并恢复 `business/tools/` 作为实际运行源。 |
| 原因 | 让询盘、产品、报价版本、审批、跟进和汇率数据遵循设计文档的结构化业务库边界，避免敏感正文和业务对象压缩为 JSON。 |
| 验证方式 | Python 编译检查通过；配置、导入和 SQL 对象静态核对通过；未连接或修改真实 MySQL。当前缺少 `pymysql`、MySQL 实例、迁移执行和端到端验收。 |
| 操作者 | Codex |

## 2026-07-21 14:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `BUSINESS_MODULE_ROADMAP.md`、`PROJECT_PROGRESS.md`、`PROJECT_CHANGELOG.md` |
| 变更摘要 | 按 `business-module.md` 新增 P0-P5 分阶段实施计划、询盘到报价到审批跟进的 Mermaid 主题流程、横向安全/幂等/可观测性控制和最小验收场景；核对当前 checkout，明确 `business/` 尚未落地。 |
| 原因 | 将业务模块改动记录转化为可执行、可验收且不混淆设计与实现状态的实施路线。 |
| 验证方式 | 读取 `business-module.md`、`config.json`、目录树及现有进度/变更记录；确认未创建数据库、未安装依赖、未注册 MCP 或修改 NanoClaw Python 源码。 |
| 操作者 | Codex |

## 2026-07-21 13:44:39 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `DATA_WAREHOUSE_DESIGN.md`、`PROJECT_PROGRESS.md`、`PROJECT_CHANGELOG.md` |
| 变更摘要 | 按参考图将外贸数据库设计扩展为 `trade_ops → trade_dw → 配置文件 → 元数据同步 → trade_metadata/Qdrant/Elasticsearch → Agent → 安全 SQL` 链路；补充外贸数仓事实与汇总、四张五字段元数据表及 MySQL DDL、YAML 示例、构建期和查询期状态机、权限隐私及分阶段验收。 |
| 原因 | 让外贸询盘、报价与跟单 Agent 能依据正式表、字段、指标和允许字段值生成可审计的只读分析 SQL。 |
| 验证方式 | 检查 Markdown 标题、Mermaid/SQL/YAML 围栏、四表字段数、外贸术语、权威源边界和实施状态；确认没有创建数据库、安装依赖或部署索引服务。 |
| 操作者 | Codex |

## 2026-07-21 12:05:31 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `RAG_ENTERPRISE_KNOWLEDGE_BASE_SCENARIO_C_PLAN.md`、`PROJECT_PROGRESS.md`、`PROJECT_CHANGELOG.md` |
| 变更摘要 | 新增 MVP 必装、按场景可选及非 Python 基础设施依赖，标明每项对应阶段、用途和当前状态；补充 `uv add --bounds exact` 分组安装命令、锁定与安装后验收规则。 |
| 原因 | 明确后续实施需要安装的依赖，同时避免在没有锁文件和兼容性验证时臆造精确版本。 |
| 验证方式 | 对照 `pyproject.toml`、`requirements.txt`、项目 Python 版本和 `uv.lock` 存在性；检查依赖表列完整、命令未实际执行、进度未误报实现完成。 |
| 操作者 | Codex |

## 2026-07-21 11:52:59 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `RAG_ENTERPRISE_KNOWLEDGE_BASE_SCENARIO_C_PLAN.md`、`business-module.md`、`PROJECT_PROGRESS.md`、`PROJECT_CHANGELOG.md` |
| 变更摘要 | 将场景 C 计划重构为离线四步和在线四步；补充父子 Chunk、向量库选型、Qdrant 推荐、按需 Rerank 质量门禁、引用生成、安全治理、验收指标和实施路线；同步修正业务模块中的数据库边界说明，并新增进度与变更证据。 |
| 原因 | 对齐用户指定的 RAG 生命周期，并消除 PostgreSQL + pgvector 与当前 MySQL 业务权威库之间的职责冲突。 |
| 验证方式 | 检查 Markdown 标题、Mermaid 代码块、关键术语、阶段状态和仓库依赖现状；确认未安装依赖、未创建数据库、未实现 RAG 代码。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-21 16:00:00 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | 	rade_rag/、	est/trade_rag/test_pipeline.py、docs/project/PROJECT_PROGRESS.md |
| 变更摘要 | 按场景 C 计划搭建无新增依赖的 RAG 框架骨架，未连接真实外部服务。 |
| 验证方式 | 运行 pytest 和 Python 编译检查。 |
| 操作者 | Codex |

## 2026-07-22 20:20:44 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/project/项目更新计划.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 结合现有 Web 会话、知识库/RAG、外贸业务工具和邮件询盘成果，将三项提案重构为 M0-M5 详细实施计划；补充当前差距、目标架构、数据/API/事件契约、父子块统计与安全删除、多对话迁移、流程窗口、可选问数 SQL 子流程、测试矩阵、灰度回滚和完成定义；同时修正进度表中已失效的 RAG 文档路径及“代码尚未落地”等旧状态。 |
| 原因 | 原提案只有功能描述和一条 SQL 示例流程，未区分现有成果与待开发能力，也缺少状态契约、删除传播、迁移、测试和安全边界，无法直接进入实施。 |
| 验证方式 | 读取并交叉核对 `channels/web.py`、`channels/web_ui/`、`session/manager.py`、`gateway.py`、`agent/loop.py`、`trade_rag/`、`agent/business/`、`agent/tools/` 及现有设计/进度文档；执行主项目与隔离 RAG 测试。主项目为 67 通过、2 失败、40 个子测试通过；隔离 RAG 为 22 通过；整仓收集冲突已列入 M0。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。

## 2026-07-22 21:03:05 +08:00

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/project/关于Agent执行多步任务时，某一步失败了的处理方法.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 将原有简要失败处理办法扩展为 M0-M7 实施计划；新增显性/隐性/部分副作用/结果不确定等失败分类，Run/Step/Attempt/Receipt 状态契约，工具 allowlist 与四层参数校验，统一超时、重试、幂等核对、后置条件、Outcome Verifier、有界 Reflection、循环检测、补偿和人工接管，并给出外贸逐节点故障注入矩阵。 |
| 原因 | 当前通用 AgentLoop 只有完全相同调用的高阈值熔断、轮次上限和对话压缩，缺少证明多步失败能被安全识别、恢复或接管的专项测试与持久执行状态。 |
| 验证方式 | 核对 `agent/loop.py`、`agent/tools/registry.py`、`agent/tools/mcp_server.py`、`providers/openai_compat.py`、`agent/memory.py`、`agent/business/` 和 `test/`；确认当前没有 AgentLoop 多步失败专项测试，邮件询盘已有超时、租约、重试和 outbox 测试可复用。检查计划 Markdown 围栏、表格、状态和敏感信息。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。


## 2026-07-23（项目更新计划 M5）

| 项目 | 内容 |
|---|---|
| 变更摘要 | 增加多对话、知识管理、流程事件三个受控发布开关与能力 API；关闭入口仅回滚功能可见性，不删除持久数据。manifest v1 升级前自动保留只读备份，升级写入失败恢复旧 manifest。新增 M5 安全、性能、恢复和发布回滚验收套件。 |
| 修改位置 | `config.py`、`.env.example`、`channels/web.py`、`trade_rag/knowledge_repository.py`、`test/test_m5_acceptance.py`、`test/m5_live_server.py` 及项目状态文档 |
| 验证方式 | 主项目 `107 passed, 40 subtests passed`；便携 RAG 22 项通过；JS 语法和 Python 编译通过。实际工作区迁移 dry-run：3 个合法 JSONL、33 条合法记录、2 个已有索引、0 个待索引。临时本地服务能力 API 返回 200。 |
| 发布边界 | Codex 内置浏览器无法访问宿主本地端口且 Chrome 控制未连接，故真实 Chromium 桌面/移动视觉 E2E 未标为通过；pgvector/Milvus、7 天物理清理、生产 MySQL、真实数据及外发均未执行。 |
## 2026-07-23（工作区流程与侧栏交互修复）

| 项目 | 内容 |
|---|---|
| 变更摘要 | 修复业务流程窗只显示英文且不能跟随当前对话实时变化的问题：流程绑定时加载当前对话快照，WebSocket 事件即时合并，并每 3 秒从服务端补拉，按当前语言翻译流程类型、节点、状态和提示。新增最左菜单栏文字展开/收起及工作空间侧栏独立收起/展开，状态持久化并适配移动布局。 |
| 修改位置 | `channels/web_ui/index.html`、`channels/web_ui/static/app.js`、`channels/web_ui/static/app.css`、`test/test_web_file_import.py`、项目进度文档 |
| 验证方式 | JavaScript 语法、Python 编译通过；Web UI 页面、静态脚本及能力 API 本地服务返回 200；相关 Web/流程/对话/M5 测试通过。Codex 内置浏览器仍受宿主本地端口隔离，未将视觉 E2E 标记为通过。 |
## 2026-07-23（双端前端视觉整合）

| 项目 | 内容 |
|---|---|
| 变更摘要 | 根据 `NanoClaw-Reusable-Frontend` 设计指南增加 `/customer` 客户询盘门户和 `/ops` 业务员工作台视觉预览，并从现有工作空间侧栏提供入口。页面具备响应式布局、键盘焦点、预览输入、对话框与状态提示。 |
| 安全边界 | 按用户确认仅整合视觉与交互：未实现或调用 BFF、客户独立会话、WebSocket、审批、真实邮件、内部口令或任何写操作；客户输入不会传输或保存，业务台不显示虚假业务数据。 |
| 验证方式 | HTTP 页面/静态资源契约测试、JS 语法检查和主项目全量测试。 |

## 2026-07-23（双端前端阶段 1 视觉基线统一）

| 项目 | 内容 |
|---|---|
| 变更摘要 | 将 `/customer` 与 `/ops` 的旧版蓝色预览样式替换为与主工作区同源的 NanoClaw 橙色令牌；拆分共享令牌、通用样式、客户端样式、业务端样式和主题脚本，补充深浅主题、900px/680px 响应式布局、键盘焦点与减少动效支持。 |
| 修改位置 | `channels/web_ui/customer.html`、`channels/web_ui/ops.html`、`channels/web_ui/static/css/`、`channels/web_ui/static/js/theme.js`、`test/test_web_file_import.py` 及前端交付文档。 |
| 安全边界 | 仍只整合视觉与交互：未实现或调用客户 WebSocket、BFF、审批、报价、邮件、认证或写操作；客户输入只在当前 DOM 中预览且不会传输或保存。 |
| 验证方式 | 静态资源/页面契约测试、JavaScript 语法、Python 编译、主项目测试及浏览器桌面/窄屏交互验收。 |

## 2026-07-23（记忆管理更新方案）

| 项目 | 内容 |
|---|---|
| 修改位置 | `docs/archive/记忆管理更新.md`、`docs/project/PROJECT_PROGRESS.md`、`docs/project/PROJECT_CHANGELOG.md` |
| 变更摘要 | 基于原 `docs/archive/记忆管理.md` 编写可落地的更新方案，补充当前实现基线、三层目标架构、结构化工作记忆、语义/情节/程序记忆模型、写入与召回、衰减与删除、存储接口、M0-M5 实施计划及验收标准。 |
| 原因 | 原文主要说明概念和示例，缺少与当前 NanoClaw 代码的差距说明、数据契约、权限治理、迁移路径和可验证的完成定义。 |
| 验证方式 | 对照 `agent/memory.py`、`agent/context.py`、`agent/loop.py`、`session/manager.py`、`main.py` 和 `workspace/memory/` 核验现状；检查 Markdown 标题、表格、代码围栏和 Mermaid 结构；确认仅交付设计文档，未误报运行代码已实现。 |
| 操作者 | Codex |

提交前请用户自行复核 `git status` 与 `git diff`，确认后再提交和推送；本次未代替用户执行 Git 提交。
