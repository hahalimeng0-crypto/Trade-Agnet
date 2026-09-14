# 项目目录结构

## 当前分层

```text
入口与装配       main.py / gateway.py / config.py
渠道层           channels/ / bus/
内部员工 Agent   employee_agent/
NanoClaw 适配层  agent/
业务 MCP         mcp_servers/
企业知识 RAG     trade_rag/
RAG 评估         rag_evaluation/
会话与模型接入   session/ / providers/
提示词           prompts/
部署             deploy/ / compose.yaml / Dockerfile
文档             docs/
测试             test/
运行数据         data/ / workspace/
示例             examples/
```

## 本次已经整理

- 内部员工和客户身份提示词从根目录移到 `prompts/`。
- 文档从单一 `doc/` 拆分为架构、指南、项目记录、参考资料和历史稿。
- 未启用的诗词 MCP 从正式 `mcp_servers/` 移到 `examples/mcp/`。
- RAG 评估阈值和说明合并到 `rag_evaluation/`。

## 暂时不移动

`agent/business/` 目前被业务工具、邮件服务、数据库迁移和大量测试直接引用，目录中还包含
本地业务数据库。把它移动到顶层 `business/` 在概念上更理想，但应先完成数据备份、导入路径
兼容层和独立迁移回归，不能只为视觉整齐直接搬动。

`gateway.py`、`config.py` 和 `main.py` 保留在根目录，因为它们是现有启动、Manager 和部署脚本
的稳定入口。等到发布入口统一后，再考虑放进 `app/` 包。

## 目录规则

- 正式 MCP Server 只放在 `mcp_servers/`；教学或演示服务放在 `examples/mcp/`。
- 身份和系统提示词只放在 `prompts/`，不要重新散落到根目录。
- 新文档必须选择 `architecture`、`guides`、`project`、`reference` 或 `archive`。
- 业务数据库、会话、知识原文和断点不得放进源码包；历史遗留数据另行迁移。
- SQLite 仅用于测试或明确的单机开发场景，生产后端按各模块配置执行。
