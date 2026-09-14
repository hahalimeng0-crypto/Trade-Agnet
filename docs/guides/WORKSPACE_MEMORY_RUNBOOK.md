# 工作空间 Agent 记忆运行手册

## 1. 当前安全状态

工作空间记忆代码已落地，但所有新增能力默认关闭。不要把 `local_hash` 的离线结果描述为真实语义检索质量；不要把记忆作为报价、库存、审批、邮件发送或交易状态的权威来源。

客户记忆数据库、客户 `pending_consent`、公开批准记忆与 `trade_rag` 均不属于本手册的迁移范围。

## 2. 开启前检查与迁移

先保持 Agent 停止，检查当前 checkout 路径与配置。dry-run 不创建数据库、不创建快照、不修改 Markdown：

```powershell
.\.venv\Scripts\python.exe -m agent.memory_runtime.migrate_workspace_markdown --dry-run --config config.json
```

确认候选数量与 `project_id` 后执行 apply：

```powershell
.\.venv\Scripts\python.exe -m agent.memory_runtime.migrate_workspace_markdown --apply --config config.json
```

apply 会先在 `workspace/memory/migration_backups/<UTC timestamp>/` 保存会话、`MEMORY.md`、`HISTORY.md` 和一致的 SQLite 快照及 SHA-256 清单，然后把非标题条目幂等导入为 semantic `pending_confirmation`。它不会激活候选，不会覆盖、删除或改写原 `MEMORY.md`。重复 apply 不会重复创建相同内容候选。

## 3. 本地分阶段开启

第一阶段只开启本地工作空间记忆；自动提取、混合索引、治理和审查仍保持关闭：

```dotenv
NANOCLAW_WORKSPACE_MEMORY_ENABLED=true
NANOCLAW_WORKSPACE_OPERATOR_ID=<trusted-local-operator-id>
NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID=<trusted-tenant-id>
NANOCLAW_WORKSPACE_MEMORY_AUTO_EXTRACT_ENABLED=false
NANOCLAW_WORKSPACE_MEMORY_HYBRID_ENABLED=false
NANOCLAW_WORKSPACE_MEMORY_GOVERNANCE_ENABLED=false
NANOCLAW_WORKSPACE_MEMORY_REVIEW_ENABLED=false
NANOCLAW_WORKSPACE_MEMORY_LEGACY_FALLBACK_ENABLED=true
NANOCLAW_WORKSPACE_MEMORY_EMBEDDING_BACKEND=local_hash
NANOCLAW_WORKSPACE_MEMORY_EXTERNAL_TRANSFER_APPROVED=false
```

使用 `/memory candidates` 查看候选，并逐条核对内容、来源、版本和哈希。只能使用完整命令确认：

```text
/memory confirm <id> <version> <hash>
```

确认/拒绝完成并通过新会话召回验收后，才可以分别开启自动提取和本地混合索引。此时仍使用 `local_hash`，外部传输、远程管理和定时 LLM 审查继续关闭。最后确认 legacy Markdown 不再需要后，设置 `NANOCLAW_WORKSPACE_MEMORY_LEGACY_FALLBACK_ENABLED=false`。

## 4. 管理 API

回环访问免密。非回环访问必须同时配置独立令牌和允许的 Origin：

```dotenv
NANOCLAW_WORKSPACE_MEMORY_ADMIN_TOKEN=<independent-random-token>
NANOCLAW_WORKSPACE_MEMORY_ADMIN_ALLOWED_ORIGINS=https://admin.example.com
```

所有写操作都携带当前 `version` 和 64 字符 `content_hash`；过期版本或哈希返回 409。常用路径：

- `GET /api/workspace/memories?status=pending_confirmation&limit=50`
- `GET /api/workspace/memories/{id}`
- `POST /api/workspace/memories/{id}/confirm`
- `POST /api/workspace/memories/{id}/reject`
- `PATCH /api/workspace/memories/{id}`
- `DELETE /api/workspace/memories/{id}?version=...&content_hash=...`
- `GET /api/workspace/memories/export`
- `POST /api/workspace/memories/review/run`

## 5. 外部 Embedding 门禁

只有数据传输审批和真实语义质量验收都通过后，才能配置 `openai_compatible`。以下配置缺一即启动失败：批准开关、HTTP(S) 地址、模型、密钥、固定维度。现有索引的模型或维度不匹配也会拒绝启动；必须显式重建匹配版本的派生索引，不能混读旧版本。

`restricted` 记忆不会进入外部向量调用。外部服务异常时允许明确降级为关键词检索，但不得静默换模型。

## 6. 验收与回退

按以下顺序验收：新会话生成目标/假设、工具证据更新、候选生成、确认前不召回、精确确认、另一会话召回、时间衰减、显式到期、审查建议仍待确认、重启后主存与索引一致。

回退时先停止 Agent，再将所有工作空间记忆开关设为 `false`。这会恢复 legacy 路径而不删除新数据库。需要恢复迁移前数据时，仅在 Agent 停止后从已核对 SHA-256 的快照恢复；保留当前数据库副本用于审计，不要覆盖原 `MEMORY.md`。

## 7. 本轮验证记录

- 工作空间及既有记忆专项：81 passed。
- 根目录全量：394 passed、3 skipped、40 subtests passed。
- `test2/rag_knowledge_base` 分发副本不包含 tests 目录；`examples.quickstart` 混合检索与引用 smoke 通过。
- 未执行真实迁移、未开启运行时、未写入现有记忆数据库、未调用外部 Embedding。
