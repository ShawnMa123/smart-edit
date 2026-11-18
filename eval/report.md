# Agent 3 远程 RAG 接入 · 自评报告（P0–P4 全程实录）

> 执行者：CodeBuddy（AI）｜ 日期：2026-11-19 ｜ 复核人：devin（C / Agent 3 owner）
> 计划文件：`AGENT3_REMOTE_RAG_PLAN.md` ｜ 本报告为 AI 自评，标注**待人工复核**的结论在 §5

## 1. 一句话结论

agent3 已从「本机空转（knowledge_base_empty）」变为**直连 Shawn 的远程 mercatoria 服务并端到端跑通**：正路径 stage=done、5 chunks、corpus=143 部法规、R-001 finding 行为符合 design.md；三条负路径失败可区分、无假成功；L3 评测四项全部完成（指标见 §4）。

## 2. 代码与文件改动

| 文件 | 改动 | 性质 |
|---|---|---|
| `app/regulatory/retriever.py` | `HttpRetriever` 增加 `token` 参数 → 请求头按需加 `Authorization: Bearer`；`resolve_retriever()` 读 `SMART_EDIT_RAG_TOKEN`。token 为空则完全不加头（向后兼容） | 生产代码 ~10 行 |
| `tests/test_regulatory_http.py` | +4 测试：Bearer 头断言 / 无 token 不加头 / 401→RetrievalUnavailable / env 读取 | TDD 先红后绿 |
| `tests/test_live_rag_optional.py` | 新增：3 条 live 契约断言（health ready / retrieve 可引用 / 无 token 必须 401），默认 skip | 冒烟，不进回归 |
| `HANDOVER.md` | 环境变量表 +1 行（SMART_EDIT_RAG_TOKEN） | 文档 |
| `scripts/rag_eval_retrieval.py` 等 4 个脚本 | 评测 harness（20 题检索 / 10 题拒答 / 引用核验 / 重建闭环） | 可复跑 |

token 只走环境变量，**未写进任何被跟踪文件**。

## 3. 验证证据（每步命令均已实跑）

| 阶段 | 结果 |
|---|---|
| P0 基线 | 652 passed / 3 failed（环境性：本机无语料索引，与 655 Docker 基线差 3 条）/ 1 skip |
| P1 红灯→绿灯→回归 | 4 新测试先红（AttributeError: no attribute 'token'）→ 绿（9/9）→ 全量 656 passed，3 个环境失败原样 |
| P2 live 冒烟 | 3 passed（0.63s）；不设开关 3 skipped |
| P3 正路径 | create=201 → stage=200 → **agent3.status=done, produced=6**；legal.input_mode=raw；retrieved=5；coverage.corpus.documents=**143**（远程）；escalate_to_human=True（交易日期不确定→按设计转人工）；R-001=REG-TRANSACTION-DATE, warn, blocking=False |
| P3 负路径×3 | 错 token→`HTTP 401 from .../retrieve`；off→`retrieval_not_configured`；不可达→`cannot reach ...`。三种 reason 互异，findings 如实留痕 |

## 4. L3 评测结果（任务 2.4 / 8.1–8.6 / 9.5）

| 任务 | 指标 | 明细文件 |
|---|---|---|
| 2.4 + 8.1 + 8.2 | **Recall@5 = 0.817 ｜ MRR = 0.817**（20 题文档级 gold，18/20 命中；2 个未命中均为「中文问美国法」跨语言路由弱） | `eval/retrieval_report.md` |
| 8.5 拒答 | **按 spec 判据 `coverage.unavailable` = 0.00（0/10，未达 0.9）**。`escalate_to_human` 10/10 **不能作为替代信号**（raw 模式下 `not filters.as_of` 恒成立，域内也 true）；仅 `coverage.notes` 如实声明了「基于正文检索/交易日期不可用」+ 零编造。判据失效原因见 §6.1 | `eval/refusal_agent3.md` |
| 8.3 + 8.4 引用 | **双口径（owner 定）**：`引用可定位率 = 1.000`（50/50，零编造可回溯）｜`主题相关率 = 0.12`（**豆包专家版**独立复核 6 supported / 1 partial / **43 unsupported**）。43 条跑题已**登记为检索质量缺口**并转告 Shawn。1.000 不再称作 `citation_support_rate` | `eval/citations_report.md` + `eval/doubao_review.md` + `eval/SHAWN_ISSUE.md` |
| 9.5 重建闭环 | **PASS**：上传→重建 8.7s→命中 TEST-001；删除→重建 8.6s→消失；服务已还原（测试文档已清，索引回 143 部基线） | `eval/rebuild_report.md` |

**真实发现（非粉饰）**：
1. 跨语言路由弱：中文问题问美国法（Q09/Q10）全部路由到中国法规——语料 73 部 US 法规对中文查询的召回失败
2. **spec 判据 8.5 与实现不匹配**：spec.md:155 要求超纲时 `coverage.unavailable=true`，但 `answer.py:122` 定义为 `unavailable = not retrieved`，而远程 BM25 对所有超纲文本仍返回 5 条无关 chunk → 实测 0/10。`escalate_to_human` 虽 10/10，但在 raw 模式下因 `not filters.as_of` 恒成立而**域内文本也 true**，不构成"识别超纲"的证据。这不是设计变更（判据与 escalate 逻辑同日 11-07 写入），而是外部检索服务换成远程 143 部后假设失效。**本次交付的硬偏离，owner 已决定保持未勾**（§6.1）
3. 服务端 answer_status 分类缺陷：answer 明确说「依据不足」仍标 partial（Q03 交通事故 / Q09 商品房）——属 Shawn 侧 mercatoria 问题，建议转告
4. 删除文档不会自动清索引，需显式 rebuild（服务行为，已写入重建脚本注释）

**接口口径澄清**：Agent 3 只接 `/retrieve`；`/v1/chat` 是远程服务自带的生成接口，不在 Agent 3 运行路径上。8.3/8.4/8.5 已全部改用 `regulatory_node()` 的真实输出重测；此前基于 chat 的两轮数据（`eval/refusal_report.md`）保留作服务侧参考，**不作验收依据**。8.1/8.2 的 Recall@5/MRR 仍为裸 `/v1/retrieve` 检索后端指标（绕过了 build_query，属 L3 检索真值的标准口径）。

### 8.6 限制声明（spec 要求主动声明）

1. **未做 rerank 对照**：本次所有检索指标均在服务端已开启 `gte-rerank-v2` 的单一配置下测得，没有「开/关 rerank」的对比实验，因此不能把 Recall@5/MRR 归因于或排除 rerank 的贡献。分项见 `eval/retrieval_report.md`
2. **`citation_check` 只做实体覆盖，未做语义蕴含**：`app/regulatory/cite_check.py` 校验的是 `chunk_id ∈ retrieved` + 关键实体（金额/日期/国别/规则号）是否出现在被引原文；它**不判断条文语义上是否真的支持结论**。本次 `引用可定位率 1.000` 正体现了这一限制，故另引入豆包专家版的主题相关性复核（0.12）作为补充
3. **样本量小**：L3 为 20 题检索 + 50 条 claim，指标置信区间较宽；本报告未做 L1 字段 F1（不属 Agent 3 范围），故 spec 提到的「F1 ±5 个点」不适用
4. **模型判定不可完全复算**：`主题相关率 0.12` 由豆包专家版判定，换模型可能不同，已按 spec「数字可追溯」记录模型名与输入材料

## 5. 待人工复核区（devin 的 ~1 小时）

| # | 项 | 怎么复核 | 预计 |
|---|---|---|---|
| 1 | **gold 标注 20 题** | 打开 `eval/gold_retrieval.json` 的 `questions` 数组（每题 gold_docs 望文生义是否对得上；注：Q12/Q13 曾有 doc_id 笔误已修正——AI 标注的真实错误例证）。该文件按 spec §L3 独立存放，改题不需改脚本 | 30 min |
| 2 | **citations 抽样 ≥10 条** | 开 `eval/citations_50.csv`，随机抽 10 条，人工判 quote 是否语义支持结论（我的判定是程序逐字匹配 + 语义初判） | 15 min |
| 3 | **代码 diff** | `git diff`（retriever.py ~10 行 + 测试） | 10 min |
| 4 | **验收勾选** | 豆包专家版复核后剩余待决：**8.4 是否勾**（缺口已登记，勾则注明）、**任务 A 第 15 题 gold 口径**（收窄则 MRR→0.792）；**8.5 保持未勾**（owner 决定）。8.3/8.4 口径已定为双口径双名字。详见 `eval/doubao_review.md` | 15 min |

## 6. 剩余未完成

### 6.1 本次明确登记的已知缺口（owner 决定：保持未勾）

**任务 8.5（拒答率）不勾选** —— 2026-11-19 owner（devin）决定选「保持未勾，作为已知缺口留给后续」。

| 事实 | 值 |
|---|---|
| spec.md:155 要求判据 | 超纲时 `legal.coverage.unavailable = true`，`refusal_rate ≥ 0.9` |
| 实测（agent3 真实输出，10 份超纲文本） | `coverage.unavailable` = **0/10**，即 0.00 |
| 根因 | `answer.py:122` 的 `unavailable = not retrieved`；远程 BM25 对超纲文本仍返回 5 条无关 chunk |
| `escalate_to_human` | 10/10，但**不能当作"识别超纲"的证据**：`node.py:365-373` 中 `not filters.get("as_of")` 在 raw 模式恒成立（推不出交易日期），10 条 notes 全是同一句「未能确定交易日期」，域内文档同样 true。是恒定副产品，不是覆盖判断 |
| 实际行为（实测探针） | **既不是拒绝回答，也不是编造**：`stage=done`、`unavailable=false`、summary 写「检索到 5 条**相关**条文」、5 条 claim 全 `supported`（问个税却返回《独立保函司法解释》条文）。零编造法规/零法律定性，但**把无关内容当相关结果照常输出**，且没有任何"主题不在语料范围"的声明。超纲与域内的结构化输出几乎无法区分（仅 `business_type_uncertain` 不同）。详见 `eval/refusal_agent3.md` |
| 是否设计变更 | **否**。spec 8.5 判据（`199de7a`, 11-07）与 escalate 6 条件（`3f1e1c8`, 11-07）同日写入，实现（`b71a563`, 11-09）一次落地。变的是**外部检索服务**（本地 20 条手写语料 → 远程 143 部 BM25），导致「超纲 → 检索为空」的假设失效 |
| 不勾的原因 | 判据与实现不匹配，**没有为了达标而改语义判断或拿别接口的数据冒充**。修它需要定义「什么叫检索结果不相关」，属于语义蕴含判断，spec 明确不在本 change 范围内（proposal.md:21），留给后续 |

三个选项当时是：① 接受现状勾掉并注明偏离；② 改 `answer.py` 引入相关性判断；③ 保持未勾作为已知缺口。owner 选 ③。

**修复方向更正（此前建议作废）**：原建议「检索命中但所有 claim 均 `insufficient` 时置 `unavailable=true`」经 6 组实测**永不触发**——超纲与域内的 claims 全部 `supported`，且超纲 top1 分数也是 1.0、低分阈值同样分不开。剩余可行路径：① Shawn 服务端加相关性重排/阈值（见 `eval/SHAWN_ISSUE.md`）；② 本仓库新 change 引入语义蕴含判断（`proposal.md:21` 明确排除）；③ 改 `build_query` 主题约束（BM25 兜底未必有效）。
**边界**：不能改评测脚本把 `escalate=true` 算成拒答（等于改考卷迁就答案，且域内也 true）；不能改 spec 冻结判据（需 openspec 变更 + owner 签字）；产品代码可以改，但属新 change。详见 `eval/refusal_agent3.md`。

### 6.2 非本次范围

- 1.2/1.3 语料内容：等 A（bank_policy）/ B（conventions，URDG 758/UCP 600）提供 → 需 Shawn 加入远程 corpus 后 rebuild
- 1.4 sanctions.mock.md：未做（需决策：进远程 corpus 或本地 fixture）
- 2.4 的 20 题命中明细人工过目（P4a 输出已就绪）
