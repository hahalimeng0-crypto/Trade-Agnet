# 多 Agent 入口路由

## 范围

本组件只负责认证之后、Agent 执行之前的入口决策，不修改两个 Agent 的提示词、
工具、RAG、记忆或业务流程。

```text
可信 Principal
  → RBAC 计算允许的 Agent 集合
  → 集合只有一个：直接选择，不调用模型
  → 集合有多个：小模型在允许 ID 中分类
  → 校验模型结果仍属于允许集合
  → Gateway 调用对应的现有 Agent 工厂
```

## 当前账号映射

| 账号角色 | 允许的 Agent | 业务名称 |
|---|---|---|
| `customer` | `customer_product_consultation` | 客户产品咨询 Agent（仅三个受控查询工具） |
| `employee` | `internal_quote_reply` | 内部外贸询盘与报价 Agent |
| `sales` | `internal_quote_reply` | 内部外贸询盘与报价 Agent |
| `quote_reviewer` | `internal_quote_reply` | 内部外贸询盘与报价 Agent |
| `admin` | `internal_quote_reply` | 内部外贸询盘与报价 Agent |

`internal_quote_reply` 是为兼容已有接口保留的稳定技术 ID；它对应的业务范围包括
询盘提取、产品匹配、报价草稿、审批协作、邮件回复草拟和跟进，并不表示另有一个
独立的“内部报价 Agent”。项目当前正式对外提供的就是上述两个 Agent。内部员工
Agent 的模型—工具循环由独立 `employee_agent` LangGraph runtime 编排，再通过薄适配层
接入 NanoClaw。NanoClaw 继续负责入口、权限、会话和工具装配；业务工具、MCP、工作流
事件和记忆生命周期保持原有实现，不强行并入任一框架。LangGraph Redis 只保存未完成
请求的编排断点，完成后自动清理；SQLite 只用于自动化和本地隔离测试。

客户角色和任一内部角色同时出现时返回
`mixed_account_realm_forbidden`，不会取权限并集。

按照当前一对一映射，小模型不会被调用。这不是缺少路由，而是 RBAC 已经给出
唯一正确结果。只有未来明确增加“可同时使用多个 Agent”的角色后，小模型才有
分类价值。

## 小模型约束

- 默认使用 `config.json` 的 `models.cheap`，也可通过
  `NANOCLAW_LLM_ROUTING_MODEL` 单独指定。
- 模型只收到用户问题和允许的 Agent ID，不接收密码或令牌。
- 输出必须是只有 `agent` 一个字段的 JSON。
- 未知 ID、越权 ID、无效 JSON或模型故障都不会扩大权限。
- 降级规则也只能在 RBAC 已允许的集合内选择。

## 启用

```dotenv
NANOCLAW_CUSTOMER_AUTH_ENABLED=true
NANOCLAW_ACCESS_CONTROL_ENABLED=true
NANOCLAW_LLM_ROUTING_ENABLED=true
NANOCLAW_LLM_ROUTING_MODEL=
```

路由开启后，没有服务端可信身份的消息会返回 `authentication_required`。目前适用
于已接入登录的内部 WebSocket 与客户门户；QQ、飞书和 CLI 需要各自完成可信身份
适配后才能在生产环境使用该路由入口。
