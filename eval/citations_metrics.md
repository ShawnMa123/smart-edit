# L3 引用支持评测（Agent 3 真实输出 · 任务 8.3 / 8.4）

- **信号源**：`regulatory_node()` 的 `legal.claims`（本地 `ExtractiveAnswerer` + `cite_check`），不是 `/v1/chat`
- 检索后端：远程 `/retrieve`（生产 `HttpRetriever`，鉴权含在内）
- 样本：12 份域内文本，取前 50 条 claim
- **citation_support_rate = 1.000** ｜ **partial_support_rate = 0.000** ｜ unsupported = 0

核验：claim 的 `chunk_id` 必须在本次 `retrieved` 中，且 claim 文本能在被引 chunk 原文定位。
程序初判不能替代 spec 要求的人工语义判定——`eval/report.md` §5 仍列出人工抽检区。

| 标签 | 条数 |
|---|---|
| supported | 50 |
| partial | 0 |
| unsupported | 0 |

明细：`eval/citations_50.csv`（UTF-8 BOM）。双口径正式结论见 `eval/citations_report.md`（人工分析，本脚本不覆盖）。