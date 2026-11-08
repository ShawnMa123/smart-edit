# Tasks: POC 骨架与契约冻结

> **Owner：待认领** —— 这是本 change 的头号阻塞项。§0 未完成前，A/B/C 不应开工写依赖契约的代码。
> 全员 review · 交接物：`app/state.py` + `app/findings.py` + `fixtures/seam_*` 四对快照
> 依据：`design.md`（裁决与不变量）· `specs/orchestration/spec.md` · `specs/agent-contract/spec.md`

> **三条第一优先**：契约（§2）、共享层（§3）、阶段状态与留痕（§4）。
> 这三块未冻结前，A/B/C 无法真正并行；冻结后，本 change 剩余部分可与三个 Agent 并行推进。

## 0. 认领与冻结动作

- [ ] 0.1 指定 owner 并写进 `README.md` 的对照表（当前为"待定"）
- [ ] 0.2 owner 通读 `design.md` 全文 + 《编排层实施设计》§2.3 / §3 / §4 / §5
- [ ] 0.3 组织一次 30 min 契约评审，逐条过 `design.md` §5 的裁决表，结论不回 PR、只回文件
- [ ] 0.4 D1 冻结时通知 A/B/C，并给出 `fixtures/seam_*` 四对快照的 owner 分工
- [ ] 0.5 建 `code review checklist`：任何模型调用前是否已有副作用、是否新增无 reducer 的并行写入键

## 1. 工程初始化

- [ ] 1.1 `pyproject.toml` 锁 `langgraph==1.2.*`、`langgraph-checkpoint-sqlite`、`fastapi`、
      `uvicorn`、`pydantic>=2`、`pymupdf`、`pyyaml`；Python ≥ 3.11（`typing.NotRequired`）
- [ ] 1.2 目录骨架：`app/`（含 `parsing/` `nodes/` `agents/` `verifier/` `storage/` `api/`）、
      `tests/`、`eval/`、`knowledge/`、`fixtures/`、`schemas/`
- [ ] 1.3 `.env.example`：模型 provider、`OPENSPEC`/DB 路径、`TRAIL_SIGNING_KEY`（仅 POC）
- [ ] 1.4 `conftest.py`：提供最小 state 工厂（空 `EditState` + 一条 `SourceFile`）
- [ ] 1.5 确认 `Overwrite` 的导入路径与 LangGraph 版本匹配（`try/except` 双路径，PR 注明版本号）；
      **不得**自己实现同名类

## 2. 契约（第一优先 · 冻结前不得动）

- [ ] 2.1 `app/state.py`：枚举常量（§4.1），含 `OVERREACH_OPS` 与 `SHARED_STAGE_OWNER`
- [ ] 2.2 `app/state.py`：`ParsedBlock` / `ParsedDoc`（含 `sha256` 可选）/ `Source` / `SourceFile` / `Chunk`
- [ ] 2.3 `app/state.py`：`FieldValue`（三分类语义注释）与 `Finding`（含 `confidence` / `needs_review` 可选）
- [ ] 2.4 `app/state.py`：`Claim` / `ApplicableRule` / `LegalOpinion`
- [ ] 2.5 `app/state.py`：`StageReport` / `TrailEntry` / `Issue` / `VerificationReport`
- [ ] 2.6 `app/state.py`：`EditState`，仅 `findings` / `trail` / `stages` 使用 reducer；含 `_candidates`
- [ ] 2.7 每个字段写语义注释，重点：`value` 大小写、`span` 粒度、`confirmed` 含义、
      `status` 与 `Finding` 的分工、`blocking` 不由 `severity` 推导
- [ ] 2.8 `app/findings.py`：`emit_finding()`（按 `FINDING_PREFIX` 自增编号）+ 同时写 `emit` 留痕
- [ ] 2.9 `app/findings.py`：前缀与 `source` 不匹配时抛错（`merge` 与单测都依赖这条校验）
- [ ] 2.10 `tests/test_contracts.py`：断言必填键、枚举值、`field_keys` 为空列表而非 `None`、
      `_candidates` 不在契约必需键内
- [ ] 2.11 `schemas/*.json`：三个 Agent 输出 JSON Schema，可直接用于 `with_structured_output`
- [ ] 2.12 `fixtures/`：四对「输入 state 快照 + 断言」——`seam_a_to_b`、`seam_a_to_c`、
      `seam_ac_to_d`、`seam_bd_to_gate`，断言写成 pytest，不写金文件
- [ ] 2.13 `design.md` §5 裁决表逐条落实为代码或注释（十处不一致不得留白）
- [ ] 2.14 **三人过一遍签字的接缝清单**（A→B、A→C、全体→D、B/闸门、D/闸门），每条一句话

## 3. 共享层（第一优先 · 纯函数）

- [ ] 3.1 `app/parsing/normalize.py`：先落 `normalize_ws`（NFKC → 零宽剔除 → 连字符 → 引号 → 空白折叠）
      与 `MAX_SPAN_LEN = 200`；**这是全层唯一基准，A 与 C 都在 import 它**
- [ ] 3.2 `app/parsing/normalize.py`：`locate_span(full_text, span)` 辅助函数，判定"能否定位"只走它
- [ ] 3.3 `app/parsing/parse.py`：文本型 PDF → `ParsedDoc`（`pymupdf`，保留 page/bbox/sha256）
- [ ] 3.4 `app/parsing/parse.py`：邮件 / 粘贴文本 → `ParsedDoc`（无位置信息）
- [ ] 3.5 `app/parsing/parse.py`：单文件失败不抛异常，写 `ParsedDoc.errors` + `StageReport(partial/failed)`
- [ ] 3.6 `app/parsing/parse.py`：扫描件（无文本层）→ 明确错误，不得返回空字符串
- [ ] 3.7 `app/parsing/extract.py`：唯一 LLM 入口，`with_structured_output` 输出候选 + span，
      返回 `ExtractResult(candidates, trail_entries, model_calls, failed_batches)`
- [ ] 3.8 `app/parsing/extract.py`：不合 schema 重试一次；重试耗尽写 `StageReport(failed)`
- [ ] 3.9 `app/parsing/normalize.py`：`build_fields()` 纯函数 → 三分类 + `required` 缺候选补 `missing` 占位
      + `extra_fields` 分流 + `detect_business_type()`
- [ ] 3.10 三个函数**均不接收 `state`、不写日志**；`tests/` 里可无图单测
- [ ] 3.11 `tests/test_parsing.py`：同一 PDF 经完整流程与独立触发两条路径，`blocks` 逐块一致
- [ ] 3.12 `tests/test_parsing.py`：`normalize_ws` 覆盖全半角 / `U+2011` / 弯引号 / 零宽字符

## 4. 阶段状态与留痕（第一优先）

- [ ] 4.1 `app/stages.py`：`AgentSpec` 数据类 + `AGENT_SPECS`（`requires_stages` / `requires_keys` /
      `produces` / `standalone` / `cleared_on_rerun`）
- [ ] 4.2 `app/stages.py`：`STAGE_TARGETS` 登记 `parse` / `extract` / `normalize` 三个**阶段目标**
      （它们不是 Agent，但必须能作为独立触发目标，否则 API 只能 409）
- [ ] 4.3 `app/stages.py`：`stage_report()` 校验 `status` 合法 + 非 `done` 必须给 `reason`
- [ ] 4.4 `app/stages.py`：`latest_stage()` / `stage_is_done()` / `stages_done()` —— 一律取**最后一条**
- [ ] 4.5 `app/stages.py`：`require()` 与 `refusal()`，拒绝格式统一为
      `{"refused": true, "missing": [...], "agent": "...", "reason": "..."}`
- [ ] 4.6 `app/stages.py`：`resolve_input_mode()` —— 跑过 `normalize` 才是 `enriched`，
      禁止用 `legal is None` 推断
- [ ] 4.7 `app/trail.py`：`record()`（节点用）与 `record_many()`（共享层回执用），
      `id = f"{agent}.{stage}#{n:03d}"`，`n` 在该 agent 内自增
- [ ] 4.8 `app/trail.py`：`op` 只能取 `TRAIL_OPS`；`OVERREACH_OPS` 单独导出供 Agent 4 判定
- [ ] 4.9 `tests/test_stages.py`：`done+produced=0` 与 `skipped+produced=0` 必须可区分
- [ ] 4.10 `tests/test_stages.py`：前置缺失返回拒绝结构，且**不返回空 findings**
- [ ] 4.11 `tests/test_stages.py`：重跑后同名阶段两条记录，`latest_stage` 取后者
- [ ] 4.12 `tests/test_trail.py`：越界 op 可被检出；日志 ID 跨 Agent 不冲突

## 5. 确定性节点

- [ ] 5.1 `ingest`：文件列表或粘贴文本 → `run_id` / `file_id` / `sha256`，`business_type` 只透传
- [ ] 5.2 `parse` 节点（薄包装）：调纯函数、`record_many` 写回、写阶段报告；
      **文件未变化时复用已有 `docs`**（按 `sha256`），不重复解析
- [ ] 5.3 `extract` 节点：写 `_candidates` 与 `trail`，**不写 `fields`**
- [ ] 5.4 `normalize` 节点：调 `build_fields`，写 `fields` / `extra_fields` / `business_type` /
      `findings(N-)`，并用 `Overwrite([])` **清空 `_candidates`**
- [ ] 5.5 `reset`：`findings` 用 `Overwrite([])`；`legal` / `retrieved` / `verification` / `gate` /
      `export` 用**普通赋值**置空（它们是 LastValue 通道）；`stages` / `trail` 不动
- [ ] 5.6 `reset`：写一条 `StageReport(done, produced=0)`，回放时能看出"第 N 轮从哪里重来"
- [ ] 5.7 `merge`：按 `(source, rule_id, sorted(field_keys), evidence)` 去重，按
      `severity → blocking → id` 排序，`Overwrite` 写回，**不重新编号**
- [ ] 5.8 `merge`：发现 `id` 前缀与 `source` 不匹配时抛错（不是静默放过）
- [ ] 5.9 `gate`：六条判定按固定顺序全部收集（不短路）：`VERIFICATION_MISSING` /
      `VERIFICATION_FAIL` → `BLOCKING_UNRESOLVED` → `INFERRED_UNCONFIRMED` → `STAGE_NOT_DONE`
      → `LEGAL_ESCALATED` / `COVERAGE_UNAVAILABLE`
- [ ] 5.10 `gate`：`required_stages = ingest/parse/extract/normalize/agent2/agent3/agent4`（`merge` 不参与）；
      `score` 只放进 `gate_out` 展示，**不参与判定**
- [ ] 5.11 `gate`：任何"无法判定"（缺 `verification`、结构异常）一律 `blocked`
- [ ] 5.12 `export`：仅在 `gate.verdict == "pass"` 时产出标准文件（含 `doc_id` / `snapshot_id` /
      `run_id` / `business_type` / `fields` / `verification` / `gate` / `exported_at` / `version_no`）
- [ ] 5.13 `export`：双保险 —— 即使路由写错走到这里，`blocked` 时只返回拦截原因并写
      `StageReport(skipped)`
- [ ] 5.14 `app/storage/doc_versions.py`：`write_version()` 写入不可变版本，版本号库内自增，
      调用方不可指定
- [ ] 5.15 `tests/test_gate.py`：六条判定各自的阻断用例 + `gate=list` 全量原因（不短路）
- [ ] 5.16 `tests/test_gate.py`：`verification.score` 极低但检查全过 → `pass`（分数不参与）

## 6. 人工核对与受控重跑

- [ ] 6.1 `hitl`：`interrupt()` payload 含「字段表（含 `status` / `source`）+ findings（按 severity）+ 三方结论摘要」；
      字段表必须能让用户看出哪些是 `inferred` 未确认
- [ ] 6.2 `hitl`：resume 后合并用户修改，置 `recheck` / `recheck_count`，标记 `confirmed` / `edited_by_user`，
      并对被改字段写一条 `op="transform"` 的留痕
- [ ] 6.3 `hitl`：`interrupt()` **之前不得**有任何模型调用或写库（code review 第一条）
- [ ] 6.4 `route_after_hitl`：`recheck and recheck_count < 3 → reset`，否则 `gate`
- [ ] 6.5 `route_after_verifier`：存在 `level="fail"` 且可修复项且 `repair_count < 1 → repair`，否则 `hitl`
- [ ] 6.6 `repair`：`FIXABLE_BY` 表决定重跑哪条分支；`UNREPAIRABLE`（输入类）**绝不重跑**，直接 `hitl`
- [ ] 6.7 `repair`：只 `Overwrite` 掉被重跑分支的结论，**保留** `verification` 作为反馈通道
- [ ] 6.8 `repair`：反馈必须含 `location` 与 `expect`，**绝不只传分数**；`repair_count` 自增，
      超预算降级 `hitl`
- [ ] 6.9 `tests/test_repair.py`：分数低不触发重跑；输入类失败不重跑；预算耗尽转人工

## 7. 占位 subgraph（D1 交付物）

- [ ] 7.1 `agents/normalize/graph.py`：返回固定 `fields` + `extra_fields` + `business_type` +
      `StageReport(done)` + 至少一条 `emit` 留痕
- [ ] 7.2 `agents/verify/graph.py`：返回固定 `findings`（`B-` 前缀，`blocking` 由规则声明）+
      `StageReport(done)` + 留痕
- [ ] 7.3 `agents/regulatory/graph.py`：返回固定 `findings`（`R-` 前缀）+ `legal` + `retrieved` +
      `StageReport(done)` + 留痕
- [ ] 7.4 三个占位节点都标 `TODO(owner)`，且**不得**调用真实模型（保证演示可离线跑）
- [ ] 7.5 `app/agents/_adapter.py`：占位与真实现共用同一签名，A/B/C 替换时只改一个 import

## 8. 主图与控制平面

- [ ] 8.1 `app/graph.py`：节点注册（`ingest parse extract normalize reset agent2 agent3 merge
      agent4 hitl repair gate export`）
- [ ] 8.2 `app/graph.py`：并行用**普通边**（`reset` 同时连 `agent2` / `agent3`），
      **不用 `Send`**；汇合用 `add_edge(["agent2","agent3"], "merge")`
- [ ] 8.3 `app/graph.py`：三条条件边 —— `agent4 → {repair|hitl}`、`repair → {agent2|agent3|hitl}`、
      `hitl → {reset|gate}`、`gate → {export|END}`；**`gate` 失败边到 `END`，不回 `hitl`**
- [ ] 8.4 `app/graph_factory.py`：`compile(checkpointer=SqliteSaver(...))`（服务重启不丢暂停会话）
- [ ] 8.5 `tests/test_graph_flow.py`：全图跑到 `interrupt` 并断言 payload 结构
- [ ] 8.6 `tests/test_resume.py`：resume 后 `parse` / `extract` 未重跑（阶段记录与模型调用数不变）
- [ ] 8.7 `app/store.py`：`RunStore`（SQLite）表结构与幂等键（`thread_id` + `resume` 序号）
- [ ] 8.8 `app/runner.py`：三个入口（新运行 / resume / 独立触发）+ 进程内锁；
      **重复 resume 不得重复写库**
- [ ] 8.9 回放：`GET /runs/{tid}/events` 能按时间顺序还原节点、阶段、留痕三视图

## 9. API 与独立触发

- [ ] 9.1 `POST /runs`：接收文件或文本，返回 `thread_id` 与首个 interrupt payload
- [ ] 9.2 `POST /runs/{tid}/resume`：`Command(resume=...)`，重复提交幂等
- [ ] 9.3 `POST /runs/{tid}/stages/{stage}`：独立触发，按 `design.md` §13 的补跑矩阵自动补前置
- [ ] 9.4 `app/standalone.py`：`plan_standalone()` 返回待执行阶段序列；
      未登记目标返回 `unknown_stage`，`agent4` 返回 `NOT_STANDALONE`
- [ ] 9.5 `app/standalone.py`：`clear_previous_outputs()` —— 只清目标负责的结论，
      否则 reducer 会叠加出重复 findings；`stages` / `trail` 不清
- [ ] 9.6 独立触发编译**线性图**（不在完整图上跳着走），避免满屏 `skipped` 噪声
- [ ] 9.7 `GET /runs/{tid}`：返回 `fields` / `findings` / `legal` / `verification` / `stages` / `trail`；
      **`stages` 必含**，否则前端无法区分"没问题"与"没检查"
- [ ] 9.8 错误码表：`REFUSED`(409) / `NOT_STANDALONE`(403) / `unknown_stage`(409) —— 前端按 `code` 分支，不看 `message`
- [ ] 9.9 `tests/test_standalone.py`：独立触发 `agent2` / `agent3(enriched|raw)` 各一条，
      断言前置补齐、`input_mode`、以及"上一轮结论被清理"

## 10. 验收与冻结

- [ ] 10.1 三人各自本地 `uvicorn app.api.main:app` 能跑通全图（含 interrupt 与 resume）
- [ ] 10.2 三个占位 subgraph 都能单独 `invoke()` 出结构正确的数据
- [ ] 10.3 `langgraph dev` 能在 Studio 里看到完整图、并行分支与 interrupt
- [ ] 10.4 四份 fixture 通过，三名成员能互相用对方的 fixture 跑自己的 Agent
- [ ] 10.5 `pytest tests/` 全绿；`test_stages.py` / `test_gate.py` / `test_graph_flow.py` 每日必绿
- [ ] 10.6 `design.md` §5 十处裁决逐条有对应代码或注释，无留白
- [ ] 10.7 **契约冻结通知 A/B/C**，并把本 change owner 写进 `README.md` 对照表
- [ ] 10.8 冻结后开一次 15 min 复盘：哪条裁决在实现时最容易被绕过，写进 code review checklist