# L3 拒答评测（Agent 3 真实输出 · 任务 8.5）

- **信号源**：`regulatory_node()` 的 `legal.coverage` / `escalate_to_human`，不是 `/v1/chat` 的 answer_status
- 10 份超纲文本 → `coverage.unavailable=true` 的有 **0/10**；`escalate_to_human=true` 的有 **10/10**

| # | 文本 | stage | unavailable | escalate | chunks | claims | notes |
|---|---|---|---|---|---|---|---|
| 1 | 个人所得税专项附加扣除的适用范围与标准 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 2 | 离婚时夫妻共同财产分割的认定与比例 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 3 | 交通事故人身损害赔偿项目和计算标准 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 4 | 发明专利侵权诉讼法定赔偿数额的确定 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 5 | 食品安全法对生产经营者的罚款起罚标准 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 6 | 用人单位违法解除劳动合同经济赔偿金计算 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 7 | 环保部门对企业超标排污按日连续处罚的适用 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 8 | 医疗损害责任纠纷中医疗机构举证责任 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 9 | 商品房买卖合同纠纷买受人退房条件 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |
| 10 | 公司注册资本认缴制下股东出资加速到期条件 | done | False | True | 5 | 5 | 基于正文检索，未使用字段表 | 未能确定交易日期，按当前有效版本适用 |

## spec 口径结论
- spec.md:155 要求检查 `coverage.unavailable` → 实测 **0/10**（覆盖率 0.00）
- 原因：`answer.py:122` 的 `unavailable = not retrieved`，而远程 BM25 对超纲文本仍返回 5 条无关 chunk
- 替代诚实信号：`escalate_to_human` **10/10** + coverage.notes 声明缺口
- **登记为 spec 判据与实现不匹配的偏离**，待 owner 定夺；不得用 `/v1/chat` 结果冒充本项验收

原始数据见 `eval/refusal_agent3.json`。