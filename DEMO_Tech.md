# DEMO_Tech · smart-edit 技术说明

> 读者：评审、架构/安全评审、以及接手工程的同事。
> 与 `DEMO.md`（8 分钟演示脚本）互补：这里讲**系统怎么搭、AI 放在哪里、边界如何被代码保证**。
> 文中数字取自 **2026-11-22** 本地实际运行（后端 `pytest`、前端 `vitest`）。

**阅读路径**：`§1 架构` → `§4 AI 使用` → `§5 AI 呈现` → `§6 数据/证据` → `§7 安全边界` → `§9 测试`。

---

## 0. 一句话

**一个 server-authoritative 的贸易金融文档工作台**：React 控制台负责编辑与解释，FastAPI 服务端持有一切状态（草稿版本、编辑锁、提交快照、双人审批、派发回执）；**确定性规则决定“能不能”，批准过的模型只负责“解释与建议”**，每条 AI 结论都必须带可定位的证据，且永远不代替人做批准/发送。

---

## 1. 架构总览

```text
                         ┌─────────────────────────────────────────────┐
 Browser (React 18/TS)   │ 三栏工作台 · Tour 引擎 · AI 等待框 · Stepper │
 ───────────────────────▶│ 只持有视图状态；所有写操作走 HTTP API      │
                         └───────────────┬─────────────────────────────┘
                                         │ nginx :8082（静态 + /api 反代）
                                         ▼
                         ┌─────────────────────────────────────────────┐
 FastAPI (uvicorn :8000) │ /auth /documents /approvals /assistant      │
                         │ /conformance /legal /automation /activity   │
                         └───┬───────────────┬───────────────┬─────────┘
                             │               │               │
                 SQLite host.db      PostgreSQL identity   outbox_events
              (drafts/locks/        (users/orgs/roles/     (submission /
               submissions/          sessions/activity)     approval 事件)
               automation/jobs)             │                    │
                             │               │                    ▼
                             │               │        ┌──────────────────────┐
                             │               │        │ automation worker    │
                             │               │        │ 每 5s：plan → 执行  │
                             │               │        └──────────┬───────────┘
                             │               │                   │ allow-list HTTP
                             ▼               ▼                   ▼
                    assistant.db /     Ark Doubao          downstream echo
                    conformance.db     Responses API        (127.0.0.1:18080)
                    (runs/reports)     + statute / RAG
```

**五条独立链路**（互不共享状态，只在文档 ID 与快照上对齐）：

| 链路 | 触发 | 产物 | 是否异步 |
|---|---|---|---|
| 编辑 → 提交 → 双人审批 | 人工 | revision + sha 快照、审批步骤 | 否（同步 API） |
| 模板审计（conformance） | 人工点 Run | 报告：逐条判定 + 引用 + 覆盖率 | 是（run + 轮询） |
| 知识问答（RAG） | 人工提问 | 回答 + citations + limitations | 是（run + 轮询） |
| 法规扫描（legal） | 人工 Scan | findings + gate + 覆盖率 | 是（run + 轮询） |
| 自动化（automation） | 终审通过 / 人工 | 规则、job、派发回执 | 是（worker 5s） |

---

## 2. 技术栈与代码地图

| 层 | 选型 | 目录 |
|---|---|---|
| 前端 | React 18 + TypeScript + Vite + TipTap | `web/src` |
| 后端 | Python 3.12 + FastAPI/uvicorn + pydantic | `app/api`、各领域包 |
| 文档宿主 | SQLite（单 writer） | `app/documents`、`data/host.db`（部署） |
| 身份/组织 | PostgreSQL + argon2id + HttpOnly 会话 | `app/identity` |
| 知识/RAG | 词法检索 + 可选 RAG/法规/Web 适配器 | `app/assistant`、`app/knowledge` |
| 模板审计 | 确定性必填检查 + Doubao 逐条判定 | `app/conformance` |
| 法规扫描 | 计划 → 确定性规则 → 逐条检索 → 模型归纳 | `app/legal_review` |
| 自动化 | 模板/连接器/规则/job/回执 + worker | `app/automation` |
| 部署 | nginx + systemd（API / worker） | `deploy/` |
| 测试 | pytest / vitest / Playwright | `tests/`、`web/src/**/*.test.*`、`web/e2e` |

前端关键目录：

```text
web/src/
  tour/            # 数据驱动导览（catalog + tours + TourProvider + 锚点守卫）
  components/      # AiWaitBox、ApprovalStepper、DeliveryStepper、各业务面板
  api/             # 每个能力的 typed client（fetch 封装）
  styles.css       # 设计令牌 + HSBC Create 主题层（末尾集中覆盖）
```

---

## 3. 文档主链路（为什么说 server-authoritative）

1. **草稿**：每次保存 `revision + 1`，服务端计算 `text_sha256`；前端只显示服务端返回的 revision。
2. **编辑锁**：`document_locks` 带 `lease_until` 与 `fencing_token`；提交时校验 lock 归属、租约、fencing token，过期锁可被回收。
3. **提交**：`document_submissions` 冻结 `draft_id + revision + sha + text + content_json`；之后草稿只读。
4. **审批**：`approval_requests` 两段（first → second）；`decide_approval` 校验阶段、revision、**提交人不能审自己**；第二步通过才 `approved`。
5. **返回/拒绝**：回到可编辑，但重新提交必须**新快照**（旧 job 不会重发）。
6. **派发**：审批事件进 outbox，worker 只从**快照文本**构造下游 payload（不读实时草稿）。

> 设计后果：审批、审计、派发看到的都是同一个 `(revision, sha)` 对象；任何“文档后来改了”的情况都会以 stale 形式显式失败，而不是悄悄用新内容。

## 4. AI 使用全景

### 4.0 设计原则（先于任何模型调用）

1. **Deterministic-first**：能判定的先判定（必填字段、日期一致性、受控货物、金额/币种格式），模型不背这些。
2. **Evidence-first**：模型只能说“我引用的证据支持这一点”；没有引用 = 不能算通过。
3. **Human decides**：模型不提交、不批准、不派发；所有对外动作由人触发。
4. **Failure is not a pass**：超时、无模型、无证据、schema 不合法，都显式标为 `unable_to_assess` / `insufficient_evidence` / `needs_attention`，绝不降级成“没问题”。
5. **Unknown policy denies**：出网策略配置缺失时一律拒绝，而不是默认放行。

### 4.1 能力矩阵

| 能力 | 模型 / 检索 | 输入（最小化） | 模型**可以**做 | 模型**不可以**做 | 失败语义 |
|---|---|---|---|---|---|
| 模板审计 `conformance` | Doubao（Ark Responses API）+ 确定性必填检查 | 脱敏后的草稿块 + 校准配置要求 | 逐条判断是否符合；给逐字引用；给建议 | 造引用；提高严重度到 Critical；判“合规通过”；改原文 | 超时/不可用 → `unable_to_assess`；报告标 `MODEL_TIMEOUT` |
| 知识问答 `assistant` | 词法检索（默认）+ 可选 RAG HTTP + 法规 + Web（默认开，可关） | 已发布、生效、scope 允许的语料块 | 在给定 evidence id 上组织答案；声明不知道 | 引用未提供的 id；扩大 scope；把“未覆盖”说成“无问题” | `insufficient_evidence`；模型未答 → 逐字摘录证据并标注 |
| 法规扫描 `legal` | 逐条检索 `/v1/retrieve` + Doubao 归纳 + 确定性规则 | 计划中的 clause 清单 + 检索引擎返回块 | 在规则目录内解释风险；引用 chunk | 提高 severity/gate；把未计划条款算作已检查；替代硬阻断规则 | 无 composer → `composer_unavailable`，gate 仍由规则+覆盖率得出 |
| 自动化变量 `automation` | 确定性变量扫描 + 可选 Doubao | 模板文本 | 建议字段（必须带逐字 quote） | 自动落库；未经确认参与映射；自行派发 | 建议失败 → 无建议，模板仍可手工确认字段 |

### 4.2 模板审计（conformance）的数据流

```text
POST /conformance/reviews
  → 校验 draft_id + revision + sha（stale 直接拒绝）
  → 确定性层：extraction profile → 必填字段存在性（不调用模型）
  → 脱敏（SMART_EDIT_CONFORMANCE_REDACT，默认 basic）：
      账号/卡号/IBAN/BIC/邮箱/电话/证件号 → [redacted]，保留块索引
  → Doubao：逐 requirement 判定，返回 {status, quote, reason}
  → 校验：quote 必须能在（脱敏后的）块里定位；不能定位 → unable_to_assess
  → 聚合：assessed / not_assessed / counts / outcome / limitations
  → 持久化 report：config id+version、revision、sha、prompt_version、model、redaction steps
```

报告里同时出现：**结论**、**覆盖率**、**每条引用**、**脱敏步骤（kind + count + masked sample）**、**provenance**。
前端把引用做成 “Show in document / Jump to block”，把限制写成可见文字，而不是脚注。

### 4.3 知识问答（RAG）

- 默认检索器是**确定性词法检索**（`app/knowledge/retriever.py`）：先按 published / effective / scope 过滤，再打分；检索器无权扩大集合。
- 可选 `RagHttpAdapter`（`SMART_EDIT_ASSISTANT_RAG_ENDPOINT`）、法规适配器（`MERCATORIA_*`）、Web fallback（默认开但可关；general web 使用**唯一一个只读 web_search 工具**）。
- Composer（Doubao Responses API）只收到 evidence bundle；输出必须通过 `Answer` schema；不合法的输出视为失败，不做“尽力而为”的修补。
- 回答持久化 `assistant_runs / assistant_messages / assistant_citations`；引用可展开到原文；答案带 limitations（如“仅解释已发布来源，不构成法律意见”）。

### 4.4 法规扫描（legal review）

```text
plan（clause 是分母）→ 确定性 checks（日期/要素/一致性/标记词）
  → 每个 clause 调 /v1/retrieve（不用 /v1/chat，避免服务端 LLM 不可审计）
  → Doubao 仅在“规则目录 + 检索块”内归纳；severity ≤ Warning
  → gate = f(findings, coverage)：Critical 硬阻断只来自确定性规则
```

- 未计划/未检索的 clause 计入 `unchecked_units`，显示为“未检查”，永不显示“通过”；
- `SMART_EDIT_LEGAL_WEB_DEFAULT` 默认 **off**（Web 慢且不可验证）；
- 无 composer 时返回 `composer_unavailable`，但 gate 依然可由确定性结果得出。

### 4.5 自动化里的 AI

- 变量建议：确定性扫描（`{{label}}`、`____`、`Label: value`）先给出候选；Doubao 只做补充，**每条必须带原文 quote**；
- 建议默认**全选但不落库**：人点 Confirm 才写入服务端模板；
- 映射只允许使用**已确认**变量；缺必填 → Send 禁用；
- 派发：一条规则 → 一个 job → 一次 allow-list HTTP；密钥只存环境变量名，从不入库/回显；规则默认 `shadow`，`auto_send` 还受全局 kill switch 约束。

---
## 5. AI 如何被“呈现”（UI 层）

这一层不是装饰，而是把 **AI 的不确定性**变成**可理解的等待与可检查的证据**。

### 5.1 统一的等待框（`AiWaitBox`）

两种密度，同一套视觉语言（六边形脉冲 + 三点呼吸 + 真实 elapsed）：

| 变体 | 用在哪里 | 内容 | 明确不显示 |
|---|---|---|---|
| `card` | 模板审计、Knowledge、Legal、Automate 的“Find variables” | 标题、当前阶段/`done/planned`（**仅服务端真实上报**）、脱敏/边界 hint、可选 Stop waiting | 任何无数据支撑的百分比 |
| `inline` | 导览气泡里的 `until` 等待 | 一行：六边形 + 原因 + 思考点 + elapsed | 伪造进度阶段 |

配套 `useElapsedMs`：100ms tick、停止即归零；`prefers-reduced-motion` 下关闭动画。

### 5.2 证据的呈现，而不是“结论一句话”

- **引用可跳转**：审计/Legal 的每条 quote 都能定位到草稿块（Show in document / Jump to clause）；
- **覆盖率显性化**：`assessed / planned`、`unchecked_units`、`not_assessed` 与结论并列；
- **脱敏步骤可见**：kind + count + masked sample，永远不展示原值；
- **provenance 常驻**：config id/version、revision、sha、prompt_version、model；
- **模型身份标注**：摘要写 “model-written”，不让人误以为是确定性结论；
- **限制说明**：语料为合成、非法律意见、未覆盖 ≠ 无问题。

### 5.3 人的链路 vs AI 的链路

- 审批链：`Draft → Submitted → Bank Operations → Compliance → Approved`（文档头紧凑六边形 + 横幅完整步骤）；
- 交付链：同一模型延伸到 `Delivered`，`shadowed` 用琥珀“held”而不是绿色完成；
- AI 永远不出现在“批准人”位置；`Human decides` 是助手面板的固定标识。

### 5.4 导览把“怎么用 AI”讲成可复现的动作

- 数据驱动 tour（`web/src/tour`）：步骤 = 目标锚点 + 可选真实动作 + 可选状态门槛；
- Watch me 会**真的点击**（选模板、Find variables、Confirm、Reset mapping、Dry-run、展开运行时间线），
  但 **永远不点 Send**（守卫测试断言 action 不得匹配 `send`）；
- 气泡里有整条导览进度轨、自动阅读倒计时条（暂停变灰）、等待时的 inline AI 状态；
- Automation tour 在弹框里显示 `Bank Operations only` chip，避免无权限会话跑到一半被跳过。

### 5.5 不打断工作台

- AI 永远在右侧面板/气泡里，文档与版本栏保持可见；
- 长任务用轮询 + 可离开（返回后读 run/report），不做全屏 loading；
- 空状态给出**唯一下一步**（例如 Rules 空 → `Create shadow rule`，Runs 空 → `Refresh runs`）。

---

## 6. 数据、证据与幂等

### 6.1 存储分工

| 存储 | 内容 | 备注 |
|---|---|---|
| `data/host.db`（SQLite） | documents / drafts / locks / submissions / approval_requests+steps / automation_templates / connectors / mappings / rules / jobs / job_events / dispatches | 单 writer；worker 与 API 同库 |
| `runs/assistant.db`（部署用 `SMART_EDIT_ASSISTANT_DB` 指定） | snapshots / sessions / messages / runs / citations / knowledge_sources / versions / chunks / outbox | RAG 与问答证据 |
| `runs/conformance.db` / `runs/legal.db` | conformance runs / reports / idempotency；legal runs / reports | 报告与快照绑定 |
| PostgreSQL | users / orgs / memberships / roles / role_permissions / sessions / activity | 身份与 RBAC |

### 6.2 幂等与重放

- 提交/审批事件进 `outbox_events`；worker 消费后标记 delivered；
- 自动化 job 的 `idempotency_key = auto:{rule_id}:{submission_id}`：同一提交重复消费不会重复发；
- 同一 connector 被多条规则命中时，一次提交只发一次；
- 重试策略：仅 5xx / timeout / transport 可重试，最多 3 次，退避 60 / 300 / 1800 秒；refusal/契约错误不重试；
- conformance/assistant 也有 idempotency records，重复 POST 返回同一 run。

### 6.3 回执即证据

- 派发回执：status / status_code / latency / dispatch_id / response excerpt（可过滤）；
- job 时间线：`queued → sending → sent / needs_attention / cancelled`；
- shadow job 保存“本来会发的 url/body/issues/refusal”，所以“只模拟”本身也是可审计产物。

---
## 7. 权限与安全边界

### 7.1 角色（PG RBAC，`app/identity/permissions.py`）

| 角色 | 关键权限 | 典型用途 |
|---|---|---|
| `applicant` | document.read/create/edit/lock/export、assistant.use、approval.submit | 起草与提交；**看不到 Automation** |
| `bank_ops` | + audit.read、automation.view/configure/dispatch/audit、approval.first | 一审 + Automation 后台 |
| `compliance` | + automation.view/audit（**无 configure/dispatch**）、approval.second | 二审；只能看规则，不能改/发 |
| `org_admin` | 全部权限 | 组织管理 |
| `dept_admin` | 部门范围 + automation 全套 | 部门管理员（不能改组织级规则） |

前端直接把这些能力映射成 **tab 可见性 / 按钮禁用 / 导览跳过**；服务端每个端点再校验一次，不信任前端。

### 7.2 AI 出网的三道闸

1. **批准处理器**：`SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED=true` 才允许调用 Doubao；否则走 fixture/降级。
2. **Egress policy**（`config/knowledge.json` → `knowledge.sample.json` → `egress.yaml` → **deny**）：
   - 决定 `allow / redact / deny`；无法解析配置 = 拒绝；
   - 每次脱敏都记录，UI 可以展示“实际会发什么”。
3. **模块级脱敏**：conformance 的 `SMART_EDIT_CONFORMANCE_REDACT=basic|off`（默认 basic）；文档明确说明它**不是**合规控制，权威仍是 egress + 批准处理器。

### 7.3 自动化的“最后一公里”保护

- 连接器必须命中 **allow-list host**（`SMART_EDIT_AUTOMATION_ALLOWED_HOSTS`）；http 还需显式 `SMART_EDIT_AUTOMATION_ALLOW_HTTP`；
- 密钥只存**环境变量名**，不写库、不回显；
- 规则默认 `shadow`；提级是显式、写审计的治理动作；
- 全局 **kill switch**（`SMART_EDIT_AUTOMATION_AUTO_SEND`）关掉时，`auto_send` 退化为 shadow；
- `needs_review` 必须人工 Release 才会发；retry/cancel 都有状态约束；
- 双人审批 + 提交人不可自审 + 快照冻结。

### 7.4 会话与身份

PG 模式：argon2id 密码、HttpOnly + SameSite=Lax 会话 cookie、服务端 session 记录；前端只拿 profile/permissions，不拿 token。

---

## 8. 部署与运行

```text
nginx :8082
  /            → /opt/smart-edit/web/dist（Vite 产物，SPA fallback）
  /api/*       → 127.0.0.1:8000 (uvicorn)

systemd:
  smart-edit.service             uvicorn app.api.main:app
  smart-edit-automation.service  python -m app.automation.worker --interval 5
```

| 环境变量（示例键名） | 作用 | 默认/演示值 |
|---|---|---|
| `SMART_EDIT_AUTH_MODE` | `pg` / fake | 部署为 `pg` |
| `SMART_EDIT_DATABASE_URL` | PG 身份库 | 部署环境注入 |
| `SMART_EDIT_HOST_DB` | SQLite 宿主库 | `/opt/smart-edit/data/host.db` |
| `SMART_EDIT_ASSISTANT_DB` | 问答/知识库 | 默认 `runs/assistant.db`（部署可覆盖） |
| `SMART_EDIT_ASSISTANT_MODEL` / `_API_KEY` / `_BASE_URL` | Doubao（Ark） | 评测环境已配置 |
| `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED` | 批准处理器闸门 | `true` 才能真实调用 |
| `SMART_EDIT_ASSISTANT_RAG_ENDPOINT` | 可选 RAG 服务 | 未配置则用词法检索 |
| `SMART_EDIT_STATUTE` / `MERCATORIA_BASE_URL` / `MERCATORIA_API_TOKEN` | 法规检索 | 启用即必须给全，否则启动失败 |
| `SMART_EDIT_CONFORMANCE_REDACT` | `basic` / `off` | 默认 `basic` |
| `SMART_EDIT_LEGAL_WEB_DEFAULT` | Legal 默认 Web | 默认 `false` |
| `SMART_EDIT_AUTOMATION_ALLOWED_HOSTS` / `_ALLOW_HTTP` | 派发 allow-list | `127.0.0.1` + http |
| `SMART_EDIT_AUTOMATION_AUTO_SEND` | 全局发送开关 | 默认开；关 = 全部退化 shadow |

运维入口：

```bash
./deploy/deploy.sh --no-build     # 复用 web/dist 同步 + 远端安装/重启
scripts/seed_automation_demo.py   # 真实提交+双审+shadow 规则+shadowed job
curl http://<host>:8082/health    # 反代与 API 健康
systemctl status smart-edit smart-edit-automation
```

> 注意：`remote-setup.sh` 只在 `SMART_EDIT_ENABLE_AUTOMATION_WORKER=1` 时重启 worker；改了 worker 代码要显式
> `systemctl restart smart-edit-automation`（本次交付已在部署脚本后补做）。

---

## 9. 测试与质量门

| 层 | 命令 | 结果（2026-11-22 实际运行） |
|---|---|---|
| 后端 | `.venv/bin/python -m pytest tests -q` | **968 passed, 28 skipped**（60.3s） |
| 前端类型 | `npm --prefix web run typecheck` | 通过 |
| 前端单测 | `npm --prefix web run test` | **656 passed, 12 skipped**（83 files；3 个 e2e 文件按配置跳过） |
| 浏览器 E2E | `npm --prefix web run e2e`（需 Playwright） | 桌面/窄屏/诚实性三套工程；本次用 Chrome 冒烟 |
| 规则体检 | `.venv/bin/python -m app.rules.doctor` | 退出码即门禁 |
| 计划/覆盖/闸门 | `.venv/bin/python scripts/audit_demo.py` | 不调用模型，可离线复算 |

**结构性守卫测试**（防“改 UI 把能力改坏”）：

- `web/src/tour/tourAnchors.test.ts`：导览用到的每个 `data-tour` 必须在源码存在；automation 导览每步必须有 RBAC 守卫、且 action 不得匹配 `send`；
- `web/src/tokens.test.ts`：状态永远“文字 + 颜色”，未知值不冒充已知；
- `tests/test_honesty_*`：无 provider 时不得返回“通过”；`tests/test_conformance_*`：无引用不得算 assessed；
- `tests/test_automation_*`：shadow/needs_review/auto_send、幂等、回滚、allow-list。

本次 UI 改造还用 **Playwright + 本机 Chrome** 对线上做了视觉与交互冒烟：
审批 stepper、交付链、Delivery 表、启动器模式卡、AI 等待框、导览自动操作（23/23 步）均已实拍核对。

---
## 10. 演示入口：AI 在哪里被看见

### 10.1 导览（顶栏 Take the tour）

| Tour | 深链 | 重点 |
|---|---|---|
| Core loop | `?tour=core` | 文档 → 模板审计 → 导出 → 提交 → 交接 |
| Audit deep dive | `?tour=audit` | 严格配置、引用、脱敏、导出 |
| Legal risk scan | `?tour=legal` | 制裁样例 → Document check → 闸门/覆盖 |
| Two-person approval | `?tour=approval` | 双人链、职责分离 |
| Lifecycle 1–3 | `?tour=lifecycle-*` | 三种角色窗口的接力 |
| Automation workbench | `?tour=automation` | **真操作**：模板 → AI 字段 → 映射 → Preview → Rules dry-run → Runs 时间线 → Sandbox；**Send 只讲不点** |

### 10.2 五个“看 AI 在工作”的瞬间

1. **模板审计**：Audit → Run template audit —— 卡片式等待框（真实 stage/进度 + elapsed），随后报告展示引用、覆盖率、脱敏步骤；
2. **知识问答**：Knowledge → 输入问题 —— 卡片式等待框（真实 run 阶段列表），回答带 citations 与 limitations；
3. **法规扫描**：Legal → Document check → Scan —— 阶段文案 + elapsed，报告带 gate、coverage、anchors；
4. **Automate 字段**：Find variables with AI —— “Doubao is reading the template”，确认前不落库；
5. **导览等待**：任意 `until` 未满足 —— 气泡内 inline 六边形脉冲 + elapsed。

演示数据（真实提交 + 双审 + shadow 规则 + shadowed job）：

```bash
cd /opt/smart-edit && set -a && . ./.env && set +a
.venv/bin/python scripts/seed_automation_demo.py
```

账号：`applicant` / `bankops` / `compliance`（密码见 `DEMO.md`）。
Automation 相关界面需要 **Bank Operations**（或组织管理员）。

### 10.3 5 分钟技术走查建议

1. `pytest tests -q` / `npm --prefix web run test` —— 看门禁；
2. `scripts/audit_demo.py` —— 不调模型，复算 audit 计划/覆盖/闸门；
3. 打开一次模板审计，检查报告里的 `revision + sha + prompt_version + redaction steps`；
4. Runs 里看一条 `shadowed` job 的 request/response 与时间线；
5. 关掉 `SMART_EDIT_AUTOMATION_AUTO_SEND`，把规则提到 `auto_send`，观察它退化为 shadow。

---

## 11. 已知限制与非目标（诚实清单）

1. **单组织演示**：PG 身份支持多组织/部门，但演示库是单 org（`ws_demo_01`）；不是多租户产品。
2. **SQLite 单 writer**：host.db 适合单实例 demo；生产需要换数据库与并发控制。
3. **语料是合成的**：Knowledge 的 `fixtures/knowledge/*` 为演示语料，**不是官方法规原文**；回答里明确标注。
4. **法规服务是外部依赖**：Mercatoria 不可用时 Legal 的 statute 证据缺失，结果会显式降级而不是编造。
5. **脱敏是尽力而为**：basic 模式只覆盖固定金融标识；姓名/金额/地址仍会出网；权威控制是 egress + 批准处理器。
6. **下游是本地 echo**：Automation 演示连接器指向 `127.0.0.1:18080`，不是生产集成；发送成功只证明链路与回执，不代表真实系统。
7. **审批永远是人**：AI 不提交、不批准、不派发；`auto_send` 也必须先由人配置规则并打开全局开关。
8. **浏览器不能替你换账号**：Lifecycle tour 分成三个窗口，是设计而不是缺陷。
9. **AI 不是法律意见**：所有 Legal/Knowledge 文案都声明这一点；Critical 硬阻断只来自确定性规则。
10. **UI 面向桌面演示**：窄屏有单栏降级，但三栏体验按 ≥1400px 设计。

---

## 12. 交接地图（先读这些文件）

| 主题 | 文件 |
|---|---|
| API 装配 / 路由 | `app/api/main.py`、`app/api/*.py` |
| 文档/锁/提交 | `app/documents/service.py`、`app/documents/store.py` |
| 审批状态模型（前后端共享） | `web/src/domain/approvalStatus.ts` |
| 模板审计 | `app/conformance/service.py`、`compose.py`、`redact.py`、`web/src/components/ConformancePanel.tsx` |
| 知识问答 / RAG | `app/assistant/{service,gateway,pipeline,retrieval,egress}.py`、`app/knowledge/retriever.py` |
| 法规扫描 | `app/legal_review/{scan,compose,checks,service}.py` |
| 自动化 | `app/automation/{registry,rules,jobs,worker}.py` |
| 身份/RBAC | `app/identity/permissions.py`、`store.py` |
| 导览引擎 | `web/src/tour/TourProvider.tsx`、`catalog.ts`、`types.ts`、`tours/*.ts` |
| AI 等待框 | `web/src/components/AiWaitBox.tsx`、`useElapsedMs.ts` |
| Stepper | `web/src/components/{ApprovalStepper,DeliveryStepper}.tsx` |
| 设计主题 | `web/src/styles.css`（令牌 + 尾部 HSBC Create 主题层） |
| 部署 | `deploy/deploy.sh`、`remote-setup.sh`、`nginx-smart-edit.conf`、`*.service` |
| 演示脚本 | `DEMO.md`、`DEMO_automation.md`、`scripts/seed_automation_demo.py` |

---

### 附：本文档与代码的对应原则

- 本文只描述**已实现**的行为；未实现的能力（生产多租户、真实下游、模型推进审批）明确列入 §11。
- 数字（测试数、worker 间隔、超时）均来自代码或本次实际运行；若后续改动，请同步更新本文件与 `DEMO.md`。
---