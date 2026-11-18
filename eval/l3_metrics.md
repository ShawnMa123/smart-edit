# L3 指标（由 `eval/run_eval.py` 生成，勿手改）

| 指标 | 值 | 来源 |
|---|---|---|
| Recall@5（文档级 gold） | 0.817 | `eval/retrieval_raw.json`，20 题 |
| MRR | 0.817 | 同上 |
| 题目命中数 | 18/20 | 同上 |
| 引用可定位率 | 50/50 = 1.000 | `eval/citations_50.csv` |
| 主题相关率 | 6/50 = 0.120 | 豆包专家版独立复核，`eval/doubao_review.md`（模型判定，非本脚本生成） |
| 拒答（spec 判据 `coverage.unavailable`） | 0/10 = 0.000 | `eval/refusal_agent3.json` |

范围：仅 L3。L1/L2/L5 由其他 change 负责，未在此运行。
重建闭环（9.5）会改动远程服务状态，须单独执行 `scripts/rag_eval_rebuild_loop.py`。