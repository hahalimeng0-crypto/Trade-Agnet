# 外贸 RAG 评估

本目录保存版本化门禁配置；评估代码位于 `rag_evaluation/`，脱敏测试集位于
`test/fixtures/rag_eval/`。报告默认只包含聚合指标、失败用例 ID 和失败代码，
不写入问题、答案、文档正文或凭据。

## 本地可重复门禁

```powershell
.\.venv\Scripts\python.exe -m rag_evaluation.cli `
  test\fixtures\rag_eval\dev\external_trade_v1.jsonl `
  --dataset-version external-trade-dev-v1 `
  --fixture-corpus test\fixtures\rag_eval\corpus_v1.jsonl `
  --thresholds rag_evaluation\config\trade_gate_v1.json `
  --output .tmp\rag-eval-dev-report.json

.\.venv\Scripts\python.exe -m rag_evaluation.cli `
  test\fixtures\rag_eval\challenge\external_trade_challenge_v1.jsonl `
  --dataset-version external-trade-challenge-v1 `
  --fixture-corpus test\fixtures\rag_eval\corpus_v1.jsonl `
  --thresholds rag_evaluation\config\trade_gate_v1.json `
  --output .tmp\rag-eval-challenge-report.json
```

不传 `--fixture-corpus` 时会评估当前配置的真实 RAG 后端。此模式必须记录真实
Embedding、Reranker、生成模型、Prompt、索引代次和知识快照版本。任何 Mock
或脱敏 fixture 报告都会保持 `production_ready=false`。

## 数据集治理

- `dev`：提示词和检索调试可见集。
- `test`：不用于日常调参的盲测集。
- `challenge`：无证据、撤回、越权、注入、冲突、过期和高风险业务样本。
- 真实客户样本只有在获批、脱敏并完成访问审计后才能加入；不得提交原始客户数据。
- 同一事实的近似改写必须按 group ID 分组后再切分，避免训练/测试泄漏。

初始门槛是工程建议，不是生产校准结论。投入发布门禁前，需由外贸业务人员复核盲测
集，并校准语义 Judge；推荐最低 Cohen's kappa 为 0.70，同时“错误判定为有证据”
的比例不高于 2%。报价计算、动态数据路由、权限和业务承诺仍保持 100% 硬门禁。
