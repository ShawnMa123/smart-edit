# Tasks

## 1. 契约（`app/legal_review/contracts.py`）

- [x] 1.1 `ReviewCreate` 增加 `scope`（默认 `question`）、`draft_id`、`expected_revision`、`expected_content_sha256`、`business_type`、`web_search`，`snapshot_id`/`facts_version_id` 变为可选
- [x] 1.2 `DocumentAnchor` / `EvidenceAnchor` 拆分；`Finding` 增加 `document_anchors`、`suggestion`、`basis`，`anchors` 改为 `EvidenceAnchor`
- [x] 1.3 `CheckResult` 增加 `clause_id`、`evidence_count`、`search_queries`
- [x] 1.4 `ReviewRun.progress`；`ReviewReport` 增加 `snapshot`、`coverage_summary`、`retrieval`、`gate`

## 2. 条款计划（`app/legal_review/document.py`）

- [x] 2.1 基于 `project_document()` 的顶层 block 切分，保留 `start_cp/end_cp/block_index`
- [x] 2.2 标题 / 编号 / 长度三种切分触发；`max_chars`、`max_clauses` 可配
- [x] 2.3 `quote_for()` 保证锚点 quote 是草稿子串；`block_at()` 支持定位
- [x] 2.4 空文档 `no_text`；超上限 `truncated`

## 3. 确定性检查（`app/legal_review/checks.py`）

- [x] 3.1 `ELEMENTS`：金额/币种/失效日/适用规则/申请人/受益人/开立日/管辖/索赔单据；缺失 → finding（金额等 `hard_block`）
- [x] 3.2 `MARKERS`：自动展期 / 无条件付款 / 单方决定 / 最终解释权 / 放弃抗辩；命中 → `human_review`
- [x] 3.3 占位符（`{{…}}` / `<<…>>` / TBD / 待填）→ `advisory`
- [x] 3.4 日期一致性：失效日 > 开立日；已过期；解析不出 → `needs_input`（不猜 DMY/MDY）
- [x] 3.5 锚点由 block 计算，quote 为原文子串

## 4. 检索与综合（`app/legal_review/scan.py`、`compose.py`）

- [x] 4.1 planner：`planned = 元素 + 一致性 + 每条款 presence(+statute) + 可选 web`
- [x] 4.2 每条款一次 `/v1/retrieve`（线程池 ≤4），用 `reason` 区分 `zero:*` / `uncovered:*` / `low_confidence` / 失败
- [x] 4.3 `LegalComposer.review_clause()`：JSON 校验（未知 rule/evidence id 丢弃、severity≤Warning、gate≤human_review、quote 必须可定位）
- [x] 4.4 `DoubaoGateway.compose_json()` 复用 Responses API 传输；无 key/fixture → `composer_unavailable`
- [x] 4.5 覆盖率汇总（planned/settled/assessed/ratio/by_status/uncovered）与 `gate_for()`
- [x] 4.6 超时（`SCAN_DEADLINE`）→ 剩余条款 `unable_to_assess` + `deadline_exceeded`

## 5. 联网补检（用户选择）

- [x] 5.1 `web_search` 三态（未指定 → 部署默认 off）
- [x] 5.2 只在有条款未被语料覆盖时触发，问题只带 clause 标题
- [x] 5.3 结果 `basis=web` + `unverified` + `human_review`；无 URL 丢弃
- [x] 5.4 `retrieval.web_requested/web_used/web_calls` 写入报告

## 6. 服务与 HTTP（`service.py`、`app/api/legal.py`、`app/api/main.py`）

- [x] 6.1 `LegalService`：question 同步、document 异步；`Idempotency-Key` 复用 run
- [x] 6.2 `stale_snapshot`（revision / sha / draft_id 三种 pin）
- [x] 6.3 `LegalStore`（SQLite：`legal_runs` / `legal_reports` / `legal_idempotency`），报告按 workspace 校验
- [x] 6.4 `GET /legal/runs/{run_id}`；错误沿用 `{code,message,detail?}`
- [x] 6.5 `create_app()` 注入 documents/statute/composer；裸 router 测试用内存 store
- [x] 6.6 `EgressPolicy.redact()` 公开方法，composer 出站前调用

## 7. 前端（`web/src`）

- [x] 7.1 `api/legal.ts`：新类型 + `getRun` + 轮询常量
- [x] 7.2 `LegalPanel`：`Document check` 标签页、revision/sha 展示、扫描、进度、覆盖率、闸门、限制说明
- [x] 7.3 findings 按严重度排序；草稿引用块 + “Jump to clause”；法条卡片；网页链接标注 unverified；建议修改
- [x] 7.4 联网开关（默认关）；“Draft changed since this scan” 提示
- [x] 7.5 `useRichEditor`/`RichEditor` 支持 `focusBlock` + `focusToken`，App 连接 `onJumpToBlock`
- [x] 7.6 样式：`.legal-scan`、`.legal-web-toggle`、`.legal-document-anchors`、`.legal-jump`、`.legal-gate-reasons`

## 8. 测试与验收

- [x] 8.1 `tests/test_legal_document_scan.py`：切分/锚点子串/缺失要素/日期/标记/无 statute/覆盖率/compose 校验/web 开关/幂等/stale
- [x] 8.2 `tests/test_legal_document_api.py`：202 + 轮询 + 报告 + `stale_snapshot` + 未知 run 错误契约
- [x] 8.3 `web/src/components/LegalPanel.test.tsx`：advice、扫描轮询、联网开关、失败 run、过期快照
- [x] 8.4 `web/src/rich/useRichEditor.test.tsx`：mount 不误报用户编辑；`focusBlock` 定位
- [x] 8.5 `pytest tests` 全绿；`npm --prefix web run typecheck && npm --prefix web run test` 全绿
- [ ] 8.6 样本集评测：4 份注入风险的样本文档（缺金额/日期倒置/URDG 版本冲突/自动展期）→ 固定期望 findings 与覆盖率
- [ ] 8.7 在 ECS 上跑一次真实扫描（RAGFlow + 豆包），记录 P50/P95 与 `uncovered` 比例

## 9. 后续（未包含在本期）

- [ ] 9.1 `SubmitVersionDialog` 接入 `gate`：`blocked` 时禁用提交并列出 hard_block findings
- [ ] 9.2 finding 处置（accept/reject/needs_human_review）持久化与审计事件
- [ ] 9.3 扫描结果缓存键 `sha256(text + rules + corpus.index_version)`，重复扫描免重复计费
- [ ] 9.4 PG 迁移（多实例部署时替换 SQLite store）
- [ ] 9.5 样本评测：脱敏（金额→`[redacted]`）对模型判断的影响，必要时改用「类型保留型」脱敏（如 `USD [amount]`）
- [ ] 9.6 合规词表的运维化：`SMART_EDIT_LEGAL_COMPLIANCE_FILE` 指向部署自维护的 JSON（目的地/货物/规避词），
      启动时校验并记录版本；当前词表在代码里，改动需要发版
- [ ] 9.7 denied-party 名单离线比对（OFAC SDN / BIS Entity List 快照）：需要名单文件与更新机制，本期用「提示 + 转人工」
- [ ] 9.8 合规 finding 的处置与报告导出（给合规官看的 PDF/CSV）

## 10. 实质性合规层（`sanctions-export` 场景）

- [x] 10.1 `app/legal_review/compliance.py`：目的地两级、受控货物 11 类、跨境渠道、规避措辞 4 类
- [x] 10.2 组合判定：全面制裁 × 受控货物 → `Critical`/`hard_block`；行业制裁 × 受控货物 → `Critical`/`human_review`
- [x] 10.3 四个合规单元进入计划，pass / finding / not_applicable 都有明确 reason
- [x] 10.4 草稿锚点：货物与目的地各自给出 quote + block_index
- [x] 10.5 composer 规则目录固定包含 `LEGAL-COMPLIANCE-*`，模型可补充但不得升级
- [x] 10.6 联网补检在「受控货物 + 目的地」时改问合规问题（EAR/ITAR/OFAC/EU/UN）
- [x] 10.7 要素目录按文种切换（保函 9 项 / 合同 4 项），`snapshot.document_type`
- [x] 10.8 `tests/test_legal_compliance.py`：中英文命中、行业制裁分级、干净文本无误报、硬阻断锚点、回避措辞
- [x] 10.9 样例：`fixtures/legal-samples/sanctions-export{,-zh}.txt`