# Spec 覆盖测试设计（2026-11-10）

> 范围：`openspec/` 中已冻结/已实现的规格；**跳过 Agent 2（`agent-verify`）**，因为该 change 尚未完成。
> 目标：把每条可判定规格落成可执行断言（前端 + 后端 + HTTP + 浏览器），并把当前实现与规格不一致处
> 以可复现测试固定下来；缺陷修复后转为普通回归测试。

## 1. 规格来源与边界

| Change / capability | 规格文件 | 本次处理 |
|---|---|---|
| `poc-skeleton` / `agent-contract` | `openspec/changes/poc-skeleton/specs/agent-contract/spec.md` | 覆盖共享层纯函数、定位基准、接缝字段、留痕 |
| `poc-skeleton` / `orchestration` | `openspec/changes/poc-skeleton/specs/orchestration/spec.md` | 覆盖主图顺序、状态写权、阶段独立触发、闸门/导出/幂等 |
| `agent-normalize` / `normalization` | `openspec/changes/agent-normalize/specs/normalization/spec.md` | 覆盖 parse/extract/normalize、三分类、跨页、业务类型、必填占位 |
| `agent-regulatory` / `regulatory-advice` | `openspec/changes/agent-regulatory/specs/regulatory-advice/spec.md` | 覆盖检索、raw/enriched、引用降级、覆盖声明、时效、转人工 |
| `agent-audit` / `rule-audit` | `openspec/changes/agent-audit/specs/rule-audit/spec.md` | 覆盖快照、计划守恒、六态、Finding、逐操作闸门、模板/规则冲突 |
| `rich-text-editing`（archive） | `openspec/changes/archive/2026-11-09-rich-text-editor/specs/rich-text-editing/spec.md` | 覆盖格式、表格、撤销重做、查找替换、投影确定性 |
| `document-editor`（archive） | `openspec/changes/archive/2026-11-09-editor-shell/specs/document-editor/spec.md` | 覆盖三栏/窄屏、按键可达、状态文字、未实现能力标注 |
| `frontend-console` / `console-api` | `openspec/changes/frontend-console/specs/console-api/spec.md` | 通过现有 `tests/test_api.py` + 新增边界用例覆盖错误封套 |
| `document-import` | `openspec/changes/document-import/specs/document-import/spec.md` | 覆盖上传、逐文件错误、同名文件、大小限制 |
| `agent-verify` / `business-verification`、`eval-benchmark` | 同目录 | **不新增**；现有 Agent2 用例保留但不在本次结论内 |

排除理由：`agent-verify` 的实现尚未冻结，按当前行为写断言会把未完成状态固化成“规格”；本报告只在
`gate`/`pipeline_gate` 的跨 Agent 契约处引用其阶段名（`agent2`），不评价其内部逻辑。

## 2. 测试分层与运行方式

| 层 | 技术 | 关注点 | 命令 |
|---|---|---|---|
| L0 纯函数 | pytest | normalize_ws、规则 DSL、report 汇总、gate 决策 | `.venv/Scripts/python.exe -m pytest -q` |
| L1 节点/图 | pytest | StageReport、trail、状态覆盖、幂等、重跑 | 同上 |
| L2 HTTP | FastAPI TestClient | 封套、错误码、上传、并发/锁、digest | 同上 |
| L3 前端单元/组件 | Vitest + Testing Library | 投影、状态机、错误文案、可访问性 DOM | `npm --prefix web run test` |
| L4 浏览器 E2E | Playwright | 真实 TipTap、上传、审计、gate、法规、版本、键盘 | `npm --prefix web run e2e` |
| L5 真实模型冒烟 | OpenAI-compatible HTTP | 仅验证接线与引用降级，不纳入回归 | `SMART_EDIT_LIVE_LLM=1 ... pytest tests/test_live_llm_optional.py` |

环境：Windows 10 / Python 3.11 / Node 22 / Chromium（Chrome channel）。
E2E 默认起 `uvicorn :8000`（fixture）、`:8010`（无 provider）与 Vite `:5173/:5174`；
本机 8000 被 RAGFlow 占用，因此执行时用**临时** `web/playwright.local.config.ts` 把端口改为
`8200/8210/5273/5274`，该临时文件不进入交付。

## 3. 覆盖矩阵（规格 → 测试）

### 3.1 Agent 1 / 共享层

| 规格点 | 新增/代表测试 | 结果 |
|---|---|---|
| 五步 `normalize_ws` 顺序 + 不折叠大小写/不去标点 | `test_spec_coverage::test_normalize_ws_applies_the_five_steps_in_order_and_nothing_else` | ✅ |
| `MAX_SPAN_LEN` 200/201 边界、超长切句、超长不截断 provenance | `test_spec_coverage::test_max_span_len_is_a_boundary_not_a_target`、`test_an_overlong_span_is_cut...` | ✅ |
| 日期 `date_order` / 两位年份 | `test_date_order_and_two_digit_year_are_applied[...]` | ✅ |
| 金额 K/M/MN/BN/B 与 Decimal 精度 | `test_amount_multipliers_and_exact_decimal_arithmetic[...]` | ✅ |
| 币种大小写、非法币种降级 | `test_lowercase_currency_is_uppercased...` | ✅ |
| 重复候选：高置信度胜出且落 `pass` 留痕 | `test_higher_confidence_duplicate_wins...` | ✅ |
| 纯文本解析保留 NBSP/全角空格、无 page/bbox | `test_plain_text_parse_keeps_visible_whitespace_and_has_no_position` | ✅ |
| 全部文件失败 → `failed`、不伪装成功 | `test_all_files_failing_makes_parse_a_failed_stage...` | ✅ |
| 抽取 schema 违规重试一次 → `partial` | `test_extract_retries_once_then_reports_a_partial_stage` | ✅ |
| 候选 `label` 保留；`source.page` 回填 | `test_a_candidate_label_is_preserved...`、`test_a_single_block_pdf_field_keeps_the_extracted_page` | ✅ |
| 业务类型 evidence/reason 留痕 | `test_business_type_decision_always_writes_one_receipt...` | ✅ |
| DOCX 表格单元格段落边界 | `BUG-N7` | ✅ |
| 扫描 PDF 的 OCR 来源标记 | `BUG-I1` | ✅ |
| 嵌套 DOCX 表格不重复读取 | `BUG-N8` | ✅ |
| 跨页误判、同页多块 page=null、模糊金额、全角业务类型、非有限金额 | `test_spec_bugs` 中 `BUG-N1…N6` | ✅ |

### 3.2 Agent 3 / 法规

| 规格点 | 新增/代表测试 | 结果 |
|---|---|---|
| `retrieved` 四项形状 | `test_retrieved_chunks_have_the_contract_shape_and_ids` | ✅ |
| `applicable_rules` 生效日 / 版本 | `test_applicable_rules_keep_the_chunk_effective_date` | ✅ |
| coverage.standards 来自实际检索 | `test_coverage_declares_the_standards_seen_in_retrieval` | ✅ |
| 不支持法域 → note + escalate + REG-JURISDICTION | `test_an_unsupported_jurisdiction_is_named_and_escalates` | ✅ |
| 有命中但无 claim → escalate + note | `test_retrieval_without_claims_requires_a_human_and_says_so` | ✅ |
| 每条 Finding 带“不替代正式筛查”声明 | `test_every_regulatory_finding_carries_the_screening_disclaimer` | ✅ |
| raw 命中 mock 名单 | `BUG-R1` | ✅ |
| raw Finding evidence 指向正文 | `BUG-R2` | ✅ |
| LLM summary/claim 禁止法律定性 | `BUG-R3` | ✅ |
| 干净结果也需筛查声明 | `BUG-R4` | ✅ |
| cite_check 大小写/全角/留痕 after | `BUG-R5/R6/R7` | ✅ |

### 3.3 Agent 4 / 审计 + 编排

| 规格点 | 新增/代表测试 | 结果 |
|---|---|---|
| 语义 hard_block 不阻断、其他操作 hard_block 不阻断 | `test_severity_or_another_operation_never_blocks_by_itself` | ✅ |
| 确定性 hard_block 对目标操作阻断 | `test_a_deterministic_hard_block_for_this_operation_blocks` | ✅ |
| `mark_stale` 派生视图、不修改原报告 | `test_mark_stale_returns_a_copy_and_is_idempotent` | ✅ |
| verdict 失败优先 / unable 一律 fail | `test_verdict_fail_wins_and_unable_always_fails` | ✅ |
| credibility = pass+finding / planned | `test_credibility_excludes_not_applicable_from_the_numerator` | ✅ |
| 全部 not_applicable → unable + `no_applicable_checks` | `test_everything_not_applicable_is_unable_and_never_pass` | ✅ |
| 导出文件字段齐全、version_no 不接受调用方值 | `test_the_export_file_has_every_required_key_and_ignores_a_caller_version` | ✅ |
| 拦截时不导出、stage=skipped | `test_a_blocked_gate_writes_no_export_and_marks_the_stage_skipped` | ✅ |
| 计划守恒/重复 result/崩溃隔离/确认字段/NaN/旧报告/旧 gate/旧 finding | `BUG-A1…A10` | ✅ |
| stale 报告上的 save_draft、ID 重用 disposition、citation/coverage evidence | `BUG-A14…A17` | ✅ |
| 所有文件失败后 extract/normalize 仍 done、latest failed 未回填 | `BUG-O1/O2` | ✅ |
| 模板变更 staleness | `test_gate_detects_a_template_edited_after_the_audit`（gate_node 读取当前发布包摘要） | ✅ |

### 3.4 HTTP / 上传 / 前端

| 规格点 | 新增/代表测试 | 结果 |
|---|---|---|
| 非对象 JSON → `EMPTY_SUBMISSION` | `test_a_json_scalar_submission_is_an_empty_submission_not_a_run` | ✅ |
| gate 非法 JSON → 400 `INVALID_BODY` | `test_malformed_json_on_the_gate_is_a_400_invalid_body` | ✅ |
| 上传路径不可逃逸 | `test_an_upload_filename_cannot_escape_the_run_directory` | ✅ |
| 不支持 MIME / >20MiB 逐文件错误 | `test_an_unsupported_upload_is_reported_per_file...`、`test_an_oversized_upload_is_refused_by_the_parser...` | ✅ |
| events 键存在、空列表 | `test_events_endpoint_is_oldest_first_and_empty_before_a_graph_run` | ✅ |
| 相同文本创建两个独立 run | `test_two_runs_are_independent_even_when_created_from_identical_text` | ✅ |
| 创建 run 的畸形 JSON → 400 | `BUG-API1` | ✅ |
| 传输层 422/400 也必须用错误封套 | `BUG-API3` | ✅ |
| disposition actor/reason 类型校验 | `BUG-API4` | ✅ |
| 非字符串 text 拒绝而非强转 | `BUG-API5` | ✅ |
| 同名文件不互相覆盖 | `BUG-API2` | ✅ |
| rich 投影插入空格 | `BUG-F1`（Vitest `it.fails`） | ✅ |
| Formatting 仍标“未实现” | `BUG-F2` | ✅ |
| 宽屏 pane 数组缺 React key | `BUG-F3`（独立文件避免 warning 去重） | ✅ |
| 损坏 localStorage 条目 | `BUG-F4` | ✅ |
| 表格 before/left 与表头切换 | `BUG-F5`（Vitest `it.fails`） | ✅ |
| 真实浏览器：三栏/窄屏、格式化、表格、查找替换、审计、gate、版本、键盘 | `web/e2e/*.spec.ts` | ✅ |

## 4. 新增用例目录

| 文件 | 数量 | 用途 |
|---|---|---|
| `tests/test_spec_coverage.py` | 46 | 正向规格断言（应保持全绿） |
| `tests/test_spec_bugs.py` | 49（参数化后 49 个节点） | 已修复缺陷的普通回归测试 |
| `web/src/App.keyWarning.test.tsx` | 1 | 独立文件抓 React key warning |
| `web/src/rich/plainText.test.ts` | +1 | 相邻 run 投影 |
| `web/src/components/RichEditor.test.tsx` | +4 | H1/H3、表格六向操作、字面查找、空文档 |
| `web/src/components/DocumentActions.test.tsx` | +1 | Formatting 可用性 |
| `web/src/versionStore.test.ts` | +1 | 损坏存储条目 |
| `web/e2e/rich-editor.spec.ts` | 3 | 真实 TipTap 格式/表格/查找替换 + 审计入参 |
| `web/e2e/gate.spec.ts` | 2 | gate 决策；stale gate 反例 |
| `web/e2e/accessibility.spec.ts` | 2 | 键盘可达/焦点可见、状态文字 |
| `web/e2e/version.spec.ts` | 1 | 捕获/编辑/恢复/清空 |
| `web/e2e/legal.spec.ts` | 1 | 无审计时直接运行 Agent3 并显示覆盖/失败 |
| `tests/test_live_llm_optional.py` | 1（默认 skip） | magpie 真实模型冒烟 |

## 5. 判定标准

- 正向测试与缺陷回归全部为普通测试，必须全绿；不再使用 `xfail` / `it.fails` / `test.fail`。
- 修复缺陷时同步删除对应 marker，并把复现转成回归测试；行为回退必须直接失败。
- Agent2 完成后，另起 `agent-verify` 规格矩阵；本设计中的 `agent2` 仅作为阶段名出现。

## 6. 真实模型冒烟（可选，非回归）

按任务要求使用当前 magpie provider：

```text
base:  http://localhost:3425/v1
model: my-local-2k/deepseek-v4.1-flash-1017
```

以本地法规 chunk + `LLMAnswerer(OpenAIChat(...))` 跑一次 `regulatory_node`：
`stage=done`、`model_calls=1`、2 条 claim 均 `support=supported`、citation 均来自本次 retrieved，
summary 未出现“合规/不合规/可做/不可做”。该冒烟用于验证接线与引用降级，不进入 CI。
