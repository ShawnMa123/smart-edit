# Design

## 1. 最小垂直链路（L1）

同步 + 内存：`POST /legal/reviews` 直接跑完两种模式、写 `_REPORTS` 字典、返回 202 + `Location`；`GET /legal/reports/{id}` 读回报告。异步 Worker 与 PG 持久化属 L2，不做。

## 2. 确定性规则

受限 DSL 目前只实现 `exists` / `compare`（三值逻辑：True/False/None）。一条合成规则 `DEMO-AMOUNT-REQUIRED`：`exists(amount)`，金额缺失→`Critical`/`hard_block` finding、确认→pass、未确认→`unable_to_assess`。缺失字段是 unknown，**绝不**当 pass。

## 3. 法规复用 `/v1/chat` 的映射

`modes=["legal"]` 时复用 `StatuteRetriever.chat_detailed()`，不重新实现检索：

| `StatuteOutcome` | 映射到 |
|---|---|
| `draft` | `Finding.explanation` |
| `candidates` | `Finding.evidence_ids`（citation_id）+ `Finding.anchors`（chunk_id/doc_id/条文号/法域/生效日/摘录） |
| `answer_status` | `Finding.support_level`（answered→strong、partial→qualified、unavailable/unsupported/error→insufficient） |
| `coverage` | `CheckResult.reason_codes`（`coverage:*` 覆盖说明） |

## 4. 范围/相关性判定：信任服务 `answer_status`，不用本地 `analyze()`

实测 `analyze()` 会把「从中国进口美国牛肉…法规」这类语料能部分回答的问题误判 `out_of_scope`，是错误的闸门。改为：

- `answered` / `partial` → 产出 Finding（草稿 + 引用）。
- `unavailable` / `unsupported` / `error` / 零引用 → `unable_to_assess`，且**绝不把服务返回的无关联 references 当引用展示**（否则离题问题会硬凑出「法规答案」）。

## 5. 四条诚实性不变量

1. **没检查≠没问题**：传输失败/超时/无引用/`unavailable` → `unable_to_assess` 或 `needs_input`，绝不 `no_findings`。
2. **引用可追溯**：正常返回时 `evidence_ids` 非空、`anchors` 不丢 `chunk_id`。
3. **失败可区分**：timeout / uncovered / no-hit / out-of-scope 各自独立 `reason_codes`。
4. **answer_status 闸门**：见第 4 节。

## 6. 边界（不假装做完）

异步 Worker、PG 持久化、规则包治理、人工复核、语义审计、完整 DSL（`all/any/not/length/charset/contains_clause`）均为 L2~L5，本 change 不含。
