# L3 引用评测（Agent 3 真实输出 · 任务 8.3 / 8.4）

> 本报告为**人工分析**，`eval/run_eval.py` 一键重跑不会覆盖它；
> 机器生成的数字表在 `eval/citations_metrics.md` 与 `eval/l3_metrics.md`。

- **信号源**：`regulatory_node()` 的 `legal.claims`（本地 `ExtractiveAnswerer` + `cite_check`），不是 `/v1/chat`
- 检索后端：远程 `/retrieve`（生产 `HttpRetriever`，鉴权含在内）
- 样本：12 份域内文本，取前 50 条 claim
- 独立复核：**豆包 专家版**（`eval/doubao_review.md`，材料为无锚定的 `eval/for_doubao.txt`）

## 两个口径，两个名字，都报（owner 2026-11-19 定）

| 口径 | 正式名称 | 结果 | 证明什么 |
|---|---|---|---|
| 程序核验 | **引用可定位率**（claim_locatability_rate） | **50/50 = 1.000** | `chunk_id` 在本次 `retrieved`、claim 文本逐字可在被引 chunk 原文定位 → **零编造、可回溯** |
| 豆包专家版独立复核 | **主题相关率**（topic_relevance_rate） | supported 6 / partial 1 / **unsupported 43** → **6/50 = 0.12** | claim 与输入文档是否同一话题 → **引用是否答非所问** |

> ⚠️ **不再把 1.000 称为 `citation_support_rate`**。spec §L3 的 `supported` 定义是
> 「引用片段确实支持这句话」，属语义口径；1.000 只是可定位性，近乎 `ExtractiveAnswerer`
> 逐字摘取的结构性必然。两个数字各自标明，**不能只留好看的那个**。

| 程序可定位性 | 条数 |
|---|---|
| supported（逐字命中） | 50 |
| partial | 0 |
| unsupported | 0 |

| 豆包专家版主题相关性 | 条数 |
|---|---|
| supported | 6 |
| partial | 1 |
| unsupported | 43 |

**登记为检索质量缺口**：43/50 条 claim 与输入文档主题无关（问完税价格却摘到「海关扣留期限」，
问 OFAC 却摘到「独立保函定义」）。数据真实、可复现，问题在**远程检索对中文输入召回不准**，
与 Recall@5 中「中文问美国法」2 个失败同源。已转告 Shawn（见 `eval/SHAWN_ISSUE.md`）。

明细：`eval/citations_50.csv`（原 label 保留为可定位性判定，未改动）、
`eval/doubao_comparison.csv`（50 行逐条对照）。旧版基于 `/v1/chat` 的数据已作废。
