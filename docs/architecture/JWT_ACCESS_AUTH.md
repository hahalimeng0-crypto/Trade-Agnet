# JWT 请求鉴权基础

## 安全顺序

```text
账号密码登录
  → 服务端校验密码
  → 签发 15 分钟 Access JWT 与可轮换 Refresh Token
  → HTTP / WebSocket 验签并构造可信 Principal
  → 通过后进入现有消息处理链路
```

模型输入、用户消息和前端提交的角色字段均不可信。`Principal` 只允许由服务端
验签结果或已经认证的客户会话构造。

当前身份记录可以保存角色，但本阶段不把角色映射到 Agent、RAG 或工具。
这些映射必须等待新的 Agent/RAG/工具设计确定后再实现，不能由前端或模型输入决定。

## 启用步骤

1. 同时开启 `NANOCLAW_CUSTOMER_AUTH_ENABLED=true` 和
   `NANOCLAW_ACCESS_CONTROL_ENABLED=true`。
2. 分别设置至少 32 字节的 `NANOCLAW_CUSTOMER_SESSION_SECRET` 与
   `NANOCLAW_JWT_SECRET`，两者不要复用。
3. 首次启动时临时设置 `NANOCLAW_BOOTSTRAP_USERNAME`、
   `NANOCLAW_BOOTSTRAP_PASSWORD`、`NANOCLAW_BOOTSTRAP_ROLES`。
4. 确认内部账号创建成功后，从运行环境中移除 Bootstrap 密码。

内部登录接口是 `POST /api/auth/login`。Access JWT 同时返回给前端并写入
`HttpOnly + SameSite=Strict` Cookie；普通 API 客户端也可使用
`Authorization: Bearer <token>`。刷新接口会轮换刷新令牌，旧令牌不能重放。

## 失败关闭

- JWT 密钥不足 32 字节时拒绝启动。
- 开启统一访问控制却未开启客户认证时拒绝启动。

## 暂不包含

- RAG 数据权限改造。
- Agent 工具清单或工具参数改造。

账号到 Agent 的入口映射和可选小模型分类见 `docs/architecture/LLM_AGENT_ROUTING.md`。
