# RAG 完整评估师实施与运行手册

> 状态：M7-M10 本地框架和脱敏门禁已实施；真实盲测集、真实模型、人工 Judge
> 校准和生产监控尚未验收，因此不得标记生产就绪。

## 1. 已实施能力

项目不再把“包含关键词”等同于答案正确，而是将评估拆成独立门禁：

1. 检索：Recall@20、MRR、正确文档与位置。
2. 答案：逐主张证据支持、引用完整率、引用精度、必要事实与限制条件。
3. 业务：动态数据路由、报价 Decimal 复算、Incoterm 指定地点/版本/责任矩阵、
   数字/单位/币种检查、人工审批要求。
4. 安全：ACL、撤回文档、禁止动作、无证据拒答、动态数据不得由 RAG 编造。
5. 治理：版本化门槛、聚合脱敏报告、Judge 人工校准、候选版本回归比较。

核心实现：

- `rag_evaluation/contracts.py`：用例、指标、门槛和报告契约。
- `rag_evaluation/dataset.py`：JSONL 数据集加载、Schema 和重复 ID 校验。
- `rag_evaluation/judges.py`：检索、忠实度、业务和安全组合裁判。
- `rag_evaluation/business_rules.py`：报价与 Incoterm 确定性规则。
- `rag_evaluation/calibration.py`：自动 Judge 与人工标签的一致性校准。
- `rag_evaluation/regression.py`：版本报告退化检测。
- `rag_evaluation/runner.py`：执行、聚合、门禁和隐私安全报告。
- `rag_evaluation/config/trade_gate_v1.json`：版本化发布门槛。

## 2. RAG 接口改造

`QueryRequest.evaluation_mode` 默认关闭。关闭时，客户接口保持原有字段；开启后才返回：

- `claims`：原子主张和对应 citation ID；
- `assumptions`、`missing_information` 和人工确认标志；
- `_evaluation_trace`：路由、改写、候选、分数、精排状态和最终选中证据。

轨迹可能包含检索正文，只允许离线评估和受控诊断使用，客户适配器不得透传。

混合检索现在对语义与关键词相关性分别归一化，再用于置信判断；RRF 分只负责排序。
置信门比较不同 Parent 的候选，避免同一 Parent 的重叠 Child 造成假歧义。最高相关性
为 0 时返回 `NO_EVIDENCE`。当前抽取式生成器只采用最强 Parent，避免无条件拼接三个
无关来源；将来接入真正的多文档生成器后，必须显式输出每条主张的 citation IDs。

## 3. 外贸路由规则

| 路由 | 内容 | RAG 返回状态 |
|---|---|---|
| `rag` | Incoterms、产品规格、流程、统计方法等静态知识 | `ANSWERED`/拒答 |
| `mysql` | 实时价格、库存、汇率、报价记录 | `BUSINESS_DATA_REQUIRED` |
| `calculator` | 报价总额、折扣、币种换算等确定性计算 | `CALCULATION_REQUIRED` |
| `human_review` | 正式报价、发送动作、最终交期承诺 | `HUMAN_REVIEW_REQUIRED` |

路由器只负责阻止 RAG 越权作答。完整 Agent 在收到后三种状态时，应调用相应的只读
权威库、确定性工具或审批流程；评估 Runner 可以替换为完整 Agent 的 query callable，
继续使用同一数据集和业务裁判。

## 4. 用例标注要求

每条 JSONL 用例至少包含 `case_id/category/question/risk_level`，并按场景增加：

- `expected_route`、`expected_status`；
- `expected_citations`（document ID 和页码/章节）；
- `expected_facts`、`required_caveats`、`forbidden_claims`；
- `expected_numbers`（Decimal、容差、单位、币种）；
- `forbidden_document_ids`、`forbidden_actions`；
- `expected_no_citations`、`requires_human_confirmation`、`as_of`。

正式集应由业务人员标注并双人复核。建议首批 120-150 题，覆盖产品、Incoterms、
MOQ/报价、库存/交期、汇率、RFQ、多语种、单证、HS/贸易统计、冲突、拒答和安全；
稳定后扩展到 300 题以上。真实集必须分为 dev、test、challenge，盲测集不得用于调参。

## 5. LLM 语义 Judge

`SemanticSupportJudge` 接收一个受控生成回调，只允许看到单条 claim 和其引用证据，
要求严格返回 `supported/contradicted` JSON。确定性字符串支持检查优先运行；只有改写
或摘要主张才调用语义 Judge。

上线要求：

1. 不使用回答模型作为唯一裁判；使用独立 Judge 或第二裁判加人工仲裁。
2. 温度设为 0，记录模型、Prompt 和提供方版本。
3. 使用脱敏人工标签运行 `calibrate_binary_judge()`。
4. Judge 未达到校准门槛时只能输出观察指标，不能控制发布。
5. 涉及外部服务前必须完成数据出境和远程传输审批。

## 6. CI 与发布流程

### 每次提交

- 运行 `test/trade_rag/test_complete_evaluation.py`；
- 运行现有 PDF M6 门禁和 RAG 单元测试；
- 使用 Mock/fixture，只验证确定性、隔离和回归。

### 每晚

- 在受控环境运行真实 Embedding、Reranker 和生成模型；
- 执行完整 dev 与 challenge 集；
- 将报告和上一个已接受报告交给 `compare_reports()`；
- 任一硬门禁失败或关键指标下降超过 3%，阻止候选发布。

### 发布前

- 执行未参与调参的 test 盲测集；
- 人工复核全部 critical 失败和至少 10% 随机样本；
- 运行 ACL、撤回、提示注入、工具动作、性能和恢复门禁；
- 报告必须记录代码版本、知识快照、索引代次、模型和规则版本。

## 7. 线上闭环

经批准后，仅保存脱敏评估事件：case 类别、路由、状态、模型版本、指标和失败代码。
原始问题、答案、客户信息与文档正文不得进入聚合报告。低评分、人工纠正、错误拒答、
错误路由和无引用数字进入待复核池；复核通过后加入下一个数据集版本。按产品、国家、
语言、文档类型和风险等级观察漂移，不得只看全局平均分。

## 8. 当前客观边界

本地 dev 与 challenge fixture 可以重复通过，但这只能证明评估链路、规则和安全门禁
能工作。它不证明真实语义模型、真实 OCR、生产索引或现场外贸答案已经达标。
`production_ready=false` 是强制输出；只有获批真实盲测集、人工 Judge 校准、真实模型
全量门禁和线上监控均通过后，才能另行建立生产就绪报告。
