# NanoClaw 项目清理清单

> 盘点日期：2026-08-27。本文只给出候选项和用途，不代表已经删除。
> 业务数据、会话、知识库原文和审批记录必须先确认保留策略及备份，再执行清理。

## 结论

项目源码目录没有发现一个可以仅凭文件名安全判定为“无用”的业务模块。当前最明显的
冗余来自依赖缓存、测试临时目录、日志、OCR 下载缓存和历史运行数据。第一批应只清理
可重建内容，不动业务数据库、有效知识文档、会话和工作流记录。

## 执行记录

- 2026-08-27：A 类已执行清理，包括 `.pytest_cache/`、`.tmp/`、`.uv-cache/`、
  `workspace/browser-acceptance/`、项目源码中的 `__pycache__/`、`botpy.log*`、
  `workspace/runtime/*.log` 和 `workspace/browser-check.*.log`。
- 本次明确保留 `.venv/`、`.paddlex/` 以及 C 类全部业务和运行数据。
- 四个已盘点目录释放约 1.17 GB（十进制），另有少量字节码缓存和日志；所有目标均在
  `D:\Trade\nanoclaw` 内，删除前未发现引用该项目的运行进程。

## A. 可直接清理的可重建内容

| 路径 | 当前用途 | 盘点大小 | 清理影响 | 建议 |
|---|---|---:|---|---|
| `__pycache__/` 及各子目录同名缓存 | Python 字节码缓存 | 根目录约 0.3 MB | 下次运行自动重建 | 可直接清理 |
| `.pytest_cache/` | pytest 最近运行缓存 | 约 0.07 MB | 下次测试自动重建 | 可直接清理 |
| `.tmp/` | Docker、浏览器验收、PDF 和旧迁移测试的临时工作区 | 约 323 MB | 只丢失旧测试现场 | 确认没有正在运行的验收任务后清理 |
| `.uv-cache/` | Python 包下载及构建缓存 | 约 848 MB | 后续安装可能需要重新下载 | 磁盘紧张时清理 |
| `botpy.log*` | QQ Bot 历史运行日志 | 不固定 | 丢失本地故障排查历史 | 归档近期日志后清理旧文件 |
| `workspace/runtime/*.log` | Gateway 标准输出和错误日志 | 不固定 | 丢失本地启动排查历史 | 保留最近一次，其余清理 |
| `workspace/browser-check.*.log` | 浏览器验收日志 | 很小 | 无运行影响 | 可直接清理 |
| `workspace/browser-acceptance/` | 浏览器验收生成的会话和工作流样本 | 很小 | 只影响旧验收现场 | 验收结束后清理 |

这些路径已经补入 `.gitignore`，避免再次进入版本控制候选。

## B. 可以清理，但会增加下次启动或安装成本

| 路径 | 当前用途 | 盘点大小 | 注意事项 | 建议 |
|---|---|---:|---|---|
| `.venv/` | 当前项目 Python 虚拟环境 | 约 863 MB | 删除后必须用 `uv sync --frozen` 重建 | 环境损坏或需要释放空间时再清理 |
| `.idea/` | JetBrains IDE 的本地项目设置 | 约 0.04 MB | 会丢失个人 IDE 窗口和检查配置 | 不使用 JetBrains 时可清理 |
| `.paddlex/huggingface/`、`locks/`、`temp/`、`func_ret/` | OCR 下载、锁和运行缓存 | `.paddlex` 总计约 203 MB | 可能触发重新下载 | OCR 已离线验收后可清理缓存部分 |
| `.paddlex/official_models/PP-OCRv5_server_det/` | 未被当前代码选用的服务端检测模型 | 约 88 MB | 当前 `trade_rag/ocr.py` 使用 mobile 模型 | 确认没有外部脚本依赖后清理 |
| `.paddlex/official_models/PP-OCRv5_server_rec/` | 未被当前代码选用的服务端识别模型 | 约 85 MB | 当前 `trade_rag/ocr.py` 使用 mobile 模型 | 确认没有外部脚本依赖后清理 |

以下三个 OCR 模型是当前离线 OCR 路径使用或保留的模型，不应列入清理：

- `PP-OCRv5_mobile_det`
- `PP-OCRv5_mobile_rec`
- `PP-LCNet_x1_0_textline_ori`

## C. 必须人工确认的业务和运行数据

| 路径 | 当前用途 | 风险 | 建议 |
|---|---|---|---|
| `workspace/knowledge_base/trash/` | 知识库软删除原文和解析结果，约 11 MB | 删除后失去恢复能力 | 设定保留期后批量清空 |
| `workspace/knowledge_base/manifest.v2.backup.json`、`manifest.v3.backup.json` | 知识库清单迁移备份 | 旧版本回滚可能依赖 | 确认当前 manifest 和索引稳定后归档或删除 |
| `workspace/sessions/` | 内部及部分历史会话 | 可能包含业务上下文和审计证据 | 按会话保留策略处理，不手工散删 |
| `workspace/customer_sessions/` | 客户 Agent 独立会话 | 涉及客户数据、同意和删除义务 | 通过客户数据保留/删除流程处理 |
| `workspace/peer_sessions/` | Workspace Peer 的最小化分析历史 | 可能受 TTL 约束 | 按 peer memory TTL 清理 |
| `workspace/workflows/` | 询盘、报价、审批和跟进工作流运行记录 | 可能是业务审计证据 | 完成状态和法定期限确认后归档 |
| `workspace/output/Quote_12_Nordlicht_Internal_Draft.md` | 内部报价草稿 | 可能仍在审批或引用中 | 查明对应工作流状态后决定 |
| `workspace/analytics/query_audit.jsonl` | 内部数据查询审计 | 删除会降低可追溯性 | 按审计保留策略归档，不直接删除 |
| `workspace/knowledge_base/documents/`、`rag_index.db`、`manifest.json` | 当前知识原文、索引和权威清单 | 删除会让 RAG 缺数据或不一致 | 必须保留；只能走知识库撤回/重建流程 |

## D. 文档合并候选，不建议立即删除

| 文档 | 当前用途 | 建议处理 |
|---|---|---|
| `docs/archive/记忆管理.md` | 早期记忆方案 | 标注“历史方案”，后续并入三层记忆架构 |
| `docs/archive/记忆管理更新.md` | 记忆方案的阶段更新 | 已移入历史文档目录，后续与主文档核对后再决定是否删除 |
| `docs/architecture/三层记忆架构.md` | 当前总体记忆架构说明 | 保留为主文档 |
| `docs/architecture/工作空间与客户Agent记忆管理设计.md` | 双 Agent 数据域和访问方向设计 | 保留，或作为主文档的安全章节 |
| `docs/architecture/双Agent记忆管理代码设计.md` | M0-M6 的详细实现设计 | 保留为工程参考 |
| `docs/project/项目更新计划.md` | 阶段性规划 | 完成项迁入 `PROJECT_PROGRESS.md` 后归档 |
| `docs/project/PROJECT_PROGRESS.md` | 当前完成度和生产缺口 | 保留为状态权威 |
| `docs/project/PROJECT_CHANGELOG.md` | 历史变更和验收证据 | 保留，不与进度表混删 |

## 建议执行顺序

1. 先清理 A 类生成物，预计可释放约 1.17 GB，主要来自 `.tmp` 和 `.uv-cache`。
2. 若仍需释放空间，再清理未使用的两个 OCR server 模型，约 174 MB。
3. 业务数据只通过保留期、归档和审计流程清理。
4. 文档先合并和标记历史版本，再删除重复稿；不要按“文件名相似”直接删除。
