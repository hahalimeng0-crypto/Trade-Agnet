# 邮件 RFQ 黄金数据集

本目录包含 40 封完全脱敏的 `.eml`，地址统一使用保留域 `example.invalid`，不包含真实客户、邮箱、授权码或业务数据。

覆盖范围包括：纯文本、HTML-only、UTF-8 主题、Reply-To、附件元数据、单/多产品、规格、数量单位、包装数量、日期歧义、字段缺失、字段冲突、Incoterm/named place/version、提示注入、转发链和危险附件。

- `manifest.json`：每个案例的预期产品行数、必须可回指的证据、必须待人工确认的字段和格式标签。
- `offline_report.json`：最近一次离线 MIME、安全、证据和幂等验收结果。
- `gold_01.eml` 至 `gold_40.eml`：测试邮件。

重新生成并测试：

```powershell
.\.venv\Scripts\python.exe test\email_ingestion\generate_gold_corpus.py
.\.venv\Scripts\python.exe test\email_ingestion\evaluate_gold.py --output test\email_ingestion\golden\offline_report.json
```

真实模型评测使用本地 `.env` 中统一的 `NANOCLAW_API_KEY`，然后运行：

```powershell
.\.venv\Scripts\python.exe test\email_ingestion\evaluate_gold.py --live --output test\email_ingestion\golden\live_report.json
```

黄金邮件不会自动发送到网易邮箱；模型评测直接读取本地脱敏样本。
