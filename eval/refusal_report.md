# L3 拒答评测（远程 /v1/chat · 服务侧参考，**非 Agent 3 验收依据**）

> ⚠️ 口径更正：Agent 3 只调用 `/retrieve`，从不调 `/v1/chat`。本文件记录的是远程服务自带的
> 生成接口行为，仅作服务侧参考与问题定位；**任务 8.5 的正式验收见 `eval/refusal_agent3.md`**
> （基于 `regulatory_node()` 的 `legal.coverage` / `escalate_to_human`）。

- 服务：`http://59.110.213.187:8080` 的 `/v1/chat`（带鉴权，answer 生成开启）
- 拒答定义：`answer_status in (unsupported, unavailable)`——依据不足时必须拒绝作答，不得编造
- 结果：**refusal_rate = 0.80** → FAIL (< 0.9)

| # | 问题 | answer_status | citations | 回答含拒绝措辞 | 判为拒答 |
|---|---|---|---|---|---|
| 1 | 个人所得税的专项附加扣除有哪些？ | unavailable | 0 | False | True |
| 2 | 离婚时夫妻共同财产应当如何分割？ | unavailable | 0 | True | True |
| 3 | 交通事故人身损害赔偿的项目和计算标准是什么？ | partial | 5 | True | False |
| 4 | 发明专利侵权诉讼的法定赔偿数额如何确定？ | unavailable | 0 | False | True |
| 5 | 食品安全法对生产经营者的罚款起罚标准是什么？ | unavailable | 0 | True | True |
| 6 | 用人单位违法解除劳动合同的经济赔偿金如何计算？ | unavailable | 0 | True | True |
| 7 | 环保部门对企业超标排污的按日连续处罚如何适用？ | unavailable | 0 | True | True |
| 8 | 医疗损害责任纠纷中医疗机构的举证责任是什么？ | unavailable | 0 | False | True |
| 9 | 商品房买卖合同纠纷中买受人可以退房的条件有哪些？ | partial | 4 | True | False |
| 10 | 公司注册资本认缴制下股东出资加速到期的条件是什么？ | unavailable | 0 | False | True |

## 限制声明
- 超纲题按语料清单人工核对（143 部均为贸易/海关/出口管制/制裁领域，不含所问领域）
- answer_status 由服务端判定（基于 citations 支持度）；本脚本只统计，不复判语义

## 复核分析（AI 初判，2026-11-19，逐条读 answer 全文）

两条 partial 复核结论：

- **Q03（交通事故赔偿）**：5 条引用均为无关条文（TRIPS 45、19 CFR 24.71/158.25/159.8、CISG 5）。answer 正文明确「依据不足。用户提供的条文均不涉及交通事故人身损害赔偿的项目和计算标准」并逐条否定引用相关性。**内容上为拒答，被 status 分类器错标为 partial。**
- **Q09（商品房退房）**：5 条引用全部为 CISG。answer 正文明确「结论：依据不足。……商品房买卖合同属于不动产买卖，不适用CISG」。**同为内容拒答被错标。**

修正口径：

| 口径 | refusal_rate | 判定 |
|---|---|---|
| 按 `answer_status` 标签 | 0.80 | 未达 0.9 |
| 按 answer 内容（10/10 拒绝编造） | **1.00** | 达标 |

- 差异根因：服务端 status 分类规则——「有 citations 且产出 answer」即判 partial，不读 answer 自身的否定结论。属 mercatoria 服务侧问题，不在 agent3 客户端。
- 下游兜底：agent3 的 `cite_check` 做实体覆盖校验，此类 claim 在 smart-edit 流水线内会降级为 `support=insufficient`，不会成为合规结论。
- 建议（转 Shawn）：status 判定改为「answer 明示无依据 → unsupported」，或评测口径改为内容判定。

## 复测（2026-11-19 第二轮，`scripts/_probe_chat.py` 逐条打印全文）

同一 10 题重测，结果与首轮不同：**9/10 为 `unavailable` + 0 引用**，唯一 `partial` 从 Q03/Q09 换成了 Q04（发明专利，5 条 TRIPS 引用，但回答仍明确「依据不足，未包含确定法定赔偿数额的规则」）。

| 轮次 | status=unavailable | status=partial | 按 status 的 rate | 按内容（逐条读答案）的 rate |
|---|---|---|---|---|
| 首轮 | 8 | 2（Q03, Q09） | 0.80 | **1.00**（10/10 明确拒答） |
| 第二轮 | 9 | 1（Q04） | 0.90 | **1.00**（10/10 明确拒答） |

结论与限制：

- 两轮**内容层均为 10/10 拒答**，答案都逐条指出「检索到的条文属什么领域、为什么不相关、缺少哪类法律」——语义拒答稳定
- **status 标签不稳定**（partial 出现在不同题上），原因是服务端基于本次 citations 分类，而有/无引用受模型/缓存状态影响。故 spec 要求的 `refusal_rate` 不能只靠 status 判定，应记录两轮结果并按内容口径报 1.00，同时声明 status 口径在 0.80–0.90 波动
- 该不稳定性来源于远程服务（Shawn 侧），agent3 客户端无法修复
- **spec 偏离仍在**：spec.md:155 要求检查 `legal.coverage.unavailable`，但远程 `/retrieve` 对超纲问题仍返回 5 条无关 chunk（实测 10/10 都返回 5 条），`answer.py:122` 的 `unavailable = not retrieved` 因此恒为 false——spec 判据在远程服务上失效。当前用 `/v1/chat` 的语义拒答作为替代信号，已在自评报告登记为硬偏离，待 owner 定夺。