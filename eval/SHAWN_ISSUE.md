# 致 Shawn：远程 mercatoria 检索服务的中文召回问题

> 来源：Agent 3 L3 评测（2026-11-19），owner devin 转交
> 服务：`http://59.110.213.187:8080`（mercatoria:prod，143 部 / 11562 chunks）

## 现象：中文查询经常召回完全不相关的条文

用生产客户端 `HttpRetriever` 打 `/v1/retrieve`，两类实测：

**1）20 题检索评测（Recall@5 = 0.817 / MRR = 0.817）里仅有的 2 个失败，都是同一模式**

| 问题 | gold | 实际 top-5 |
|---|---|---|
| 美国海关对进口货物完税价格的估价方法有哪些？ | `us-cfr-19-152` | 中国《海关审定进出口货物完税价格办法》 |
| 美国商务部反倾销调查的程序规定是什么？ | `us-cfr-19-165` | 中国《反倾销条例》 |

中文提问 + 明确写了「美国」，仍全部路由到中国法规；语料里 73 部 US 法规没被召回。

**2）12 份域内文档跑 agent3 得到的 50 条 claim，豆包专家版独立复核判定 43 条主题无关**

| 输入文档主题 | 检索回来并摘成 claim 的内容 |
|---|---|
| 进口货物完税价格 | 海关扣留货物期限不得超过 1 年 / 进口滞报金 / 欧盟海关法典 |
| CISG 货物不符通知期限 | 贸易法规公布管理 / 贸易障碍表述 |
| OFAC 制裁资产冻结 | 独立保函定义 / 涉外独立保函法律适用 |
| 两用物项出口管制 | 独立保函司法适用规则 |

## 关键澄清：不是数据问题，是召回问题

- 每条 claim 的 `chunk_id` 都真实存在于本次 `retrieved`，文本逐字可在被引 chunk 原文定位（50/50 通过，重跑可复现）
- 服务端 `/health` 正常、rerank 已开启、`expand_cross_language=true` 已配置
- 因此结论是：**BM25/向量融合对中文查询的召回信号弱，且 top-5 几乎总能填满**（超纲问题也返回 5 条无关 chunk）

## 附带影响（我们这边已如实登记）

1. `answer.py:122` 的 `coverage.unavailable = not retrieved` 只看「有没有返回」，不看「返得对不对」→ 超纲输入时 `unavailable` 恒为 false。spec 8.5 的拒答判据因此失效，我们已登记为已知缺口、任务 8.5 保持未勾
2. `/v1/chat` 的 `answer_status` 在两轮复测中不稳定（同样 10 题，partial 从 2 条变 1 条且落在不同题），但 answer 文本 10/10 都明确拒答

## 建议（服务侧，不在 Agent 3 客户端修）

1. 中文查询的跨语言检索增强：目前 `expand_cross_language=true` 似乎未生效，建议查 query 改写 / 多语言 embedding 是否覆盖中文→英文法规
2. 相关性阈值或低分兜底：当 top-1 分数明显偏低时应返回空或标注「无可靠命中」，让 `coverage.unavailable` 能真正触发（但需谨慎定义，避免引入语义判断）
3. `answer_status` 分类：answer 正文明确写「依据不足」时，应判 `unsupported`，不要因「有 citations」判 `partial`

## 复现材料

- `eval/gold_retrieval.json`（20 题）
- `eval/citations_50.csv`（50 条 claim，label 列为可定位性判定）
- `eval/doubao_comparison.csv`（逐条对照）
- `eval/doubao_review.md`（独立复核分析）
- `eval/retrieval_report.md`（Recall@5/MRR 明细）
- `eval/refusal_agent3.md`（超纲 coverage 实测 0/10）

以上文件均为公开法规条文 + 评测数据，不含 token / 内网凭据。
