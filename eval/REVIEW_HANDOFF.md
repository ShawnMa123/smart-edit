# 独立复核交付包（给 owner devin 用）

> 目的：让**另一个 AI agent** 对 Agent 3 的 L3 评测做独立第二意见，避免单模型系统性偏差。
> 生成日期：2026-11-19 ｜ 复核对象：`eval/` 下的 L3 评测资产
> **使用规则：本文件整体只给你（人）看；只把 §3 代码块里的内容复制给复核 agent。**
>
> **两种场景，别用错**：
> - 复核 agent **能读工作区**（IDE 内另一个会话）→ 用 §2 白名单 + §3 的 prompt
> - 复核 agent **是聊天窗口**（本次用 **豆包 专家版**，读不到本地文件）→ 用 `eval/for_doubao.txt`
>   （`eval/for_doubao.py` 生成，单文件 19.7KB，材料与 prompt 已内联，**整段粘贴即可**）

---

## 1. 为什么这么设计（人读）

`openspec/changes/agent-verify/specs/eval-benchmark/spec.md:118-119` 有一条硬要求：

> MUST 只标"业务上应该报什么"，AND MUST NOT 参考模型实际报了什么

如果复核 agent 看到我已产出的结论（Recall@5、citation_support_rate、CSV 的 `label` 列），它会从「独立判真值」退化成「检查我的结论对不对」，独立性失效。**锚定是这份交付包要防的唯一风险。**

复核 agent 的产出必须是**它自己的两份独立判定表**，然后由你逐条比对，只看分歧项。

---

## 2. 白名单 / 黑名单（人读，发之前照此准备）

### ✅ 允许给复核 agent 的文件

| 文件 | 用途 |
|---|---|
| `eval/gold_retrieval.json` | 20 题 + 现有 gold（让它判断这些 gold 合不合理） |
| `openspec/changes/agent-verify/specs/eval-benchmark/spec.md` | L3 判据原文（MUST 条款） |
| `openspec/changes/agent-regulatory/proposal.md` | 责任边界：语料内容由 A/B 提供，C 不自撰法规内容 |
| `data/regulatory/corpus/README.md` | 语料领域范围（贸易/海关/出口管制/制裁），用于判断"超纲" |
| `scripts/rag_eval_agent3.py` 的 `IN_SCOPE_DOCS` / `OUT_OF_SCOPE_DOCS` | 12 份域内 + 10 份超纲文本 |
| 远程 `GET /v1/corpus/documents` 的 143 部清单 | 文档 ID 与法域的真实清单（复核 doc_id 笔误用） |
| `eval/citations_50.csv` **去掉 `label` / `check` / `support_field` 三列后** | 只剩 `claim_text` + `chunk_id` + `document`，让它独立判 |

### ❌ 禁止给复核 agent

| 文件/字段 | 原因 |
|---|---|
| `eval/report.md` | 我的自评结论（0.817 / 1.000 / 偏离登记）——强锚定 |
| `eval/citations_report.md`、`eval/retrieval_report.md` | 我的指标结论 |
| `eval/refusal_agent3.md`、`eval/refusal_report.md` | 我的拒答结论 |
| CSV 的 `label`、`check`、`support_field` 列 | 我的程序初判 |
| `AGENT3_REMOTE_RAG_PLAN.md` | 含预期结果 |
| **本文件（`REVIEW_HANDOFF.md`）** | 含上面全部结论 |

> 如果复核 agent 与你在**同一工作区**（能自己读文件），务必在 prompt 里保留"只读白名单、不得读取其他文件"的约束——§3 已写死。

---

## 3. 可直接复制给复核 agent 的 prompt

```
你是一个独立的评测复核员。你的任务是「不看任何已有结论，独立产出判定」，不是检查别人的工作。

【硬性只读约束】
只允许读取下列文件，禁止读取工作区内任何其他文件（尤其禁止 eval/report.md、
eval/*_report.md、AGENT3_REMOTE_RAG_PLAN.md、REVIEW_HANDOFF.md、任何含"自评/结论/指标"的文档）。
如果某个文件读不到，说明并跳过，不要去别处找答案。

白名单：
- eval/gold_retrieval.json
- openspec/changes/agent-verify/specs/eval-benchmark/spec.md
- openspec/changes/agent-regulatory/proposal.md
- data/regulatory/corpus/README.md
- scripts/rag_eval_agent3.py（只用来取 IN_SCOPE_DOCS / OUT_OF_SCOPE_DOCS 两个列表）
- eval/citations_50.csv 的 claim_text / chunk_id / document 三列
  （忽略 label / check / support_field 列；若无法只取列，请声明你未读取这三列的值）

【任务 A：gold 独立复核（20 题）】
对 eval/gold_retrieval.json 的每题，独立判断 gold_docs 里的文档 ID 是否与问题主题相符。
判据只用「望文生义 + 语料清单里该 ID 是否真实存在」，不要判断法规条文的实质内容。
逐题输出：题号 | 你判定的 gold_docs | 与文件里写的是否一致 | 理由一句话。
特别检查：文档 ID 是否有拼写错误或不存在于 143 部清单中。

【任务 B：claim 独立复核（50 条）】
对 CSV 每条（只读 claim_text / chunk_id / document 三列），判断该 claim 文本与对应
document 的主题是否属同一话题。
输出三档之一：supported（同话题且内容相关）/ partial（沾边但不直接相关）/ unsupported（明显无关）。
逐条输出：行号 | 你的判定 | 理由一句话。
注意：不要因为"文本逐字出现在某个 chunk 里"就判 supported——那是可定位性，不是主题相关性。

【任务 C：超纲题核对（10 条）】
看 scripts/rag_eval_agent3.py 的 OUT_OF_SCOPE_DOCS，结合语料领域说明，
判断这 10 条是否真的都超出语料覆盖范围。逐条给 是/否 + 一句话理由。

【输出要求】
- 只输出三张判定表 + 简短汇总（每题/每条一行），不要给综合分数、不要给"通过/不通过"结论
- 不要修改任何文件，不要写入 eval/ 下的任何文件
- 如果你发现自己依赖了白名单之外的信息，明确声明并标注该条判定无效
- 在结尾列出：你无法独立判断的条目编号（这些留给人工终裁）
```

---

## 4. 拿到复核结果后怎么做（人读，约 20–30 分钟）

1. **逐条比对两份判定表**，只挑出**分歧项**：
   - 任务 A 的分歧 → 打开 `eval/gold_retrieval.json` 看那个 doc_id，对照 143 部清单判断谁对
   - 任务 B 的分歧 → 打开 `eval/citations_50.csv`，看 `claim_text` 和 `document` 是不是同一话题
2. **分歧项你终裁**，按 spec 的分歧处理精神（`:121-124`）：各标一半、交叉复核、**不得由单方（含单个 AI）决定**
3. 把它判 `partial`/`unsupported` 而你原先判 `supported` 的条目，如实改 CSV 的 `label` 并重算 `citation_support_rate`
4. 复核 agent 标"无法独立判断"的条目，**保持未定**，不要替它填
5. 最后勾 `openspec/changes/agent-regulatory/tasks.md`（8 项可勾、8.5 按你的决定保持未勾）

### 签收责任

**最终勾选 tasks.md 只能由你（owner C）做**，不能委托给复核 agent。
理由：`proposal.md:47` 的责任边界 + 评测 spec 要求真值由 C 标注。AI 可以做第二意见，不能做签收人。

---

## 5. 一个提醒

两个 AI 可能犯**同类系统性错误**（比如都把"海关扣留期限"误当成支持"完税价格"）。若条件允许，用**不同模型家族**做复核；若只有同一模型，至少保证它没读到我的任何结论——这是本交付包唯一但最关键的价值。
