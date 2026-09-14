# 内部员工 Agent 架构与状态边界

## 设计结论

内部员工 Agent 的模型—工具编排使用独立的 `employee_agent` LangGraph runtime。
它不引用 NanoClaw 模块，也不承载渠道、鉴权或业务数据库职责。

NanoClaw 只通过 `NanoClawEmployeeAgentAdapter` 接入该 runtime，并注入已有的模型、
工具、MCP、会话、工作流和记忆生命周期。客户咨询 Agent 不受本次改造影响。

```text
CLI / Web / QQ / 飞书
        ↓
NanoClaw：鉴权、路由、会话、工具装配
        ↓  薄适配层
employee_agent：LangGraph 编排、单轮恢复断点
        ↓  调用现有服务
RFQ / 产品 / 报价 / 审批 / 邮件 / 记忆
```

## 状态保存位置

| 状态 | 保存位置 | 权威性 | 生命周期 |
|---|---|---|---|
| 当前模型消息、待执行工具、迭代次数 | Redis DB 1（默认 `redis://127.0.0.1:6379/1`） | 仅恢复断点 | 未完成时最多保留 7 天，成功后删除 |
| 对话历史 | SessionManager 或已配置的 MySQL 会话库 | 对话权威数据 | 按原有会话策略 |
| RFQ、产品、报价、审批、邮件 | 业务 SQLite 或 MySQL | 业务权威数据 | 按原有业务策略 |
| 工作记忆、长期记忆 | 原有 SQLite / MySQL / Milvus 分层 | 记忆权威数据 | 按原有记忆策略 |
| 工作流事件 | 原有 WorkflowService 存储 | 工作流权威数据 | 按原有工作流策略 |

LangGraph Redis 断点不是业务数据库，也不能用于查询报价或审批状态。SQLite Checkpointer
只保留给自动化测试和明确的本地隔离测试。

## 恢复规则

- 断点 ID 由租户、用户、会话和请求 ID 共同生成，不同用户或会话不能共用断点。
- 同一请求在模型已选定工具后失败，重试会从待执行工具继续，不重复生成上一轮模型决策。
- 同一轮有多个工具时，每完成一个工具就写入一次断点，后续工具失败不会重跑已完成的前序工具。
- 最终回复写入会话后删除对应断点，避免把已完成对话长期复制到编排库。
- Redis Checkpointer 使用 JSON 数据；内部 Agent 图状态只写入基础字典、列表和标量。
- Redis key 使用 `employee_checkpoint` 命名空间，并与客户产品缓存分离到不同 DB。

进程恰好在“外部工具已经产生副作用、但 LangGraph 尚未来得及保存该工具完成状态”的
极小窗口内崩溃时，该工具仍可能在恢复时重试。涉及报价、审批、发送等写操作时，业务服务
自己的幂等键和数据库约束仍是最终保障；LangGraph 断点不能替代业务幂等。

## 配置

正式运行配置：

```dotenv
EMPLOYEE_AGENT_CHECKPOINT_BACKEND=redis
EMPLOYEE_AGENT_REDIS_URL=redis://127.0.0.1:6379/1
EMPLOYEE_AGENT_CHECKPOINT_TTL_MINUTES=10080
EMPLOYEE_AGENT_REDIS_CONNECT_TIMEOUT_SECONDS=5
```

SQLite 配置只用于测试：

```dotenv
EMPLOYEE_AGENT_CHECKPOINT_BACKEND=sqlite
EMPLOYEE_AGENT_CHECKPOINT_PATH=workspace/internal_agent/checkpoints.sqlite3
```

将后端设为 `off` 会关闭编排断点，但不会关闭或改变会话、业务数据、工作流和记忆持久化。
Redis Checkpointer 需要 RedisJSON 和 RediSearch；项目 Compose 使用 Redis 8 提供这些能力。

## 不纳入 LangGraph 的部分

- NanoClaw 的渠道、Gateway、RBAC、JWT 和 Agent 路由
- MCP Server 和 ToolRegistry 的业务实现
- RFQ、报价、审批、邮件与产品服务
- 客户产品咨询 Agent 的三个受控查询工具
- SessionManager、MemoryLifecycle 和 WorkflowService 的持久化规则

这些模块已经有清晰职责，没有为了框架统一而强行改写。
