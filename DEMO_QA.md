# DEMO_QA · 汇丰 AI 跨境业务创新大赛答辩手册

> **版本**：v2（PM 优化版）｜**更新**：2026-11-23
> **事实来源**：本仓库代码 + `README.md` / `DEMO_Tech.md` / `how_to_use.md` / `deploy/README.md` + 本轮实测。
> **原则**：只承诺能演示的；做不到的，明确说"边界 + 路线"。

---

## 0. 怎么用这份文档（30 秒读完）

| 场景 | 直接看 |
|---|---|
| 上台前 10 分钟 | §1 一页答辩卡 + §9 禁忌 |
| 现场被问住 | §2 TOP 12 → 按编号跳 §3/§4/§5 |
| 评委说"演示一下" | §6 Demo 剧本 |
| 被问"下一步做什么" | §8 路线图（含 Phase 2 一致性） |
| 需要引用代码 | §10 证据索引 |

**两条阅读约定**
1. 状态标签只有三种：**✅ 已实现**（能演示）｜**🟡 有基础待优化**｜**⛔ 未实现 / 不在当前范围**。
2. 每个问题固定结构：**一句话答 → 展开 → 证据 → 状态 → 追问怎么接**。赶时间只读"一句话答"。

---

## 1. 一页答辩卡（建议打印这一页）

### 1.1 我们是谁

> 把跨境贸易单证里"人读文档、逐条对照模板与法规"的重复劳动，变成**有证据、可审计、可复现**的结构化审查。**放行永远由人做。**

### 1.2 三个不能越过的边界

1. **不是制裁筛查，也不是法律意见**——是"需要人复核的红黄线"。
2. **AI 不提交、不批准、不派发**——Critical 硬阻断只来自确定性规则。
3. **"没查到" ≠ "没问题"**——`unable_to_assess / needs_input / unchecked_units` 是数据结构，不是文案。

### 1.3 必须记住的 5 个数字

| 数字 | 含义 |
|---|---|
| **1219 / 32** | 后端 `pytest` passed / skipped（本轮实测） |
| **670 / 12** | 前端 `vitest` passed / skipped（本轮实测） |
| **57** | 模板审计样例检查项：pass 36 / finding 1 / NA 19 / unable 1 |
| **11 + 11 + 4** | 合规目录：目的地 / 货物类别 / 规避措辞 |
| **12 / 10** | 制裁样例扫描：planned / assessed；4 findings，Gate Blocked |

> 口径提醒：`TEST_REPORT.md` 里的 655/178 是更早基线；答辩用本轮数字。

### 1.4 最可能被问的 3 个问题

| 问题 | 一句话答 |
|---|---|
| **你们的漏报率？** | 没有生产漏报率（无银行标注集）；控制 = 词表 + 证据内模型 + 人复核，下一步与客户共建评测集。 |
| **为什么不直接用 Copilot？** | 银行要"敢签字"：证据绑定、模型不能提级/阻断、默认不出网、报告可复现。 |
| **SQLite 单机怎么上银行？** | 现在是单租户 POC；生产路径 host.db→PG + 队列 + 多副本，差距清单见 §8。 |

### 1.5 三句不能说

| ❌ 不要说 | ✅ 改成 |
|---|---|
| 我们做制裁筛查 / 合规判定 | 红线提示，与正式筛查并联 |
| 模型不会错 | 错了可发现、可追溯、不自动放行 |
| 银行级高可用 / 已过 SOC2 | 单实例 POC，生产化清单在这里 |

## 2. 高频问题 TOP 12（按现场概率排序）

> 现场先给"一句话答"；评委继续追问，再展开对应 Q。

| # | 评委问题 | 一句话答 | 展开 |
|---|---|---|---|
| 1 | 你们漏报率/误报率多少？ | 没有生产数字；现有是规则单测 + 样例，缺银行标注集。控制=词表+模型+人，评测集是 Phase 2 首要项。 | Q10 |
| 2 | 你们和 Fircosoft/Actimize 什么关系？ | 不替代；他们管名单命中，我们管单证文本里的红黄线，并联使用。 | Q9 |
| 3 | 为什么不直接用通用大模型？ | 通用模型能读得像，银行要能签字：证据绑定、不能提级/阻断、默认不出网、可复现。 | Q5 / Q22 |
| 4 | 客户数据出境吗？模型能换吗？ | 默认不出网；出网需批准处理器 + egress + 脱敏；模型可切私有部署。 | Q7 / Q13 |
| 5 | SQLite 单机怎么支撑银行？ | 现在明确是单租户 POC；生产路径 PG+队列+多副本，已有迁移清单。 | Q19 / Q20 |
| 6 | 怎么防止模型编法条？ | 只能引用给定 evidence id；quote 必须能定位；定位不到就 `unable_to_assess`；Critical 只来自规则。 | Q22 / Q26 |
| 7 | 英文单据为什么"无法评估"？ | 语料目前以 CN/EU/INT/US/WTO 为主；检索不到就如实说无法评估，不猜。 | Q16 / D4 |
| 8 | 模型错了谁负责？ | AI 不放行；人签放行；报告留模型/证据/人工处置；合同与保险待补。 | Q11 |
| 9 | 多租户 / SSO / 高可用呢？ | 都未实现；当前单实例+自建 session，路线在 §8。 | Q19 / Q20 / Q27 |
| 10 | 单份成本 / P95 延迟？ | 架构上可控（确定性优先、按 clause 检索、web 默认关），但还没压测，不能给承诺。 | Q32 |
| 11 | 怎么接 SWIFT / 核心系统？ | 有 REST + 幂等 + 通用 downstream；SWIFT/ISO 20022 适配器未做。 | Q31 |
| 12 | 90 天能交付什么？ | Phase 2：评测集、OCR、性能基线、PG/SSO、真实单据 pilot；Phase 3 企业化。 | §8 |

---

## 3. 业务与商业（Q1–Q8）

### Q1. 解决谁的什么问题？

- **一句话答**：贸易融资/保函/信用证链条上，申请人、Trade Ops、Compliance 三段里"逐条对照 + 找证据 + 写意见"的重复劳动。
- **展开**：不替代任何人的签字权；替代的是"翻文档、对模板、找法条"的工时。
- **证据**：`demo-document` 保函 → Audit 57 项 → Legal 扫描 → Approval 一审/二审。
- **状态**：✅
- **追问**："具体哪个岗位的一天？" → 答：Trade Ops 的单证准备与合规复核，不是客户经理的营销。

### Q2. 价值怎么量化？

- **一句话答**：POC 不宣称 ROI 百分比；给可测的机制指标，试点用 A/B 拿客户基线。
- **展开**：cycle time、人工分钟、补件轮次、一次通过率、合规复核项数、漏检/误报。
- **证据**：报告的 `planned/assessed/unchecked` 与 finding 锚点天然可对比。
- **状态**：🟡（机制 ✅，数字待试点）
- **追问**："那你们现在能承诺什么？" → 承诺"同一批单据可测出基线"，不承诺具体百分比。

### Q3. 和 Traydstream / Conpend / Surecomp / Finastra 比？

- **一句话答**：不拼单证解析广度与银行连接器；拼"证据层"——可审计、可私有化、模型可替换。
- **展开**：他们像单证处理平台，我们像合规复核的证据层，可以先并进他们的流程。
- **状态**：✅（定位）/ 🟡（缺量化竞品对比表）
- **追问**："那客户为什么不直接买他们？" → 他们不解决"这条结论凭什么"和"没查成怎么显示"。

### Q4. 谁买？预算从哪出？怎么定价？

- **一句话答**：Trade Ops（效率）与 Compliance（可解释/留痕）两类买家；POC 不定价。
- **展开**：可选单租户私有化 license + 实施，或按文档量托管；成本结构可拆（确定性≈0、按 clause 检索、web 默认关）。
- **状态**：🟡（有形态，无定价/毛利模型）
- **追问**："谁有预算？" → 合规科技/贸易融资数字化预算；创新预算只适合 POC。

### Q5. 为什么银行不直接用 Copilot？

- **一句话答**：通用模型能"读得像"，银行要"敢签字"：证据、权限、出网、可复现。
- **展开**：引用必须可定位；模型不能提 severity/不能硬阻断/不能审批；默认不出网；报告记录版本。
- **状态**：✅（机制）
- **追问**："那你们比 Copilot 强在哪？" → 不是模型强，是**约束与审计**强。

### Q6. 试点成功的 3 个可签指标？

- **一句话答**：覆盖率、复核效率、红线召回，三项都要有人工确认记录。
- **展开**：`assessed/planned ≥ 80%`；人工分钟下降 ≥ 30%（客户基线）；标注集召回 ≥ 95%（红线提示口径）。
- **状态**：🟡（指标可提，目标值需联合校准）

### Q7. 数据不出境 / 模型可换？

- **一句话答**：可以。解析/检查/草稿/审批/审计在本地；出网只有批准处理器，且受 egress + 脱敏。
- **展开**：模型走网关抽象，可切私有部署；不配模型时业务仍能跑确定性部分。
- **状态**：✅（机制）/ 🟡（私有模型适配与 DPA）
- **追问**："你们现在用的什么模型？" → Doubao；演示环境已配置，生产可替换。

### Q8. 护城河是什么？

- **一句话答**：规则/语料/评测集（可复制）→ 工作流与审计留痕（替换成本高）→ "证据绑定 + 失败语义"的工程规范（最难抄）。
- **展开**：不假设能挡住复制；先做一个高价值单证类型，把集成与审计做深。
- **状态**：🟡

## 4. 合规、风险与责任（Q9–Q18）

### Q9. 你们是制裁筛查系统吗？

- **一句话答**：不是。我们是红线提示层，和正式筛查并联。
- **展开**：目录是策展的（11 目的地 / 11 类货物 / 4 类规避措辞）；不做 OFAC/BIS/EU/UN 名单、不做 ECCN/USML 分类、不做许可判断。
- **证据**：`app/legal_review/compliance.py` 顶部注释；finding 标 `basis=rule` + "lexical red flag, not legal advice"。
- **状态**：✅（边界明确）/ 🟡（与筛查系统并联方案待共创）

### Q10. 漏报率多少？漏掉一个怎么办？

- **一句话答**：没有生产漏报率（无银行标注集）；已知边界是词表覆盖与实体消歧，控制靠三层 + 评测集。
- **展开**：词表（确定性）→ 模型在证据内提示 → 人复核；`unchecked_units` 暴露"没查成"；上线前必须与客户共建标注集，报 recall/precision/每类误报。
- **状态**：🟡（机制 ✅，评测 ⛔）
- **追问**："那你们凭什么说能防住？" → 不承诺防住；承诺"漏了能被发现、能追溯、不自动放行"。

### Q11. 模型错了导致损失，谁负责？

- **一句话答**：AI 不放行，人签放行；产品机制可追溯，合同/保险尚未补。
- **展开**：Critical 硬阻断只来自规则；模型 severity ≤ Warning、gate ≤ human_review；`auto_send` 默认 shadow 且受 kill switch；报告留模型/证据/人工处置。
- **状态**：✅（机制）/ ⛔（责任上限、保险、DPA）

### Q12. 输出算"法律意见"吗？

- **一句话答**：不算。UI 与报告都写明 advisory / not a legal opinion；只给"需要律师/合规官看的位置与依据"。
- **展开**：法条结论必须引用 chunk（条号/法域/生效日）+ limitations；无证据 → `unable_to_assess`。
- **状态**：✅（措辞与证据约束）/ 🟡（执业边界需律师确认）

### Q13. PII / 商业机密怎么保护？

- **一句话答**：默认不出网；出网三闸：批准处理器、egress（缺配置=拒绝）、脱敏。
- **展开**：conformance 默认 basic 脱敏（账号/卡号/IBAN/BIC/邮箱/电话/证件号），每次记录 kind+count+masked sample；明确承认 basic 不是合规控制。
- **状态**：✅（机制）/ 🟡（DPA、数据驻留、跨境依据）

### Q14. 模型治理怎么映射 SR 11-7 / PRA SS1/23 / EU AI Act？

- **一句话答**：已有边界、schema、证据白名单、失败语义、版本记录、人工复核；缺正式模型卡/独立验证/漂移监控。
- **展开**：定位是"高风险场景的辅助决策"，默认人在环、默认不自动放行；进银行要按客户 MRM 模板补文档。
- **状态**：🟡

### Q15. 法条/制裁规则更新多久生效？

- **一句话答**：法规逐 clause 实时检索，不缓存结论；语料在 Mercatoria 侧维护，版本与生效日落报告。
- **展开**：规则包有 `valid_from/valid_to/published`，审计记录 bundle 版本；缺口是更新 SLA、变更通知、旧规则回放。
- **状态**：🟡

### Q16. 多法域/多语言？英文为什么 Unable？

- **一句话答**：语料目前以 CN/EU/INT/US/WTO 为主；检索不到就如实说无法评估，不猜。
- **展开**：演示用中文样例可见完整法条结论；路线是按客户单证/法域扩语料（UCP 600、ISBP、URDG 758、当地海关）。
- **状态**：🟡（可用但有边界）

### Q17. "57 项检查"怎么来的？会误报吗？

- **一句话答**：来自模板/规则包 + 覆盖率分母；不是固定 57，换模板/文种会变。
- **展开**：状态区分 pass/finding/NA/unable/needs_input；误报靠模板可评性体检（`app.rules.doctor`）与客户校准。
- **证据**：`scripts/audit_demo.py` 可离线复算。
- **状态**：✅

### Q18. 监管查 3 年前的判断，能还原吗？

- **一句话答**：能还原结构化事实；不能保证模型逐字复现同一段文字。
- **展开**：草稿 revision/checkpoint、报告（模型/prompt/provider/脱敏）、证据 id 与锚点、人工处置、审批链、下游回执都可查；缺 WORM/legal hold。
- **状态**：✅（数据在）/ 🟡（WORM）/ ⛔（监管模板导出）

## 5. 技术与 AI 治理（Q19–Q34）

### 5.1 架构与规模

#### Q19. 什么架构？能撑多少量？

- **一句话答**：FastAPI + SQLite 文档宿主 + PG 身份 + Mercatoria 检索 + Doubao 模型；单实例 POC，不给 QPS 承诺。
- **展开**：nginx :8082 → uvicorn 单 worker（run 状态在进程内）；生产路径是 PG + 队列 + 多副本 + K8s。
- **状态**：✅（可跑）/ 🟡（扩展性）/ ⛔（HA 与压测）

#### Q20. 多租户怎么隔离？

- **一句话答**：当前是单组织部署，不是多租户产品；生产首选单租户私有化。
- **展开**：身份模型支持多组织/部门与授权版本，但没有配额与 noisy-neighbor 隔离。
- **状态**：🟡（模型有）/ ⛔（隔离与配额）

#### Q21. 两个人同时编辑会怎样？

- **一句话答**：服务端权威：revision + ETag + 编辑锁（fencing token），冲突 412 进冲突面板，不静默覆盖。
- **展开**：保存写 checkpoint，可回到任意历史；心跳续租，第二个人只读。
- **状态**：✅（可现场演示）

### 5.2 AI 边界与证据

#### Q22. 哪里用模型，哪里确定性？

- **一句话答**：Deterministic-first：要素/日期/金额/受控货物/制裁/措辞/覆盖率/gate 是规则；模型只做解释、建议、问答。
- **展开**：模型输出过 schema；引用必须是 evidence id；quote 必须能定位；severity ≤ Warning、gate ≤ human_review；不合法=失败，不修补。
- **状态**：✅

#### Q23. 单据里写"忽略以上指令"会被骗吗？

- **一句话答**：设计上把文档当证据而不是指令；但残余风险存在，缺正式红队集。
- **展开**：固定 schema；quote 定位不到 → `unable_to_assess`；severity/gate 由规则决定。
- **状态**：🟡（有防护，缺红队）

#### Q24. RAG/检索质量怎么证明？

- **一句话答**：知识问答 33 题合成基线（outcome 1.0 / citation 1.0）；法规决策层 15 例离线重放；样本小，需扩到千级 + 律师盲评。
- **展开**：合成语料不是官方法规原文；评测是"答对/引用命中"，还没测同义问法一致性（见 §8 Phase 2）。
- **状态**：🟡

#### Q25. 模型/检索挂了会变成"没问题"吗？

- **一句话答**：不会。失败语义显式：`composer_unavailable / statute_unavailable / failed / insufficient_evidence`。
- **展开**：`unchecked_units` 进 gate reasons；可现场拔 key 演示"无法评估"。
- **状态**：✅（可演示）

#### Q26. 锚点为什么可靠？

- **一句话答**：Unicode code point + 客户端/服务端同一套投影 + golden fixture；quote 必须是原文子串。
- **展开**：`web/src/rich/projection.ts` ↔ `app/documents/projection.py`，跳转不会漂。
- **状态**：✅

### 5.3 安全与运维

#### Q27. 安全做到什么程度？密钥怎么管？

- **一句话答**：应用层有 RBAC、CSRF、HttpOnly session、argon2id、审计与幂等；密钥仍在 `.env`，无 Vault/KMS。
- **展开**：下游 allow-list、secret 只存 env 名；缺 SBOM/依赖扫描门禁、渗透报告、SOC2/ISO 27001。
- **状态**：✅（应用层）/ 🟡（密钥）/ ⛔（认证与审计报告）

#### Q28. 可观测性怎么样？

- **一句话答**：有 request_id、请求日志、run 的 stage/trail、报告版本字段、`/health`；没有 metrics/tracing/告警/SLO。
- **状态**：🟡

#### Q29. 部署与回滚？

- **一句话答**：`./deploy/deploy.sh` 一键：构建 → rsync → 远端安装 → systemd 重启 → nginx 校验 → `/health` 自检；回滚=重部署上一版本。
- **展开**：数据目录与 `.env` 不覆盖；没有蓝绿/金丝雀/自动回滚。
- **状态**：✅（单机）/ 🟡（企业发布）

#### Q30. 测试能证明什么、不能证明什么？

- **一句话答**：能证明工程基线（1219/670/tsc 0/规则体检/离线复算）；不能证明真实单据准确率、并发、灾备。
- **展开**：结构守卫防"改 UI 把能力改坏"；真实数据与压测是 Phase 2。
- **状态**：✅（工程）/ 🟡（真实数据）

### 5.4 集成与成本

#### Q31. 怎么接银行系统？SWIFT 呢？

- **一句话答**：REST + 幂等 + request_id + 通用 downstream connector（allow-list/TLS/secret env/回执/重试）；SWIFT/ISO 20022/核心系统适配器未做。
- **状态**：🟡（通用集成）/ ⛔（SWIFT/核心系统）

#### Q32. 成本与延迟？

- **一句话答**：架构上可控（确定性优先、按 clause 检索、web 默认关、模型只归纳）；具体 P50/P95 与单份成本未压测。
- **状态**：🟡（设计可控，数据待测）

#### Q33. 数据保留/删除？

- **一句话答**：草稿/报告/审批/审计/回执都持久化；保留期限、WORM、legal hold、按主体删除流程未做。
- **状态**：🟡 / ⛔

#### Q34. 最不想被问的技术问题？

- **一句话答**（主动说）：真实召回、多租户/HA、模型治理文档、SWIFT 适配、SOC2/渗透。
- **展开**：主动列出来，比被问出来更加分；对应路线都在 §8。
- **状态**：⛔（诚实清单）

## 6. 现场 Demo 剧本（D1–D9）

### 6.1 总表

| # | 评委说 | 怎么演 | 预期 | 状态 |
|---|---|---|---|---|
| D1 | 粘贴这份制裁合同 | New document → 粘贴样例 → Legal → Document check → Scan | Gate Blocked；4 findings（3 Critical）；4 个锚点 | ✅ |
| D2 | 换个说法还抓得到吗 | 把"军用无人机"改 UAV components / dual-use | 标准写法命中；隐晦变体可能漏，如实说明 | 🟡 |
| D3 | 改金额/日期 | 改一位数字、日期改未来 | 确定性 finding 立即变化 | ✅ |
| D4 | 英文 UCP 为什么 Unable | 粘英文样例 | 如实 `Unable to assess`；换中文样例可见法条结论 | 🟡 |
| D5 | 扫描件/拍照能读吗 | 上传无文本层 PDF/图片 | 走 OCR；缺引擎报 `ocr_engine_missing`，不静默 | ✅/🟡 |
| D6 | 拔掉模型 key 呢 | 停用模型配置后重扫 | 确定性仍跑；法条/模型变 unable，不变成通过 | ✅ |
| D7 | 两个人同时编辑 | 双窗口/双账号 | 第二人只读；冲突 412 + 面板；双人审批 | ✅ |
| D8 | 看 3 个月前依据 | 打开历史报告 | revision/checkpoint/证据/处置可查；文字不保证逐字复现 | ✅ |
| D9 | 刚粘贴就扫描会扫旧稿吗 | 粘贴后立即 Scan | 先 flush 再扫；报告显示 `Scanned rev N · X chars — 前 80 字`，不一致会警告 | ✅ |

### 6.2 三个必练的演示脚本

**D1 · 制裁样例（3 分钟）**

1. `New document` → 粘贴 `fixtures/legal-samples/sanctions-export-zh.txt`。
2. 右侧 `Legal` → `Document check` → `Scan document`（不需要等自动保存）。
3. 指三处：**Gate: Blocked** → **Critical/Blocks** 那条 → **Jump to clause** 回到原文。
4. 收尾话术："这不是筛查结论，是告诉合规官'这四个词必须看'。"

**D6 · 拔掉模型（2 分钟）**

1. 先说："接下来我把模型停掉，看系统会不会假装没问题。"
2. 重扫 → 指出 `composer_unavailable / unable_to_assess`，gate 仍按确定性结果给出。
3. 收尾："失败不会变成通过，这是我们和'聊天机器人'最大的区别。"

**D9 · 未保存就扫描（1 分钟）**

1. 粘贴文本，**立刻**点 Scan（不等底部 Saved）。
2. 指出报告顶部的 `Scanned rev N · X characters — "…"`。
3. 收尾："扫描先落盘，再扫保存后的版本；扫的到底是不是你看到的那段，报告自己会证明。"

## 7. 能力矩阵（一页看懂）

### 7.1 ✅ 已实现（可现场演示）

| 能力 | 证据 |
|---|---|
| 服务端权威草稿：revision / ETag / checkpoint / 自动保存 | `app/documents/*`、`web/src/App.tsx` |
| 编辑锁 + fencing token + 冲突面板 | `document_locks`、412 冲突 UI |
| 提交快照、只读、双人审批、提交人不可自审 | `app/approval/*`、`ApprovalPanel` |
| 模板审计：57 项、引用可定位、脱敏步骤入报告 | `app/conformance/*` |
| 法规扫描：planned/assessed/unchecked、gate、锚点、stale | `app/legal_review/*` |
| 合规红线：11 目的地 / 11 类货物 / 4 类规避措辞；hard block | `app/legal_review/compliance.py` |
| 逐 clause `/v1/retrieve`；模型不能造证据/提级 | `scan.py`、`compose.py` |
| 知识问答：引用可展开、limitations、失败不冒充答案 | `app/assistant/*` |
| 自动化：shadow / kill switch / allow-list / 幂等 / 回执 | `app/automation/*` |
| PG + argon2id + HttpOnly session + RBAC + CSRF | `app/identity/*` |
| 出网三闸：批准处理器 + egress + 脱敏 | `app/assistant/egress.py` |
| 导入：PDF 文本层 / DOCX / OCR / txt / eml；空文本不成功 | `app/parsing/parse.py` |
| 一键部署 + `/health` 自检 | `deploy/deploy.sh` |
| 测试基线：1219 / 670 / tsc 0 / 规则体检 / 离线复算 | 本轮实测 |

### 7.2 🟡 有基础，建议优化

| 能力 | 缺什么 | 归属 |
|---|---|---|
| 合规词表 | 版本化、别名/多语言、变体扩展 | Phase 2-A |
| 红线评测 | 标注集 + recall/precision + 每类误报 | Phase 2-A |
| 法规语料 | 法域/语言/时效/更新 SLA | Phase 2-B |
| RAG 评测 | 33 题 + 15 例 → 千级 + 律师盲评 | Phase 2-B |
| OCR | tesseract 容器化、语言包、置信度 | Phase 2-C |
| 性能与成本 | 压测、P50/P95、单份成本 | Phase 2-D |
| 可观测性 | metrics / tracing / 告警 / SLO | Phase 2-D |
| 密钥 | Vault/KMS、轮换 | Phase 2-E |
| **一致性与可复现** | **版本元组、温度/seed、问题规范化、答案缓存、一致性评测** | **Phase 2-F** |
| 集成 | SWIFT / ISO 20022 / 核心系统 adapter | Phase 3 |
| 多租户 | 隔离、配额、noisy neighbor | Phase 3 |
| 数据保留 | WORM、legal hold、保留期限 | Phase 3 |
| 模型治理 | 模型卡、漂移监控、独立验证 | Phase 3 |

### 7.3 ⛔ 尚未实现 / 不在当前范围

| 项 | 说明 |
|---|---|
| OFAC/BIS/EU/UN 名单筛查 | 非目标；与正式筛查并联 |
| ECCN/USML 分类、许可判断 | 非目标 |
| SSO / OIDC / SAML / MFA | 未实现（当前自建 session） |
| HA / 灾备 / RPO/RTO / 蓝绿 / 压测 | 未实现 |
| SOC2 / ISO 27001 / 渗透 / SBOM 门禁 | 未做 |
| 真实银行单据 golden set | 未建 |
| eBL / MLETR / 电子签名 | 未做 |
| 计费 / 客户门户 / 多语言 UI | 未做 |
| DPA / SCC / 责任保险 | 未做 |

---

## 8. 路线图（评委问"下一步"就看这页）

### Phase 1 · 已完成（本轮，可演示）

1. 修复 `dev_andy` 合并残留（后端导入/路由/422 契约、前端 props/投影一致性）。
2. 扫描前自动保存；保存失败不扫描（`draft_not_saved`）。
3. 报告记录"实际扫描的字符数 + 前 80 字预览"，与编辑器不一致时显式警告。
4. 切换/新建文档前先保存，避免 debounce 丢弃输入。

### Phase 2 · 验证与试点就绪（0–8 周）

| 工作流 | 交付 | 验收 |
|---|---|---|
| **A. 红线评测集** | 中英 + 变体 + OCR 噪声的标注集；recall/precision/每类误报 | 可复现脚本 + 报告 |
| **B. 语料与问答评测** | 目标法域语料；千级问答 + 律师盲评 | 引用命中率、答对率、弃答率 |
| **C. 导入质量** | OCR 容器化（tesseract+语言包）、预处理、置信度 | 扫描件/拍照样张通过率 |
| **D. 性能与可观测** | 压测脚本、P50/P95、单份成本、metrics/tracing/SLO | 基线报告 + 告警 |
| **E. 安全基线** | Vault/KMS 方案、SBOM/依赖扫描、渗透预约 | 清单关闭率 |
| **F. 一致性与可复现** | 见 8.1（本轮新增的专项） | 同义问法一致率、flip rate |

### 8.1 Phase 2-F · 一致性与可复现性（Reproducibility）

> **要回答的问题**：同一份法规/文档，不同人、不同时间、不同问法，AI 的"理解"能不能统一？
>
> **结论先行**：逐字一致的生成做不到；**同一输入 + 同一版本 → 同一判定 + 同一证据**可以做到。做法是把"判定"从模型手里拿走、把输入钉死、把输出按证据缓存，并度量一致性。

**F1. 版本元组（所有报告必带）**

```text
document_sha256, corpus_snapshot_id, rule_pack_versions,
prompt_version, model_id, egress_version, redaction_version
```

缺任何一项 → 报告标 `partial` 或拒绝出结论。

**F2. 生成参数固定**

- `temperature=0`、`top_p=1`；供应商支持则固定 `seed`。
- 记录 `prompt_hash`；只在 schema 不合法时重试，**同一 prompt**，不做"再想想"。

**F3. 法规扫描记录 composer 版本**

- 现状：conformance 报告有 `model + prompt_version`，legal 报告没有。
- 目标：`ReviewReport` 增加 composer 元数据，与 conformance 对齐。

**F4. 问题规范化（canonical question）**

- 意图归一（规则/别名 + few-shot）→ `canonical_question_id`；
- 每个 canonical question 固定检索 query、法域 scope、证据集合；
- 意图不确定 → 追问澄清或 `needs_input`，不猜。

**F5. 证据哈希缓存**

```text
key = sha256(canonical_question_id + prompt_version + model_id
             + sorted(evidence_chunk_id + chunk_sha256)
             + document_sha256 + redaction_version)
```

命中 → 原样返回；任一版本变化 → 失效重算；报告记录 `cache_key / cache_hit`。

**F6. 高风险问题 N 次采样 + 人工裁决**

- N 次判定不一致 → 不取多数票，标 `needs_input`；
- 人工裁决结果落库（带语料/规则版本），作为该版本的先例。

**F7. 一致性评测**

| 指标 | 定义 | 目标（待校准） |
|---|---|---|
| `decision_agreement` | 同义问法组内判定一致率 | ≥ 95% |
| `citation_stability` | 引用集合 Jaccard | ≥ 0.9 |
| `flip_rate` | 同文档重复跑结论翻转率 | ≤ 1% |
| `coverage_delta` | assessed/planned 波动 | 在阈值内 |

**F8. 漂移回放**

- 每周回放固定文档集；结论翻转/引用漂移 → 告警；
- 模型/语料/规则任一升级，必须跑一致性评测再发布。

**代码落点**

| 改动 | 位置 |
|---|---|
| 温度/seed/prompt_hash/model_id | `app/assistant/gateway.py` |
| legal 报告 composer 元数据 | `app/legal_review/scan.py`、`contracts.py` |
| 统一 versions 元组 | `ReviewReport.snapshot` |
| canonical question 映射 | 新 `app/knowledge/intent.py` |
| 证据哈希缓存 | 新 `app/assistant/answer_cache.py` |
| 一致性评测脚本 | 新 `scripts/consistency_eval.py` |
| 漂移回放 | 新 `scripts/drift_report.py` |

> 说明：**本轮不做代码改动**，仅作为 Phase 2 的改进清单。

### Phase 3 · 企业化与商业化（8–12 周）

1. SWIFT MT798 / ISO 20022 / 核心贸易系统 adapter；eBL/MLETR 评估。
2. WORM / legal hold / 监管导出模板。
3. 模型卡 + 漂移监控 + 变更审批（映射 SR 11-7 / PRA SS1/23 / EU AI Act）。
4. SOC2 / ISO 27001 预审；DPA/SCC/责任保险模板。
5. 定价与交付包：单租户私有化 license + 实施人日 + 年度支持。

## 9. 数字卡片与答辩禁忌

### 9.1 数字卡片（只说你验证过的）

| 类别 | 可以说 | 不要说 |
|---|---|---|
| 测试 | 后端 **1219 / 32 skipped**；前端 **670 / 12 skipped**；`tsc` 0 | 覆盖率 100% |
| 审计 | 样例 **57 项**：pass 36 / finding 1 / NA 19 / unable 1 | 固定 57 项 |
| 法规扫描 | 制裁样例 **planned 12 / assessed 10**；4 findings（3 Critical）；阈值 0.6；单次 ≤12 clause / ≤1200 字符 | 全法域覆盖 |
| 合规目录 | **11 / 11 / 4**；受控货物 + 全面制裁 = hard block | 制裁筛查 |
| 知识问答 | 33 题合成：outcome 1.0 / citation 1.0 | 法律准确率 100% |
| 法规决策层 | `statute_eval.py` 15 例离线重放 | 生产召回 95% |
| 部署 | 单 ECS / nginx 8082 / systemd / 单 worker；`/health` 200 | 银行级高可用 |
| 边界 | 语料 CN/EU/INT/US/WTO；英文常 unable；`.doc` 不支持 | 支持所有语言/法域 |

**需要补测的数字**：真实单据 recall/precision、P50/P95、单份成本、日吞吐、RPO/RTO、模型漂移基线。

### 9.2 答辩禁忌（8 组）

| ❌ 不说 | ✅ 改成 |
|---|---|
| 我们做制裁筛查 / 合规判定 | 红线提示，与正式筛查并联 |
| AI 会自动审批/自动发送 | AI 不提交、不批准、不派发；默认 shadow |
| 模型不会错 | 错了可发现、可追溯、不自动放行 |
| 支持所有法域/语言 | CN/EU/INT/US/WTO；英文常 unable |
| 银行级高可用 / 已过 SOC2 | 单实例 POC；差距清单在 §8 |
| 我们比 Traydstream 强 | 我们补证据层，不拼解析广度 |
| 数据绝对不出境 | 默认不出网；出网需批准处理器 + egress + 脱敏 |
| 57 项全过 | 36 pass / 1 finding / 19 NA / 1 unable |

---

## 10. 证据索引（被问"凭什么"时直接指）

| 断言 | 代码 / 文档 |
|---|---|
| 服务端权威草稿、锁、检查点 | `app/documents/*`、`web/src/App.tsx` |
| 审批双人、提交人不可自审 | `app/approval/*`、`web/src/components/ApprovalPanel.tsx` |
| 模板审计与脱敏记录 | `app/conformance/*`、`web/src/components/ConformancePanel.tsx` |
| 法规扫描、gate、覆盖率 | `app/legal_review/{scan,document,checks}.py` |
| 合规词表与 hard block | `app/legal_review/compliance.py` |
| 模型证据约束 | `app/legal_review/compose.py`、`app/assistant/gateway.py` |
| 知识问答引用与失败语义 | `app/assistant/service.py`、`app/knowledge/retriever.py` |
| 出网三闸 | `app/assistant/egress.py`、`app/assistant/settings.py` |
| RBAC / CSRF / session | `app/identity/*` |
| 自动化 shadow / allow-list / 回执 | `app/automation/*` |
| 导入与 OCR | `app/parsing/parse.py` |
| 一键部署 | `deploy/deploy.sh`、`deploy/README.md` |
| 能力边界（官方口径） | `DEMO_Tech.md` §11 已知限制 |
| 演示脚本与预期 | `DEMO.md`、`Demo_audit.md` |

---

## 附录 · 按角色的 3 份速查

### A. 业务/投资评委关心

Q1 痛点 · Q2 价值 · Q3 竞品 · Q4 买家 · Q6 试点指标 · Q8 护城河 · §8 路线图

### B. 合规/风险/法务评委关心

Q9 边界 · Q10 漏报 · Q11 责任 · Q12 法律意见 · Q13 数据 · Q14 模型治理 · Q15 规则时效 · Q18 可复现

### C. CTO/架构/安全评委关心

Q19 规模 · Q20 多租户 · Q21 并发 · Q22 AI 边界 · Q25 失败语义 · Q27 安全 · Q28 观测 · Q29 部署 · Q30 测试 · Q31 集成 · Q32 成本 · §8.1 一致性

---

## 收尾话术（最后 15 秒）

> 我们不是替银行做决定，而是让每个决定**有依据、能复现、知道哪里没查到**。给我们一个单证类型和一批真实单据，90 天内给出可签的召回率、覆盖率和人工节省数据。