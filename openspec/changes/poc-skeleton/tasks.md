# Tasks: POC 骨架与契约冻结

> Owner: 待定（需三人认领）· 全员 review
> 截止：团队开写各自 Agent 之前

> 三项为**第一优先**：契约（2.x）、共享层（3.x）、阶段状态（4.x）。
> 契约未冻结前，A/B/C 三人无法真正并行；契约冻结后，本 change 剩余部分可与三个 Agent 并行推进。

## 1. 工程初始化

- [ ] 1.1 建 `pyproject.toml`，锁 `langgraph==1.2.*`、`langgraph-checkpoint-sqlite`、`fastapi`、`uvicorn`、`pydantic>=2`、`pymupdf`
- [ ] 1.2 建目录骨架（`app/`、`tests/`、`eval/`、`knowledge/`、`fixtures/`、`schemas/`）
- [ ] 1.3 配置模型 provider 环境变量，写 `.env.example`
- [ ] 1.4 建 `fixtures/` 与 `schemas/`，确立"契约 = 结构 + 语义 + fixture"的交付方式

## 2. 契约（第一优先）

- [ ] 2.1 `app/state.py`：`ParsedBlock` / `ParsedDoc` / `Source` / `FieldValue`
- [ ] 2.2 `app/state.py`：`Finding` / `Claim` / `ApplicableRule` / `LegalOpinion`
- [ ] 2.3 `app/state.py`：`StageReport` / `TrailEntry` / `Issue` / `VerificationReport`
- [ ] 2.4 `app/state.py`：`EditState`，仅 `findings`/`trail`/`stages` 使用 reducer
- [ ] 2.5 每个字段写语义注释，重点标注：`value` 大小写、`span` 粒度、`confirmed` 含义、`status` 与 `Finding` 的分工
- [ ] 2.6 `tests/test_contracts.py`：断言必填键、枚举值、`Finding.field_keys` 为空列表而非 None
- [ ] 2.7 `schemas/*.json`：三个 Agent 输出 JSON Schema，可直接用于 `with_structured_output`
- [ ] 2.8 `fixtures/`：每个接缝一对「输入 state 快照 + 期望输出」，共四对
- [ ] 2.9 **三人过一遍签字的接缝清单**（A→B、A→C、B→D、C→D），每条一句话

## 3. 共享阶段（第一优先）

- [ ] 3.1 `app/parsing/parse.py`：文本型 PDF → `ParsedDoc`（用 `pymupdf`，保留 page/bbox）
- [ ] 3.2 `app/parsing/parse.py`：邮件 / 粘贴文本 → `ParsedDoc`（无位置信息）
- [ ] 3.3 `app/parsing/parse.py`：单文件失败不抛异常，写入 `ParsedDoc.errors`
- [ ] 3.4 `app/parsing/parse.py`：扫描件检测（无文本层）→ 明确错误，不得返回空字符串
- [ ] 3.5 `app/parsing/extract.py`：唯一的 LLM 抽取入口，`with_structured_output` 输出候选字段 + span
- [ ] 3.6 `app/parsing/extract.py`：输出不合 schema 重试一次
- [ ] 3.7 `app/parsing/normalize.py`：值规范化 + `fields.yaml` 映射 + 三分类判定
- [ ] 3.8 `app/parsing/`：三个函数均为纯函数，可在无图状态下单测
- [ ] 3.9 `tests/test_parsing.py`：同一 PDF 经两条调用路径，`blocks` 逐块一致

## 4. 阶段状态与操作日志（第一优先）

- [ ] 4.1 `app/stages.py`：`StageReport` 写入与查询 helper
- [ ] 4.2 `app/stages.py`：前置条件校验 —— 缺 `fields` / `business_type` 时抛结构化拒绝
- [ ] 4.3 `app/trail.py`：`record()` 签名与 ID 生成（agent 内自增，避免并行冲突）
- [ ] 4.4 `app/trail.py`：`op` 枚举含 `summarize`/`rewrite`/`drop` 三个越界值
- [ ] 4.5 `tests/test_stages.py`：`done+produced=0` 与 `skipped+produced=0` 必须可区分
- [ ] 4.6 `tests/test_stages.py`：前置缺失时返回拒绝，不返回空 findings
- [ ] 4.7 `tests/test_trail.py`：越界 op 可被检出

## 5. 确定性节点

- [ ] 5.1 `ingest`：接收文件列表或文本，生成 `run_id` / `doc_id`
- [ ] 5.2 `reset`：`Overwrite` 清空 `findings` / `legal` / `retrieved` / `verification`
- [ ] 5.3 `merge`：按 `(source, rule_id, field_keys, evidence)` 去重、按 severity 排序，`Overwrite` 写回，**不重新编号**
- [ ] 5.4 `gate`：依次判定 verdict fail / blocking 未处理 / inferred 未确认 / 必需阶段未完成 / 通过
- [ ] 5.5 `gate`：不确定时默认 `blocked`
- [ ] 5.6 `export`：产出标准文件 JSON，写 `doc_versions`

## 6. 人工核对与受控重跑

- [ ] 6.1 `hitl`：`interrupt()` 抛核对面板 payload（字段表 + findings + 三方结论）
- [ ] 6.2 `hitl`：resume 后合并用户修改，置 `recheck` / `recheck_count`，标记 `confirmed` / `edited_by_user`
- [ ] 6.3 `route_after_hitl`：`recheck and recheck_count < 3 → reset`，否则 `gate`
- [ ] 6.4 `repair_dispatch`：只接受 `level="fail"` 的 Issue；分数不触发
- [ ] 6.5 `repair_dispatch`：反馈必须含定位与期望；输入类失败不重跑
- [ ] 6.6 `repair_dispatch`：`repair_count < 1` 且总重跑 < 3，否则降级人工复核

## 7. 占位 subgraph

- [ ] 7.1 `agents/normalize/graph.py`：返回固定 `fields` + `StageReport(done)`
- [ ] 7.2 `agents/verify/graph.py`：返回固定 `findings`（`B-` 前缀）+ `StageReport(done)`
- [ ] 7.3 `agents/regulatory/graph.py`：返回固定 `findings`（`R-` 前缀）+ `legal` + `retrieved` + `StageReport(done)`
- [ ] 7.4 三个占位节点都标 `TODO(owner)`

## 8. 主图

- [ ] 8.1 `app/graph.py`：节点注册、边、`fanout`、三条条件边
- [ ] 8.2 `compile(checkpointer=SqliteSaver...)`
- [ ] 8.3 `tests/test_graph_flow.py`：全图跑到 interrupt 并断言 payload 结构
- [ ] 8.4 `tests/test_resume.py`：resume 后断言解析与抽取阶段未重跑

## 9. API 与独立触发

- [ ] 9.1 `POST /runs`：接收文件或文本，返回 `thread_id` 与首个 interrupt payload
- [ ] 9.2 `POST /runs/{tid}/resume`：`Command(resume=...)`
- [ ] 9.3 `POST /runs/{tid}/stages/{stage}`：独立触发，自动补前置阶段
- [ ] 9.4 `GET /runs/{tid}`：返回 `fields` / `findings` / `legal` / `verification` / `stages` / `trail`
- [ ] 9.5 `agent4` 单独触发返回明确拒绝
- [ ] 9.6 `tests/test_standalone.py`：独立触发 agent2/agent3 各一条，断言前置补齐与 `input_mode`

## 10. 验收

- [ ] 10.1 三人各自本地 `uvicorn app.api.main:app` 能跑通全图
- [ ] 10.2 三个占位 subgraph 都能单独 `invoke()` 出结构正确的数据
- [ ] 10.3 `langgraph dev` 能在 Studio 里看到完整图与 interrupt
- [ ] 10.4 四份 fixture 通过，三名成员能互相用对方的 fixture 跑自己的 Agent
- [ ] 10.5 **契约冻结，通知 A/B/C 可以开始**
