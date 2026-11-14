# Tasks

> 依据：`proposal.md`（A1 范围）、`specs/knowledge-assistant/spec.md`（行为）、`specs/document-editor/spec.md`（tab 变更）、
> `design.md`（D1–D12）。每组的测试随组落地；第 6 组只做跨组验收。
> **A 的边界：** 不做 PostgreSQL/Worker/真实鉴权/真实模型/向量/联网/语音/管理端 UI；但 Port、DTO、状态机、
> 知识源状态、权限与 Reviewer 按 C 的接缝实现，后续只换 Adapter/存储/执行器。

## 0. 合同、Port 与状态机（I1）

- [x] 0.1 `app/assistant/schemas.py`：Session / Run / Message / Answer / Claim / Citation / EvidenceDetail / Feedback / Error 的 Pydantic DTO 与枚举；禁止额外字段；导出 OpenAPI 片段。Verify: 单测验证规格中的成功/失败示例可解析，未知字段/非法枚举/非法组合被拒绝。
- [x] 0.2 `app/assistant/ports.py` + 依赖注入：Identity、Authorization、Snapshot、Store、Retriever、ModelGateway、Audit、KnowledgeAdmin、Clock、Ids；local/test/production 模式配置。Verify: fake 模式可启动；production + fake/合成源 MUST 启动失败；单测覆盖。
- [x] 0.3 `app/assistant/domain/state_machine.py`：Run 状态/阶段转换、单 Session 一个活跃 Run、取消/超时/发布 CAS、终态不可覆盖、幂等键语义；Answer outcome/support_level 不变量。Verify: 纯函数单测覆盖合法/非法转换与竞争分支。

## 1. SQLite 存储与 Fake Adapter

- [x] 1.1 `app/assistant/persistence/sqlite.py`：按规格 §7.3 建表（sessions/messages/runs/dependencies/citations/feedback/knowledge_sources/versions/chunks/idempotency_records/outbox_events），全部经 repository 接口；版本化 schema。Verify: repository 合同测试；表/列与未来 PG 映射文档一致；业务层无直接 SQL。
- [x] 1.2 Fake Identity/Authorization/Snapshot/Audit：固定 workspace + 两个 principal；POC 专用 `POST /assistant/snapshots` 注册当前版本摘要/正文；owner 在服务端校验。Verify: 两个用户互相访问 Session/Run/Citation 均 404；快照不可变；production 使用 fake 被拒。
- [x] 1.3 启动恢复与截止时间：进程重启把过期 `queued/running` 标为 `failed/timed_out`；轮询/执行器检查 deadline。Verify: 单测模拟重启与超时，终态不被迟到结果覆盖。

## 2. 知识层、发布状态与检索

- [x] 2.1 `app/knowledge/models.py` + SQLite repositories：来源/版本/分块；字段含 source_type、publisher、version、language、scope/ACL、license、effective_from/to、status、submitted_by/reviewed_by、locator。Verify: repository/状态字段单测；缺失适用性元数据显式为 null + 原因。
- [x] 2.2 `fixtures/knowledge/*`：合成产品 FAQ、贸易规则摘要、内部政策；每条显著标注 synthetic/not legal advice，带版本与生效期。Verify: 种子后只读；fixture 元数据可追溯。
- [x] 2.2a Phase 1 合成语料扩展：在现有 3 个 source 上扩到 `trade_rules` 12 / `product_faq` 12 / `internal_policy` 8 chunks（共 32）；版本升 `demo-2`，保留条款级 `locator`；不新增规则 source，避免跨 source 冲突。Verify: 空库 seed 后 3 个 source/32 chunks 均为 `published`；原 20 题引用基线不退化（若新 chunk 合法改变期望引用，在 6.4a 显式更新并记录原因）；新内容仍带 synthetic/非官方声明。
- [x] 2.3 最小导入/审核/发布/撤回（service + CLI）：`processing → pending_review → published | rejected`；`reviewed_by != submitted_by`；发布原子切换；`superseded`/`withdrawn`。Verify: 单测覆盖待审核不可检索、自审拒绝、部分失败不发布、撤回立即生效。
- [x] 2.4 `app/knowledge/retriever.py`：词法检索（英文 casefold + 中文关键词/二元组），先过滤 published/ACL/生效期；`RetrieverPort`。Verify: 20 个合成问题的命中基线；无命中与检索依赖失败分别返回不同结果。
- [x] 2.5a 本地/测试 fixture 补种：`build_services`/`seed_knowledge` 检测已有 DB，补种缺失 source、升级 fixture version；相同 source/version 不重复发布；补种失败明确报错。Verify: 旧 3-source DB 重启后补齐 8 sources/72 chunks；重复启动不新增版本；生产模式不执行 fixture 补种。
- [x] 2.5b 语言隔离检索：`published_chunks`/`LexicalRetriever` 按 `plan.language` 过滤；中文只返回中文 source、英文只返回英文 source；帮助 source 由 `knowledge-onboarding` 按语言映射。Verify: 中英文问题各自只 cite 同语言 source；不混用；中文既有 33 题基线不退化。

## 3. 问答管线与 Reviewer

- [x] 3.1 `app/assistant/domain/query.py`：确定性意图路由（product_faq / trade_rule_explanation / document_explanation / out_of_scope）；缺规则版本/法域/适用日期时澄清；修改/审批请求转交。Verify: 枚举外结果被拒；澄清/转交各有单测。
- [x] 3.2 EvidenceBuilder：从检索结果生成稳定 evidence ID、来源版本、允许摘录、定位、冲突/缺口；文档快照/选区定位与 code point 切片校验。Verify: 伪造/越界定位被拒；选区不匹配返回 ANCHOR_MISMATCH。
- [x] 3.3 Fixture Composer：输出结构化 Answer（claims/citations/limitations/clarification/handoff）；只能引用 EvidenceBundle 中的 ID；fixture 标注。Verify: 无证据时 `insufficient_evidence`；引用 bundle 外 ID 被 Reviewer 拦截。
- [x] 3.4 代码 Reviewer：引用存在/摘录匹配/关键实体覆盖/Claim 支持关系；计算 support_level；最多修复一次，失败删除无依据 Claim 或 abstain。Verify: 负例覆盖“伪造引用”“引用不支持 Claim”“金额不在被引原文”；不记录隐藏思维链。
- [x] 3.5 Publisher：发布前重新授权、来源状态检查；Answer/Citation/Message/Run 终态/审计原子写入；撤权/撤回后 redacted。Verify: 单测覆盖发布失败不落半成品、撤权后读取 redacted。

## 4. API 与执行器

- [x] 4.1 `app/api/assistant.py`：Session（创建/读取/列表）、Run（创建 202/轮询/取消）、Messages、Citation Detail、Feedback；错误码/404/409/422/503 与幂等键。Verify: TestClient 覆盖成功/错误合同与 owner 隔离；未知字段被拒。
- [x] 4.2 执行器：进程内/后台任务实现，deadline/取消/超时/单活跃 Run/CAS；重复 Worker/迟到结果不重复写助手消息。Verify: 单测覆盖取消/超时/并发发布/重复执行；C 只换 Runner。
- [x] 4.3 反馈与 redacted 历史：同一用户/消息 PUT 替换并保留历史；依赖失权后消息占位不含正文/标题/引用。Verify: 反馈替换与 redacted 单测。

## 5. 前端 Knowledge Q&A

- [x] 5.1 `web/src/api/assistant.ts` + types：Session/Run/Message/Answer/Citation/Feedback 客户端；轮询/取消/错误文案；`KnowledgePanel`。Verify: client 单测断言 URL/方法/错误映射；typecheck clean。
- [x] 5.2 `AssistantPanel` 把 knowledge 标为 implemented，新增面板：基于当前 version digest 注册 snapshot + 创建 session；问题/选区；轮询/取消；Answer（outcome/support_level/claims/citations/limitations/澄清/转交）；引用详情；反馈；fixture-backed 横幅；旧版本提示新建会话。Verify: 组件测试覆盖成功/无证据/澄清/转交/失败/取消/跨用户 404；Automation/Legal 仍标 not implemented。
- [x] 5.3 `document-editor` delta 验收：knowledge tab 可用且不渲染示例答案；audit tab 保持；automation/legal 仍标未实现。Verify: `AssistantPanel.test.tsx` 更新；既有前端测试全绿。

## 6. 验收与文档

- [x] 6.1 端到端（真实 HTTP）：FAQ 有证据回答 + 引用；规则解释缺版本 → 澄清；文档选区问答；无证据 → insufficient；伪造引用被拦截；跨用户 404；撤权/撤回 → redacted；取消/超时终态。Verify: pytest/HTTP e2e 记录结果。
- [x] 6.2 回归：`.venv/bin/python -m pytest -q`、`npm --prefix web run test`、`typecheck`、`build`；确认 `EditState`/现有 audit 链路未变。Verify: 命令输出与记录一致。
- [x] 6.3 文档：`how_to_use.md` 增加知识助手一节（fixture/合成语料、支持等级、引用/反馈、A 不做的能力）；`web/README.md` 更新 tab；DEMO 记录 A→C 边界。Verify: 文档中的每条操作/限制与 UI 一致。
- [x] 6.4 合成评测集：20 个问题 + 期望引用/outcome；计算引用命中、弃答/澄清正确率；明确未做向量/重排/真实模型。Verify: `eval/` 报告数字可由测试复现。
- [x] 6.4a Phase 1 评测扩展：在 20 题基线上新增 5 题（UCP 600 审单、ISP98/ISBP、费率、修改、事件报告），总 25 题；更新 `tests/test_assistant_eval.py` 与 `tests/test_knowledge_retriever.py` 的总数断言；保持 `outcome_accuracy >= 0.95`、`citation_hit_rate >= 0.9`，并保留“未做向量/重排/真实模型”说明。Verify: `scripts/assistant_eval.py` 输出 25 题且数字可复现。
- [x] 6.5 Phase 1 文档同步：`how_to_use.md` / `web/README.md` 更新语料规模、评测数字与演示问题；确保仍标 `Fixture-backed`。Verify: 文档数字与 `scripts/assistant_eval.py` 实际输出一致。
- [x] 6.6 英文提示词文档同步：与 `knowledge-onboarding` 一起更新 `how_to_use.md` / `web/README.md` 的英文 onboarding/chips 示例、8 sources/72 chunks/33 题与旧库补种说明。Verify: 文档示例与英文 UI 一致；`Fixture-backed` 与 synthetic 声明仍在。

## Workflow follow-up

- **C 升级（独立 change）**：详见 [`TBD-upgrade-to-c.md`](TBD-upgrade-to-c.md)（K01–K15、顺序、触发条件、反模式）。SQLite → PostgreSQL repositories + 迁移；进程内执行器 → Worker/队列/租约/fencing；Fake Identity/Snapshot → 宿主 Adapter；词法 → 混合/向量/重排；Fixture Composer → 批准模型；知识 CLI → 导入/独立审核/管理端 API/UI；轮询 → SSE/观测/限流。
- **与 `agent-regulatory` 协调**：本 change 拥有 `app/knowledge/`；法规组作为只读消费者，不复制语料/索引。需在该 change 的 follow-up 记录。
- **P1**：受控联网、语音/截图、导出；不因 UI 入口出现而算完成。
- **不要声称生产**：A 的 fixture/合成语料/本地 fake 必须在 UI、文档与 DEMO 中显式标注；production 检测到 fake 必须失败关闭。