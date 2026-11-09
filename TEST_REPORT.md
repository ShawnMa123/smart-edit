# Spec 测试执行报告与缺陷记录（2026-11-10）

> 基线：`c07f650` + 本次测试设计新增用例。
> 口径：**只记录可复现的实现/规格不一致**；每条都在 `tests/test_spec_bugs.py`（pytest
> `xfail(strict=True)`）或前端 `it.fails` / Playwright `test.fail` 中有对应断言。
> Agent 2（`agent-verify`）未完成，未评价其内部行为；`agent2` 仅作为导出闸门的阶段名出现。

## 1. 执行结果

| 套件 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `.venv/Scripts/python.exe -m pytest -q` | **600 passed, 1 skipped, 49 xfailed**（8 条既有线程警告） |
| 前端类型 | `npm --prefix web run typecheck` | **通过** |
| 前端单元/组件 | `npm --prefix web run test` | **178 passed, 12 skipped**（其中 6 条为 `it.fails` 预期失败：F1/F2/F3/F4/F5/A13） |
| 浏览器 E2E | Playwright（本地端口 8200/8210/5273/5274） | **17 passed**，其中 1 条 `test.fail`（A13 stale gate） |
| 真实模型冒烟 | `SMART_EDIT_LIVE_LLM=1 pytest tests/test_live_llm_optional.py` | **1 passed**（magpie `my-local-2k/deepseek-v4.1-flash-1017`）：`agent3` done / 1 次模型调用 / 2 条 supported claim / 无禁止措辞；默认套件该文件 skip |

说明：本机 `:8000` 被 RAGFlow 占用，E2E 使用临时 `web/playwright.local.config.ts`；临时文件已删除。未使用 Docker：Python/Node/浏览器依赖在本机已就绪，临时构建无必要。
`web/playwright.config.ts` 已改为跨平台 `python -m uvicorn`，Windows 不再依赖 `.venv/bin/uvicorn`。

## 2. 缺陷总览

| ID | 严重度 | 结论 | 规格 | 复现测试 |
|---|---|---|---|---|
| A3 | **P0** | `/gate` 信任客户端 `candidate_digest`，编辑后重放旧 digest 仍 `allowed` | rule-audit / The candidate is what gets checked | `test_the_gate_binds_the_server_snapshot...`、`test_http_gate_rejects_a_replayed_old_candidate_digest` |
| A13 | **P0** | UI 报告已 stale 仍可 Ask gate，服务端返回 `allowed` | rule-audit / Document changes during the run | `web/e2e/gate.spec.ts`（`test.fail`） |
| A1 | **P0** | `status=inferred, confirmed=true` 仍判 `needs_input`，审批永久阻塞 | rule-audit / Present but unconfirmed + design D7 | `test_a_human_confirmed_inferred_value_passes...` |
| N1 | **P0** | 多页 PDF 中完整位于第 2 页块的值被误判跨页，降级 `inferred` | agent-normalize / 跨页拼接必须降级 | `test_a_value_contained_in_one_late_page_block...` |
| API2 | **P0** | 同名上传互相覆盖，第一份内容丢失；相同内容重传复用同一 file_id/path | document-import / 同名重传 | `test_two_uploads_with_the_same_filename_keep_both_contents`、`test_identical_content_reupload_has_an_independent_file_id_and_path` |
| A2 | **P0** | `NaN/Infinity/1e999` 金额穿过类型检查，比较时抛异常导致整次审计失败 | rule-audit / Malformed numeric input | `test_a_malformed_amount_becomes_a_unit_finding...` |
| A4 | P1 | 审计失败后旧 findings 仍留在 state，与 failed stage 并存 | rule-audit / Coverage + honesty | `test_a_failed_audit_leaves_no_old_findings...` |
| A5 | P1 | 重新审计成功后旧 gate 决策仍留在 state | rule-audit / gate answers one candidate | `test_a_new_audit_clears_the_previous_gate_decision` |
| A6 | P1 | 重新审计追加 findings（reducer），旧快照 findings 累积 | rule-audit / findings bound to snapshot | `test_a_second_audit_does_not_accumulate_old_findings` |
| A9 | P1 | 同一 run 二次导出写第二个版本，违反重复提交幂等 | orchestration / 重复提交 | `test_exporting_the_same_snapshot_twice...` |
| A10 | P1 | 人工 `accepted` 无法解除 blocking finding，导出永远 blocked | rule-audit / disposition + 未处理项 | `test_an_accepted_disposition_resolves_a_blocking_finding...` |
| N2 | P1 | 同页两个 block 中的值可标 `extracted` 但 `source.page=null` | agent-normalize / 出处必须能跳回具体页 | `test_an_extracted_pdf_value_always_has_a_page...` |
| N3 | P1 | “约 USD 500K” 被确定化为 `500000.00` | agent-normalize / 模糊表述不得被确定化 | `test_a_hedged_amount_is_inferred...` |
| N4 | P1 | 全角 `ＢＡＮＫ ＧＵＡＲＡＮＴＥＥ` 无法识别业务类型 | agent-contract / 定位基准唯一 | `test_full_width_guarantee_wording_is_detected...` |
| N7 | P1 | DOCX 表格单元格内多段落被拼成 `AlphaBeta`，丢失段落边界 | agent-normalize / 解析必须保留原文结构 | `test_docx_table_cell_keeps_paragraph_boundaries` |
| I1 | P1 | 扫描 PDF 经 OCR 后 `form` 仍是 `pdf_text`，掩盖了 OCR 来源 | document-import / OCR 的文本来源 | `test_a_scanned_pdf_that_went_through_ocr_is_labelled_image_ocr` |
| N8 | P2 | 嵌套 DOCX 表格被递归多次读取，文本重复进 blocks/full_text | document-import / DOCX 解析 | `test_a_nested_docx_table_is_not_walked_twice` |
| N5/N6 | P1 | `-Infinity/+Infinity/1e999` 崩溃；`-NaN` 成为字段值 | agent-normalize / 值规范化 | `test_a_non_finite_or_huge_amount...`、`test_nan_with_a_sign...` |
| R1 | P1 | raw 模式只用字段表命中 mock 名单，正文命中被忽略 | regulatory-advice / 疑似命中筛查名单 | `test_a_mock_sanctions_hit_in_the_body...` |
| R2 | P1 | raw 结构化 Finding 的 evidence 是生成摘要，不是正文片段 | regulatory-advice / raw 模式无字段锚点 | `test_raw_findings_evidence_is_a_body_fragment` |
| R3 | P1 | LLM 可把“合规/可做”留在 summary 或 claim 中 | regulatory-advice / 指出问题但不定性 | `test_llm_legal_conclusions_are_removed...` |
| R4 | P1 | 干净结果没有“不替代正式筛查”声明 | regulatory-advice / 不替代正式筛查 | `test_a_clean_run_still_disclaims_formal_screening` |
| A11 | P1 | 任意 `critical` Finding 都阻断；advisory / semantic / 其他操作也阻断 | rule-audit / Severity does not decide blocking | `test_severity_or_another_operation_never_blocks...` |
| API1 | P1 | `POST /runs` 畸形 JSON 抛异常（500），非 400 `INVALID_BODY` | console-api / error envelope | `test_malformed_json_on_create_run_is_a_client_error` |
| F1 | P1 | 富文本投影在相邻 text run 间强行插空格（格式改变审计文本） | rich-text-editing / 投影规则 | `plainText.test.ts` `it.fails` |
| F2 | P1 | 工具栏已有格式化，但 Header 仍标 `Formatting · not implemented` | document-editor / Actions the build can perform | `DocumentActions.test.tsx` `it.fails` |
| A7 | P2 | 同一 planned unit 的两条 result 被静默取最后一条，不报错 | rule-audit / 每个计划单元恰好一个状态 | `test_duplicate_results_for_one_planned_check_are_refused` |
| A8 | P2 | 任一 schema/rule evaluator 崩溃会导致整份报告失败，而非该单元 `failed` | rule-audit / 一个 checker 崩溃 | `test_a_crashing_rule_unit_does_not_take_the_audit_down` |
| R5 | P2 | `cite_check` 用 casefold/compact，大小写改写仍 `supported` | regulatory-advice / 有依据的结论 | `test_a_case_changed_claim_is_not_a_verbatim_fragment` |
| R6 | P2 | `cite_check` 私有归一化，全角文本被误降级 | agent-contract / 归一化基准唯一 | `test_a_full_width_claim_is_matched_by_the_shared_benchmark` |
| R7 | P2 | 降级 trail 的 `after` 仍写 `supported` | regulatory-advice / 校验失败降级不删除 | `test_a_downgrade_trail_records_the_new_support_state` |
| F3 | P2 | 宽屏 pane 数组缺 React key，控制台持续告警 | rich-text-editing / React 渲染稳定 | `App.keyWarning.test.tsx` `it.fails` |
| F4 | P2 | 浏览器存储中的 `null`/畸形条目原样进入列表，读取即抛错 | editor-shell / browser-local history | `versionStore.test.ts` `it.fails` |
| F5 | P2 | 表格仅暴露 below/right 与删除，缺 before/left 与表头切换 | rich-text-editing / 表格的增删行与列 | `RichEditor.test.tsx` `it.fails` |
| A14 | P1 | `supported` claim 无 `chunk_id` 时 `citation_support` 仍 pass | rule-audit / citation_support | `test_a_supported_claim_without_a_citation_is_a_finding` |
| A15 | P1 | 空 `coverage` 对象在检索非空时被当成覆盖声明 pass | rule-audit / coverage declaration | `test_an_empty_coverage_declaration_is_not_a_pass` |
| O1 | P1 | `plan_standalone` 把历史上曾 done 的阶段当 done，忽略后续 failed | orchestration / 阶段可独立触发 | `test_a_later_failed_stage_is_backfilled...` |
| R8 | P1 | 单条/同分候选经 `_minmax` 全变 0，随后被 InProcess 过滤为“未覆盖” | regulatory-advice / 检索命中 | `test_a_single_or_tied_candidate_keeps_a_positive_score` |
| O2 | P0 | 所有文件解析失败时，配置了 provider 仍让 extract/normalize 变 done 并写 7 个占位字段 | agent-normalize / 全部文件失败 | `test_all_files_failing_leaves_fields_empty_and_the_chain_not_done` |
| API3 | P1 | 422/400 传输层错误绕过 `{code,message}` 错误封套 | console-api / error contract | `test_transport_validation_errors_use_the_error_envelope` |
| API4 | P2 | disposition 的 actor/reason 非字符串时抛 AttributeError（500） | console-api / error contract | `test_disposition_rejects_non_string_identity_and_reason` |
| API5 | P2 | 非字符串 `text` 被 `str()` 强转（dict 变 Python repr）而非 400 | console-api / create run | `test_a_non_string_text_submission_is_rejected` |
| A16 | P2 | `save_draft` 在 stale 报告上仍返回 indeterminate，违反“草稿不受内容闸门” | rule-audit / Draft saving is not a content gate | `test_saving_a_draft_is_not_blocked_by_a_stale_audit_report` |
| A17 | P1 | reset/repair 清空 findings 却保留 dispositions；重用 B-001 会继承旧 accepted | rule-audit / disposition + 重跑 | `test_a_disposition_cannot_resolve_a_different_finding_with_a_reused_id` |

## 3. P0/P1 复现与影响

### A3 · 客户端 digest 可重放（P0）

- **规格**：rule-audit「The candidate is what gets checked」；gate 必须绑定服务端当前候选快照。
- **代码**：`app/api/main.py` 从 body 读取 `candidate_digest` 并原样传给 `gate_node`；
  `app/nodes/gate.py:17` 用 `candidate_digest or snapshot_digest(state)`，客户端值优先。
- **复现**：创建 run → `stages/audit` → 修改 `store.get(thread)["fields"]` → 用**旧报告 digest**
  调 `/gate`。返回 `allowed`，`candidate_content_sha256` 是旧 digest。
- **影响**：编辑后的文档可用旧快照通过审批；这是“不确定性不得放行”的核心失效。
- **建议**：`/gate` 忽略客户端 digest（或仅接受用于一致性校验，不匹配即 `indeterminate`），
  始终用 `snapshot_digest(state)`；前端传浏览器 digest 只能作为“更严格”校验，不能作为依据。

### A13 · stale 报告仍能 Ask gate（P0，前端）

- **规格**：rule-audit「Document changes during the run」；报告 stale 后不得用于审批。
- **代码/行为**：`handleAskGate` 只传 `operation`；服务端状态仍是旧审计；`buildAuditView` 已显示
  `Report is stale`，但 `gate` 区块仍可操作，返回 `allowed`。
- **E2E**：`web/e2e/gate.spec.ts:26`（`test.fail`），编辑后 `data-decision=allowed`。
- **建议**：stale 时禁用 Ask gate；或把当前浏览器 digest 传给服务端并要求匹配，不匹配返回
  `indeterminate/stale_report`。注意与 A3 一起修，不能只信任客户端 digest。

### O2 · 全部文件解析失败仍产出占位字段（P0）

- **规格**：agent-normalize「全部文件失败」：`fields` MUST 为空、`StageReport.status` MUST 为 `failed`、
  整次运行判定为 `fail`。
- **代码**：`parse_node` 正确写 `failed`，但 `extract_node` 把“所有 doc 都带 errors”当成
  “没有 batch 失败”，`failed_batches=[]` → stage `done`、produced 0；`normalize_node` 随后按
  `required` 写 7 个 `missing` 占位，stage `done`。
- **复现**：`execute_chain(state, ["parse","extract","normalize"], llm=fixture)`，文件路径不存在：
  阶段为 `failed/done/done`，`fields` 有 7 个占位。
- **影响**：前端 `fieldChecksRan` 只看 extract+normalize 是否 done，会把“解析失败”当成
  “检查过且字段缺失”，从而发起审计并报告假缺陷；导出闸门也会看到 `inferred/missing` 混乱状态。
- **建议**：`extract_node` 在 `docs` 全部带 errors 时返回 `failed`（reason: all files failed），
  `normalize_node` 在 `docs` 全部失败时不写占位；`fieldChecksRan` 还应要求 `parse` 为 done。

### A1 · 人工确认不解除 needs_input（P0）

- **规格**：rule-audit「Present but unconfirmed」+ design D7：`status=inferred (or confirmed=false)`。
- **代码**：`app/audit/bind.py::bind_field` 只看 `status`；`app/nodes/hitl.py:143` 只写
  `confirmed=True`，不改 `status`。
- **复现**：`bind_field` 输入 `status=inferred, confirmed=True` → `state=unconfirmed`；
  `SCHEMA:guarantee_amount:required` 返回 `needs_input`。
- **影响**：HITL 修改后重新审计仍然 `needs_input`；`start_approval` 永久 blocked，形成
  “修改→失败→修改→失败”的死循环（与规格禁止的循环一致）。
- **建议**：`bind_field` 在 `status=inferred and confirmed=True` 时映射为 `confirmed`；HITL 也可将
  `status` 改为 `extracted`（需保留 `normalized_from`/`edited_by_user` 语义）。
- **对偶**：`pipeline_gate._unconfirmed_inferred` 已经按 `status=inferred and not confirmed` 判断，
  两处口径分叉正是该缺陷的来源。

### N1 · 多页 PDF 误判跨页（P0）

- **规格**：agent-normalize「跨页拼接必须降级」；只有真正跨页的 span 才降级。
- **代码**：`app/parsing/normalize.py::cross_page_span` 对 `start..end` 累积文本，命中时只检查
  `end > start and len(pages) > 1`，没有检查“needle 是否完整落在最后一个 block 内”。
- **复现**：3 个 block（page1/page1/page2），span 完全在第 3 个 block → 返回 `[1,2]`，
  `_build_field` 加 `merged_across_pages`，`classify` 降为 `inferred`。
- **影响**：任何多页 PDF 中位于后续页的字段都可能被降级；`pipeline_gate` 要求 inferred 已确认，
  导出被错误阻断。现有跨页测试只覆盖“真正跨页”的正例，因此全绿。
- **建议**：命中时先判断 `needle in normalize_ws(blocks[end]["text"])`；只有不在最后一个 block
  内才视为跨块；同时把同一页的跨 block 拼接（`len(pages)==1`）标记为可定位但需记录
  `merged_across_blocks`（或回填 page），避免 N2。

### API2 · 同名上传覆盖（P0）

- **规格**：document-import / multiple files；每份文件应有自己的内容与 fingerprint。
- **代码**：`app/runs.py::store_upload` 只用 `Path(filename).name` 作为落盘名；
  同一 run 中两个 `same.txt` 写同一路径。
- **复现**：`POST /runs` 两个 `same.txt`（`first`/`second`）→ `stages/parse` 两份
  `full_text` 都是 `second`。
- **影响**：第一份文件内容不可恢复，且两份 doc 的 `sha256` 与实际内容不一致；审计/抽取基于错误数据。
- **建议**：落盘名包含 `file_id` 或 digest（`<file_id>__<name>`），或上传前拒绝同 run 重名并提示
  改名；`SourceFile.file_id` 与 path 必须一一对应。

### A2 / N5 / N6 · 非有限数值（P0/P1）

- **规格**：rule-audit「Malformed numeric input」：scientific/NaN/∞/超精度必须是 unit finding，
  不得四舍五入；agent-normalize 值规范化不得崩溃。
- **代码**：`app/rules/engine.py` 的 amount parser 是 `Decimal(raw)`，接受 `NaN/Infinity/1e...`；
  `evaluate_rule` 的 `Decimal` 比较未捕获 `InvalidOperation`；`app/parsing/normalize.py`
  的 `_normalize_amount` 只在 `Decimal(body)` 外层捕获，`quantize` 在 try 外。
- **复现**：
  - `audit_state(fields.guarantee_amount="NaN")` → `decimal.InvalidOperation`，`audit_node` 整次
    failed；
  - `build_fields(raw="-Infinity")` → `InvalidOperation`；`"1e999999999"` → `Overflow`；
    `"-NaN"` → 字段值 `-NaN` 且无降级 note。
- **影响**：恶意/脏输入可让审计不可用；NaN 进入字段后导出文件不可被下游解析。
- **建议**：统一 `parse_decimal`：拒绝非有限、科学计数法（按规格）、超出 precision 的小数；
  返回 reason code；`quantize` 包在异常处理内；schema `precision` 真正执行。

### A4 / A5 / A6 · 审计重跑状态污染（P1）

- **规格**：findings 绑定快照；新审计使旧 gate 失效；失败审计不得留下旧结论。
- **代码**：
  - `_failed` 只返回 `verification=None, gate=None`，不返回 `findings`；
  - 成功 update 不返回 `gate=None`；
  - `findings` 是 reducer，`merge_update` 把新 findings 追加到旧列表。
- **复现**：缺失金额 → 首次审计 1 条 finding → 强制失败 → state 仍有 1 条；
  首次 gate=`allowed` → 修改字段再审计 → `gate` 仍 `allowed` 且 digest 是旧值；
  连续两次审计 → findings 从 1 变 4。
- **影响**：UI 可同时显示 failed stage 与旧 findings；旧 `allowed` 与新报告并存，审批语义被污染。
- **建议**：审计节点返回 `findings: Overwrite([...])`（首次/重跑均替换）、`gate: None`；
  失败时显式 `findings: Overwrite([])`；或者把 findings 按 `snapshot_digest` 归档。

### A17 · 重跑后 Finding ID 重用，旧 disposition 误命中（P1）

- **规格**：`Finding` 的 disposition 是人工对**某一条** Finding 的处理；`stages`/`trail` 追加，
  `reset` 只清本轮结论。
- **代码**：`reset_node` / `repair_node` 清空 `findings`，但保留 `dispositions`；
  `materialize_findings` 的前缀计数器只看当前 `findings`，清空后重新从 `B-001`/`N-001` 开始。
- **复现**：旧 B-001 critical + `accepted` → reset → 新审计又产生 B-001 critical → `evaluate_gate`
  把旧事件当成本次处理，返回 `allowed`（新 Finding 没有被人工处理）。
- **影响**：审批绕过；同时违反“历史只能追加、不能把旧处理贴到新事实”。
- **建议**：Finding ID 在 run 生命周期内单调（计数器持久化/从 trail 取最大），或 disposition 事件
  绑定 `(finding_id, check_id, snapshot_digest)`；reset 清 findings 时同时归档 dispositions，
  新快照不得读取旧快照的 disposition。

### A9 · 导出非幂等（P1）

- **规格**：orchestration「重复提交」：不得重复写版本。
- **代码**：`app/nodes/export.py` 每次 `versions.append`；`DocVersionStore.next_version` 自增。
- **复现**：同一 state 调 `export_node` 两次 → `version_no=1`、`2`。
- **现有测试反例**：`tests/test_gate.py::test_export_refuses_a_blocked_gate_and_writes_version_on_pass`
  明确断言第二次为 2，等于把缺陷固化为期望；本次已加 xfail 反向断言。
- **建议**：以 `(run_id, snapshot_digest, gate.policy_revision)` 做幂等键，命中则返回既有版本。

### A10 · accepted 不能解除 blocking（P1）

- **规格**：Finding 有 disposition state；导出闸门只拦“未处理项”。
- **代码**：`pipeline_gate` 只读 `finding["resolved"]`，而 disposition 是 append-only events，
  没有任何代码把它写回 `resolved`；`evaluate_gate` 用 events 判断 critical，两者口径不一致。
- **复现**：blocking finding + `dispositions=[{finding_id, disposition:"accepted"}]` + 其它检查全过
  → `verdict=blocked`（`BLOCKING_UNRESOLVED`）。
- **建议**：`pipeline_gate` 读取 `state["dispositions"]`，以 latest disposition 判断；
  `accepted/rejected/needs_human_review` 均视为已处理（是否允许导出由 operation policy 决定）。

### N2 / N3 / N4 · Agent1 事实性偏差（P1）

- **N2**：`extract.locate_span` 只按单 block 匹配，跨 block 时 page 为 `None`；
  `_build_field` 不尝试用 `doc.blocks` 回填；`cross_page_span` 同页多块返回 `None`，
  于是 `span_locatable` 对整篇 `full_text` 成功 → `extracted + page=null`。
- **N3**：`_CURRENCY_PREFIX` 只剥非数字前缀，没有“约/大概/approximately/about/~”等 hedge 检测；
  `约 USD 500K` → `500000.00`、`extracted`。
- **N4**：`decide_business_type` 用原始 `full_text` + `re.IGNORECASE`，没有走 `normalize_ws`；
  全角/零宽排版差异会得到 `unsupported`。
- **建议**：N2 回填 page/bbox 或在无法定位具体页时强制 `inferred`；N3 增加 hedge 词表并降级；
  N4 对全文先 `normalize_ws` 再匹配（注意 `normalize_ws` 不折叠大小写，业务类型匹配可另行
  `casefold`，但不能绕过基准）。

### R1–R4 · Agent3 静默风险（P1）

- **R1**：`_mock_hits` 只拼接 5 个字段；raw 模式没有字段 → 正文中的 mock 名单永不命中。
- **R2**：`_structural_drafts` 的 evidence 用 `legal["summary"]`（生成文本），不是正文片段；
  raw 模式要求 `field_keys=[]` 且 evidence 指向正文。
- **R3**：`_FORBIDDEN` 只有 `未发现问题/无适用规则/合法合规`，`_sanitize_summary` 也只替换这些；
  “该保函合规/可做”原样保留在 summary 和 claim。
- **R4**：免责声明只放在 `_draft.suggestion`；零 finding 的干净结果没有任何“不替代正式筛查”声明。
- **建议**：R1 同时扫描 `_full_text(state)`；R2 用正文中命中片段/摘要句做 evidence；
  R3 扩展禁用词（合规/不合规/可做/不可做/可开立…）并同时清洗 claim 文本；
  R4 把 disclaimer 作为 `legal` 的固定字段输出（或 legal.summary 固定后缀）。

### A11 · severity 仍决定阻断（P1，规格内部冲突）

- **规格**：`Severity does not decide blocking`；`Model output can never hard-block`；
  gate 只按 `hard_block + target_operations + policy`。
- **代码**：`evaluate_gate` 的 `block_on_unresolved_critical` 收集所有 `severity=="critical"` 的
  finding，不看 `gate_type`/`method`/`target_operations`；`tests/test_audit_gate.py` 现有用例
  `test_advisory_findings_never_block_but_unresolved_critical_does` 把该行为固化为期望。
- **复现**：advisory+critical（target=handoff）问 `start_approval` → `blocked/unresolved_critical`；
  semantic+hard_block → 同样 blocked（应被 semantic 合同拦截为 FAILED，而不是 hard block）。
- **影响**：与定义冲突；且任何 advisory critical 都会让审批无法通过，除非人工 disposition。
- **建议**：明确政策：要么只对 `gate_type=hard_block` 的 critical 要求 disposition，要么在规格中
  增加“critical advisory 也需人工处理”的独立规则；当前实现与 spec 文本不一致，需 owner 裁决。

## 4. 测试基础设施缺陷（已修复，不计入产品缺陷）

| 问题 | 证据/修复 |
|---|---|
| E2E 仍找旧 textarea `[data-testid=editor-text]`，富文本升级后 8 条 E2E 全部失败 | `web/e2e/support/workspace.ts` 改为 `[data-testid=editor-rich] .ProseMirror`；`layout.spec.ts` 同步 |
| `errors.spec.ts` 断言“Only the rule audit tab is wired”，但 Legal advice 已实现 | 更新为 “Only the rule audit and legal advice tabs are wired” |
| `fillable-blank.spec.ts` 用 `URL.pathname`，Windows 变成 `/C:/...` | 改用 `fileURLToPath` |
| Playwright 后端命令写死 `.venv/bin/uvicorn`，Windows 无法启动 | `playwright.config.ts` 改为 `python -m uvicorn`，按平台选择 `.venv/Scripts/python.exe` |
| 本机 8000 被 RAGFlow 占用 | 执行时用临时端口配置；临时文件已删除 |

## 5. 覆盖缺口（非缺陷，但需要 owner 确认）

1. **模板变更 staleness 在生产链路不可达**：`evaluate_gate(template_digest=...)` 只在单测中被调用；
   `gate_node` / `pipeline_gate` 都没有传当前模板 digest，因此“模板改了但报告没变”无法被发现。
2. **Finding 的 disposition state**：`verification.audit.findings[]` 没有 `disposition` 字段，
   只有独立的 `dispositions` 事件列表；规格文字要求 finding 本身含 disposition state，需定义
   “读取时派生”还是“写入时冗余”。
3. **表格“之前”操作**：规格要求行/列前插入与表头切换；当前 UI 只有 `+R/-R/+C/-C`（后/右），
   没有 before/left 与 `toggleHeaderRow`。Tiptap 命令存在但未暴露；`BUG-F5` 已固定。
4. **Agent2**：`requirements.yaml`、字段语义校验、`not_found`/`missing` 双判等未纳入本次矩阵；
   `pipeline_gate` 的 `agent2` 阶段要求已存在，Agent2 完成后需重跑导出/审批链路。
5. **OCR**：依赖本机 Tesseract/语言包；现有测试对“无文本层”与“引擎缺失”有覆盖，但未做真实
   扫描件识别质量评测。
6. **并发**：RunStore 每 run 锁已覆盖基本并发；未做多进程/多 worker 的 SQLite 竞争压测。

## 6. 建议修复顺序

1. **A3 + A13**（审批完整性，P0，必须同修）
2. **A1 + A4/A5/A6**（HITL/重跑状态，P0/P1）
3. **N1 + N2 + A2/N5/N6**（多页与数值，P0/P1）
4. **API2 + API1**（上传/边界，P0/P1）
5. **A9 + A10**（导出幂等/处理闭环，P1）
6. **R1–R4 + N3/N4**（法规静默风险，P1）
7. **A7/A8/A11**（审计健壮性与规格裁决，P2/P1）
8. **F1–F4、R5–R7、表格 before 操作**（前端/引用细节，P2）

修完每条后删除对应 `xfail` / `it.fails` / `test.fail`；若测试 XPASS，说明行为已变化，需要同步
规格与本文档。
