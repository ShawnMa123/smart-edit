# smart-edit 演示脚本（8 分钟）

> 一句话定位：**把客户材料变成内部系统能用的标准文件，并在生成过程中做"格式 / 业务要件 / 法规与合规"三层校验；
> 每条结论都能指回原文，查不到的会明确说"没查到"，而不是"没问题"。**

| 项 | 值 |
|---|---|
| 演示地址 | **http://59.110.213.187:8082/** |
| 演示主号 | `applicant@atlas-trade.test` / `Applicant!2026`（申请人：编辑 + 提交） |
| 一审 | `bankops@atlas-trade.test` / `BankOps!2026` |
| 二审 | `compliance@atlas-trade.test` / `Compliance!2026` |
| 管理员（备用） | `admin@atlas-trade.test` / `AtlasAdmin!2026` |
| 浏览器 | Chrome / Edge，窗口宽度 ≥ 1400px（右侧助手面板才能完整展开） |
| 建议时长 | **8:00**（下方时间轴按秒分配；Q&A 另计） |

> 文中"线上实测"数字取自 **2026-11-22** 的演示环境；模型每次措辞会不同，但**结构、计数口径、引用位置**是稳定的。

## 0. 时间轴（照这个走就不会超时）

| 时间 | 场景 | 屏幕上一句话 |
|---|---|---|
| 0:00–0:40 | 开场：登录 + 工作台 | "一份文档、三层校验、每条结论可追溯" |
| 0:40–3:40 | ★ **模板审计**（核心） | "读当前草稿 + 按校准配置 + 豆包逐条判定" |
| 3:40–4:20 | 两个对照 | "空文档只会报缺失；换配置结论就变" |
| 4:20–5:50 | 提交 + 双人审批 | "提交的是快照，审批人不能是自己" |
| 5:50–7:10 | 法规风险扫描 | "组合判定能阻断，没查到会明说" |
| 7:10–8:00 | 收尾（含 20 秒缓冲） | "模型不造证据；出网是用户决定" |

---

## 1. 开场前 60 秒（不计入 8 分钟）

### 1.1 三条命令自检

```bash
curl -s http://59.110.213.187:8082/health          # {"status":"ok","auth_mode":"pg"}
curl -s -o /dev/null -w '%{http_code}\n' http://59.110.213.187:8082/    # 200
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'systemctl is-active smart-edit nginx smart-edit-automation; curl -s -m 3 http://127.0.0.1:8080/health'
# 期望：active active active + {"status":"ready",...}
```

### 1.2 恢复干净起点（**必做**，10 秒）

```bash
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py >/dev/null \
   && systemctl restart smart-edit && echo restored'
```

这会：重置 5 个演示账号密码；把 `demo-document` 还原成 **Draft rev 1**（清掉上一轮的提交/审批/锁），
所以每次演示都能从"可编辑的草稿"开始。

> 不改 `sanctions-zh` 等样例文档；如果它们被上一轮提交过（只读），§6 会说明改用什么。

### 1.3 三个窗口（推荐：一个普通窗口 + 两个无痕）

1. 普通窗口：`applicant` 登录，停在文档页（`Demand Guarantee Application`）。
2. 无痕窗口 A：`bankops` 登录。
3. 无痕窗口 B：`compliance` 登录。

> 都用 `http://`（不要 https），否则带 `Secure` 的 Cookie 不会回传，表现为"登录成功但立刻 401"。
> 如果 §1.2 之前已经登录过，刷新一下页面即可。

### 1.4 网页内的产品导览（推荐先试一遍）

顶栏 **Take the tour** 会弹出选择框：

| 选项 | 说明 |
|---|---|
| **Guide me** | 你自己点；每一步的 **Next** 只有达到预期状态才会解锁（例如出现报告、状态变成 Pending） |
| **Watch me** | 自动演示：模拟光标飞到控件、真实点击、按节奏输入文本；**每一步在气泡里显示 10 秒倒计时**，可以 **Pause / Next now / Stop**，`Esc` 退出 |
| **Hand off to me**（提交） | 到"提交审批"时停下来，由你自己点 |
| **Let the tour submit**（提交） | 自动点"Submit for approval"；文档会变成只读，演示后按 §1.2 重置 |

> **这两个提交选项在弹框的 `Submission step` 一栏**（现在与 `Mode` 并排显示；底部的 `Start tour` 固定在可视区，不会被滚动挡住）。

导览与本文主线一致（文档 → 模板审计 → 证据 → 导出 → 提交 → 交接审批）。
Bank Ops / Compliance 的审批仍需各自窗口，导览会在此处交接。

**可选导览**（启动弹框里的 `Tour` 下拉，完成过的会带 ✓）：

| Tour | 内容 | 时长 |
|---|---|---|
| `Core loop` | 文档 → 模板审计 → 导出 → 提交 → 交接（默认） | ~4 min |
| `Audit deep dive` | 严格配置、证据、脱敏、导出 | ~2 min |
| `Legal risk scan` | 打开制裁样例 → Document check → 闸门/发现/锚点 | ~2 min |
| `Two-person approval` | Approval 面板、职责分离、二审交接 | ~1.5 min |
| `Automation workbench` | Automate 模板/字段/下游契约 → Rules 分级（自动 dry-run）→ Runs 回执（自动展开 Details）→ Sandbox（**全程不发送**；Watch me 会自动切区域、展开映射/回执、切三个沙盒子页签） | ~4 min |
| `Lifecycle 1/3` | **新建** → 粘贴 → 审计 → 提交（applicant 窗口） | ~3 min |
| `Lifecycle 2/3` | Bank Ops 一审 → Pending second（bankops 窗口） | ~1 min |
| `Lifecycle 3/3` | Compliance 二审 → **Approved**（compliance 窗口） | ~1 min |

> **Lifecycle 是“三段接力”**：浏览器不能替你换账号，所以每段在各自窗口运行；启动弹框会显示 `Lifecycle: x/3 parts complete`。
> 深链：`?tour=lifecycle-applicant`、`?tour=lifecycle-first`、`?tour=lifecycle-second`。
> 提交/审批动作仍受 **Let the tour submit** 控制；不选就由你手动点。跑完终审后按 §1.2 重置再重放。

也可用深链直接打开选择框：`?tour=audit`、`?tour=legal`、`?tour=approval`、`?tour=automation`（`?tour=core` 为默认）。

> `Automation workbench` 需要 **Bank Operations**（或组织管理员）身份：`automation.view` 缺失时该标签会被隐藏，
> 导览会逐段跳过并在弹框里提示换 `bankops@atlas-trade.test` 登录。导览只讲解、不点 **Send**，不会产生派发。

**提词器（Presenter script）**：弹框底部的 **Presenter script** 按钮，或直接访问 `?presenter=1`。
底部会出现 8 分钟脚本面板：分段（开场 / 模板审计 / 对照 / 审批 / 法规 / 收尾）、总倒计时、当前段要点；
`←/→` 换段、`Space` 暂停、`Esc` 关闭。它**只读**，不会点击或输入，因此不会改动文档或提交。

### 1.5 如果现场翻车（Plan B）

- **模型慢/超时**：模板审计会给出 `MODEL_TIMEOUT` / `deadline_exceeded` 的 Limitations，照实讲"这是超时，不是通过"；然后直接演 §4.1 的 `333333`（不需要模型也能得到缺失清单）。
- **页面是旧版**：`Cmd/Ctrl + Shift + R` 硬刷新。
- **登录 401**：重新登录；确认 URL 是 `:8082`。
- **任何接口红错**：`ssh … 'journalctl -u smart-edit -n 80 --no-pager'`。

---

## 2. 0:00–0:40　开场：登录与工作台

**操作**

1. 用 `applicant` 登录，看到三栏：左（模块）、中（文档）、右（AI 助手）。
2. 鼠标点一下底部状态条：`draft rev N · Saved to server · lock: this session`。

**台词**

> 这是我们今天要看的一份保函草稿。左边是业务要编辑的原文，右边我们把"格式、业务要件、法规与合规"
> 三类检查放在同一处。所有检查读的都是**当前这份草稿**——而且结论必须能指回原文，这是这个产品最核心的约束。
>
> 底部这行 `draft rev N` 很关键：每次保存都会 bump 版本，后面的 AI 审计会**钉住**这个版本；
> 如果审计之后文档又改了，报告会立刻标 `stale`，不会拿旧结论冒充新结论。

**指一下**：顶部组织/角色（Atlas Trade Bank / Applicant）、右侧面板四个标签（`Audit / Knowledge / Automation / Legal`）。

## 3. 0:40–3:40　★ 模板审计（8 分钟的核心）

> 这一段要讲清三件事：**读的是当前草稿**、**判的是预设校准配置**、**每条结论都能指回原文**。

### 3.1 粘贴 + 保存（40 秒）

1. 确认打开的是 **`Demand Guarantee Application`**（§1.2 已把它还原成可编辑草稿；不用新建文档，列表更干净）。
2. 在编辑器里 `Cmd/Ctrl + A` 全选 → 粘贴 **附录 A.1 标准保函**。
3. 等约 2 秒，底部变成 **`Saved to server`**、`draft rev 2`。

**台词**

> 这一步先建立"审的是什么"：粘贴后自动保存，底部这行 `draft rev 2` 就是接下来审计要钉住的版本。

> 如果顶部出现 "unsaved changes…"，说明自动保存还没完成，点一下 **Save now** 再审计。

### 3.2 选配置 + 运行（20 秒）

1. 右栏 **Audit**（默认就是模板审计）。
2. `Calibration config` 选 **Demand guarantee — standard desk check**。
3. 点 **Run template audit**。进度会依次显示：
   `Reading the saved draft → Checking required fields (no model) → Asking Doubao to judge the checklist → Assembling the report`
   （线上实测约 **6 秒**）

**台词**

> 这里分了两层：**字段缺失**由确定性抽取算，不经过模型；**语义是否符合模板**才交给豆包逐条判断。
> 所以"缺字段"这件事永远不会有幻觉。

### 3.3 讲结果（80 秒，照这张表讲）

**屏幕（线上实测）**

```text
Findings            5/6 requirement(s) assessed · 100% coverage · complete
Required fields not found    （无）
Does not match the config
  Applicant and beneficiary…(parties.contactability)  Must · Warning · high confidence
  Applicant: Alpha Tech Pte Ltd
  Beneficiary: Beta Construction Ltd          [Show in document]
  5 requirement(s) met        （展开：每条都带引用的原文）
```

**台词（按行讲）**

> **结论先给结论**：6 条要求里 5 条满足、1 条不符合，覆盖率 100%——意思是"每一条都真的判了"，
> 不是"只看了几条就说没问题"。
>
> **这条不符合**是"双方没有地址/联系方式"：保函要能见索即付，索赔要送得到。
> 下面这行不是模型复述，是**从你的文档里逐字摘出来的原文**；点 `Show in document` 会跳回那一段。
>
> **已满足的 5 条**点开，每条都带它引用的那句话。**没有引用就不能算通过**——
> 如果模型给不出能定位的原文，这条会降级成"未能评估"，而不是算它过。
>
> 最下面那行小字也要念：**总结是模型写的**；`pass` 只代表"引用的这段文字满足这条要求"，
> **不等于整份文件合规**。

### 3.4 三个 10 秒的加分动作（40 秒）

1. 展开 **Config details**：这是本次用的**校准配置**（每条要求的口径、必需字段、生成上限、config 版本 + sha）。
   > 「配置是文件化、版本化的；报告里记了 config 的 sha，事后能复原"当时按什么口径审的"。」
2. 展开 **What leaves the service** / **Redaction steps**：
   > 「发给豆包之前先做一层模式脱敏：账号/卡号、IBAN/BIC、邮箱、电话、证件号会被换成 `[redacted]`；
   > 报告只显示"类型 + 次数 + 打码样例"。这只是缓解措施，姓名/金额/地址仍会出境——
   > 出站策略与 approved-processor 闸门才是权威控制。」
   （这份标准样例没有敏感标识，所以这里显示 0 条；要演示脱敏，用附录 B.1 的加料句。）
3. 点 **Copy report / Download .md / Print**：
   > 「结论可以带走：导出的 Markdown 与屏幕一致，包含覆盖率、限制、脱敏步骤和模型信息。」

> **如果时间紧**：只讲 1 和 2，导出留到 Q&A。

## 4. 3:40–4:20　两个对照（证明不是"随便给结论"）

> 这一段用**同一份文档**换内容、换口径，避免现场开太多空白文档（新建会得到多份 `Untitled document`，列表里不好认）。

### 4.1 空内容：只会报"缺失"（15 秒）

1. 编辑器 `Cmd/Ctrl + A` → 只输入 `333333` → 等 **Saved to server**。
2. Audit → `guarantee-standard` → **Run template audit**。

**屏幕（线上实测）**

```text
Needs input        0/6 requirement(s) assessed · 0% coverage · partial
Required fields not found
  Guarantee No / Applicant / Beneficiary / Amount / Currency / Issue Date / Expiry Date / Governing Rules
6 requirement(s) not assessed
Limitations        model_note
```

**台词**

> 这份"文档"只有一个数字。系统不会拿别人的样例凑数：**8 个必填字段全部明确报缺失**，
> 6 条语义要求因为看不到内容而标"未能评估"。注意"缺失"和"未能评估"是两种不同的状态。

### 4.2 换配置：同一份文档，口径变了（25 秒）

1. 把 **附录 A.1 标准保函**再粘贴回去 → 等 **Saved to server**。
2. `Calibration config` 换成 **Demand guarantee — strict compliance check** → **Run template audit**。

**屏幕（线上实测）**

```text
Findings           3/5 requirement(s) assessed · 100% coverage · complete
Does not match the config
  Governing law clause is stated                      Must · Warning
  Sanctions and anti-money-laundering declaration…    Should · Info
2 requirement(s) met  （URDG 758 / presentation period / legal names）
```

**台词**

> 同一份文档，换一份更严的校准配置，结论就变了：严格版要求**明示管辖法律**和**制裁/合法来源声明**，
> 这份标准保函没有，所以两条不符合。
>
> 这就是"预设校准配置"的意义：**口径是可替换、可版本化的**，不是写死在代码里的一个判断。

---

## 5. 4:20–5:50　提交 + 双人审批（90 秒）

### 5.1 applicant 提交（20 秒）

1. 确认底部是 `lock: this session`（不是的话点 **Start editing**）。
2. 工具栏点 **Submit new version** → 对话框确认目标链：
   `Bank Operations — First Approver` → `Compliance — Second Approver`
3. 点 **Submit for approval**。

**屏幕**：文档顶部出现 `Pending first approval`；编辑器变**只读**；锁释放。

> **台词**：提交的是**快照**（revision + sha），审批人看到的就是提交时的文本；提交后这份草稿冻结，避免"批的和改的不是一份东西"。

### 5.2 一审：bankops（20 秒）

1. 切到 `bankops` 的无痕窗口 → 顶部 **Approval** → 标签 **First approval**。
2. 选中刚提交的记录 → **Approve**（如要求意见，填一句"资料齐全"）。

**屏幕**：状态变 `Pending second approval`。

### 5.3 二审：compliance（20 秒）

1. 切到 `compliance` 窗口 → **Approval** → **Second approval** → **Approve**。

**屏幕**：状态变 `Approved`；再回 applicant，文档只读，`Approval → My submissions` 能看到完整状态。

### 5.4 留痕（30 秒）

1. 顶部 **Activity**：能看到 `Submitted for approval` / `Approved` 等事件（谁、什么时候）。
2. 顺带一句：**提交人不能审自己的单**；审批人之间职责分离，每一步都写活动流水。

**台词**

> 这一层是"谁能看、谁能改、谁批过"的底座。所有 AI 结论都挂在这套组织/文档权限下面，不绕过授权。

---

## 6. 5:50–7:10　法规风险扫描（80 秒）

> 这条链路和模板审计是**两条独立能力**：模板审计判"是否符合我们的审单口径"，法规扫描判"是否触碰法规红线"。
> 今天不合并它们。

### 6.1 准备 + 扫描（20 秒）

1. 文档头 **Open document…** → 选 **`sanctions-zh`**（`draft`）。
   > 若它已是只读（上一轮提交过）：**New document** → 粘贴 **附录 A.2 制裁合同** → 等 Saved。
2. 右栏 **Legal** → 子标签 **Document check**。
3. 确认 **Use web search…** **不勾选**（默认关）→ 点 **Scan document**（约 3–10 秒）。

### 6.2 讲结果（60 秒）

**屏幕（线上实测）**

```text
Gate: Blocked      Planned 12 · assessed 10 (83%) · 1 clause
Critical  Blocks         Sensitive goods destined for a sanctioned country        [Jump to clause] ×4
Critical  Needs review   Export-controlled goods without a stated licence         [Jump to clause]
Critical  Needs review   Comprehensively sanctioned destination referenced        [Jump to clause]
Warning   Needs review   Circumvention wording detected                           [Jump to clause]
```

**台词**

> 这份合同要"从美国出口军用无人机部件、导弹备件和弹药到伊朗"，还写了"第三国现金支付、经第三国转运以规避制裁审查"。
>
> 系统不是"看到伊朗就报警"，而是**组合判断**：受控货物 + 全面制裁目的地 = 硬阻断；
> 只出现其中一项，只会转人工复核。**硬阻断只来自确定性规则，模型不能把任何一条升成 Critical。**
>
> 每条都能点 `Jump to clause` 回到原句；右上角的 `Planned 12 · assessed 10 (83%)` 是覆盖率，
> 没覆盖的 2 个单元会写进 Gate 原因（`unchecked_units`）——这就是"没查到 ≠ 没问题"。

> 想演"联网补检"：勾选 Use web search 再扫一次，会多一条 `Info · Web sources need a human check`，
> 带真实链接并标 `Unverified web source`。**8 分钟版建议跳过**，只在被问到时提一句。

---

## 7. 7:10–8:00　收尾：三句诚实边界（含缓冲）

1. **没查到 ≠ 没问题**：报告里 `assessed / planned`、`unchecked_units`、`unable_to_assess` 就是这件事。
2. **模型不造证据、也不能阻断**：它只能引用检索到/文档里的原文，不能把严重度提到 Critical，也不能 hard block。
3. **出网是用户的决定**：法规扫描的联网默认关；模板审计发送前做模式脱敏，且只有 approved processor 才能接收。

**边界（被问到时照实说）**

- 这不是法务意见，所有 finding 都是"red flag / 提示"，最终要人判。
- 这不是制裁名单筛查：没有接 OFAC SDN / BIS Entity List，也没有货物分类与许可判断。
- 这是单组织演示环境（`ws_demo_01`），身份/组织/审批是真实链路，但下游系统是本地回显。

**结束句**

> 我们要交付的不是"一个会说话的结论"，而是**一条可复核的审单链路**：
> 读的是哪一版、按什么口径、每条结论引用了哪句话、哪里没查到——都能指出来。

---

## 附录 A　样例文本（直接粘贴）

### A.1 标准保函（模板审计用）

```text
DEMAND GUARANTEE
Guarantee No: BG-2026-00417
Applicant: Alpha Tech Pte Ltd
Beneficiary: Beta Construction Ltd
Amount: USD 500,000.00
Currency: USD
Issue Date: 12/03/26
Expiry Date: 12/03/27
Governing Rules: URDG 758

This guarantee is payable on first written demand.
```

> 线上实测：`Findings · 5/6 · 100% · complete`；唯一不符合是"双方没有地址/联系方式"。
> 换成 `guarantee-strict`：`3/5`，多出"未写管辖法律"和"无制裁/合法来源声明"两条。

### A.2 制裁合同（法规扫描用）

```text
出口合同

卖方：Northbridge Arms Trading LLC（美国）
买方：Sepahan Logistics Co.（伊朗）
目的地：伊朗德黑兰
货物：军用无人机部件、导弹备件及弹药 120 套
合同金额：USD 4,800,000.00
适用法律：新加坡
付款：第三国现金支付，经第三国转运以规避制裁审查
```

> 线上实测：`Gate: Blocked`、`Planned 12 · assessed 10 (83%)`、4 条 finding（3 Critical），
> 第一条带 4 个草稿锚点。

### A.3 只用数字（对照用）

```text
333333
```

> 线上实测：`Needs input`、8 个必填字段全部缺失、6 条语义要求 `unable_to_assess`、`0% coverage`。

---

## 附录 B　可选深挖（不在 8 分钟内）

### B.1 脱敏步骤（30 秒）

在 A.1 末尾加一行，再跑一次模板审计：

```text
Please remit to account 6123 4567 8901 2345 or email ops@example.com.
```

展开 **Redaction steps**：应出现 `email × 1 — o•••@example.com`、`account_or_phone × 1 — 61••••••••2345`，
模型看到的文本里对应位置是 `[redacted]`。

> 口径：这是**固定模式**的缓解措施；姓名/金额/地址仍会出境，权威控制是出站策略 + approved-processor。

### B.2 上次审计对比（20 秒）

把 `Expiry Date: 12/03/27` 改成 `Expiry Date: 12/03/30` → 保存 → **Re-audit**。
报告顶部会出现：

```text
Previous audit 2026/11/22 20:xx (rev N): findings 0 · missing fields 0 · coverage 0 pts
```

（同一文档 + 同一配置才有对比；换配置会清空对比，避免拿别的口径来比。）

### B.3 知识问答（1 分钟）

`Knowledge` → 点第一条建议问题 **"独立保函必须载明哪些事项才有效？"**。
期望 `answered` + 若干条引用，并带"仅覆盖…"的限制说明。

**诚实对照**：再问英文的 "What does URDG 758 article 20 require for claims?"，
期望 `insufficient_evidence`——语料里没有 URDG 758 原文。**这是卖点，不是故障。**

### B.4 自动化（2 分钟，可选）

环境已就绪：`smart-edit-automation` worker **active**，本地回显 `127.0.0.1:18080` **healthy**。
`Automation` 标签内按引导走：`Template → Fields (Find variables with AI → Confirm) → Downstream → Review & send`。
发送后回执显示 `status · 200 · 15 ms · dispatch_id`。
也可以让导览代讲：顶栏 **Take the tour** → `Automation workbench`（或 `?tour=automation`，需 bankops 登录）；
它只切换 Automate / Rules / Runs / Sandbox 并解释闸门，最后停在 Review，**不会替你点 Send**。

演示数据（已通过脚本写入本环境，可重复执行）：

```bash
cd /opt/smart-edit && set -a && . ./.env && set +a
.venv/bin/python scripts/seed_automation_demo.py
```

它会创建 `Automation demo · trade application`（真实提交 + 双审 Approved）、一条 **shadow** 规则
（`Demo · Trade application (spec demo) → Trade intake (spec demo)`）和一条真实 **shadowed** 运行；
脚本在发现同模板存在非 shadow 规则时会拒绝执行，保证不会真的发送。
在 `Open document…` 里打开该文档可看到它自己的 Delivery；其它文档的 Runs 会显示“工作区最新运行”。
导览在 Rules 会点一次 **Dry-run**，在 Runs 会点 **Details** 展开时间线 —— 这两步现在都有真实内容。

口径：这是**本地回显**的演示下游，不是生产集成；连接器只存变量名，密钥走环境变量。

### B.5 导入文件（可选）

工具栏 **Import file** 支持 `.pdf / .docx / .png / .jpg`。仓库现成样例：
`fixtures/imports/guarantee.docx`、`...wording.pdf`、`scan.png`。
注意：导入是**另起一个 run 去解析**，正文演示仍以粘贴为主。

### B.6 组织 / 权限 / API / 活动

- `People`：成员、部门、邀请；角色 Applicant / Bank Ops / Compliance / Auditor / Org admin。
- `Developer`：API keys、请求日志、7 天用量。
- `Activity`：谁在什么时候做了什么（审批、扫描、保存都有）。

### B.7 文档列表里的历史样例

`Open document…` 里还有 `sanctions-en`、`sample-a-hard-block`、`独立保函` 等历史样例，
以及若干 `Untitled document`（历史会话留下的）。**演示只用 `Demand Guarantee Application` 和 `sanctions-zh`**，其余可忽略。

---

## 附录 C　现场故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 页面空白 / JS 404 | `web/dist` 与远端不一致 | 本机 `./deploy/deploy.sh` 后硬刷新 |
| 登录 401、所有接口 401 | Cookie 未回传 / 会话过期 | 重新登录；确认是 `http://…:8082`（不是 https） |
| 密码正确仍 401 | 账号表被重置过 | 跑 §1.2 的 seed 脚本 |
| 编辑器不能输入 | 只读（审批中 / 不是本人 / 无锁） | 草稿点 **Start editing**；`pending_*`/`approved` 属预期只读 |
| 点 Save 提示 "Nothing to save" | 自动保存已经落库 | 正常；看底部是否已是 `Saved to server` |
| 状态显示 **Unsaved changes (local only)** | 当前窗口没有编辑锁（另一个窗口持锁，或锁已过期） | 点状态条上的 `lock:` → **Release stale lock**（过期锁）或去持锁窗口 **Release lock**，再 **Start editing** |
| 文档顶部提示 **Could not load this document** | 加载失败（网络/会话/服务重启） | 点 **Retry**；仍失败则重新登录或看后端日志 |
| Tour 停在 **Confirm the chain** | 文档已经提交（`Pending/Approved`），Submit 按钮被禁用，弹窗不会出现 | 新版会自动跳过提交段；要演示提交，先按 §1.2 重置文档，或 **New document** |
| 模板审计立刻失败 | 看错误码：`composer_unavailable` / `stale_snapshot` / `unknown_config` | 分别是模型未批准 / 审计后文档又保存了 / 配置 id 不对 |
| 模板审计 `MODEL_TIMEOUT` / `deadline_exceeded` | 模型慢或网络抖动 | 重跑；或改演 §4.1（不依赖模型也能看到缺失清单） |
| 审计结果为 `document_chunked` / `truncated` | 文档超过 24k 字符 | 属设计行为；报告里写了发了多少字符 |
| 法规扫描一直 `Checking statute evidence` | 检索/模型慢 | 等 90 秒预算；`journalctl -u smart-edit -f` 看 timeout；必要时重扫 |
| 大量 `uncovered:*` / `low_confidence` | 语料不覆盖该法域/主题 | 换中文样例；或当成"没查到 ≠ 没问题"讲 |
| `Gate: Blocked` 但不是你想演的 | 样例本身有硬阻断 | 换 §A.1 的标准保函，或按 §4.2 讲"不同口径" |
| 8082 打不开（外网） | 安全组 / 主机 firewalld | 控制台放行 8082 + `firewall-cmd --list-ports` |
| 重跑后旧 run 报 `unknown_run` | run 状态在进程内 | 重新发起（属设计行为） |
| 文档列表还是旧数据 | 另一个进程改过 SQLite，服务持有旧快照 | `systemctl restart smart-edit` 后刷新 |

---

## 附录 D　运维命令（在 ECS 上）

```bash
systemctl status smart-edit nginx smart-edit-automation
journalctl -u smart-edit -n 120 --no-pager        # 后端日志（含 request_id）
journalctl -u smart-edit-automation -n 80 --no-pager
systemctl restart smart-edit                      # 重启后端（run 状态会丢，文档不丢）
tail -f /var/log/nginx/smart-edit.access.log /var/log/nginx/smart-edit.error.log
```

**本机部署 / 更新**

```bash
./deploy/deploy.sh                 # 构建前端 + 同步 + 远端 pip/systemd/nginx + 外网自检
./deploy/deploy.sh --no-build      # 只改了后端
./deploy/deploy.sh --remote-only   # 只重跑 nginx/systemd（不同步代码）
```

**数据备份 / 恢复（host.db）**

```bash
systemctl stop smart-edit
cp /opt/smart-edit/data/host.db /opt/smart-edit/data/host.db.bak-$(date +%F-%H%M)
systemctl start smart-edit
# 恢复：停服务 → 覆盖 host.db → 启服务
```

**恢复演示文档与账号**

```bash
cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py && systemctl restart smart-edit
```

**改配置**：本机编辑 `deploy/env.ecs` → `./deploy/deploy.sh --remote-only`（会覆盖服务器 `.env`，权限 600）。

---

## 附录 E　一页 Cheat Sheet

```text
地址：http://59.110.213.187:8082/
主号：applicant@atlas-trade.test / Applicant!2026
一审：bankops@atlas-trade.test   / BankOps!2026
二审：compliance@atlas-trade.test/ Compliance!2026

开场前：ssh … 'cd /opt/smart-edit && .venv/bin/python scripts/seed_identity_users.py && systemctl restart smart-edit'

模板审计：粘贴 A.1 → 等 Saved → Audit → standard → Run template audit
  期望：Findings · 5/6 · 100%；1 条不符合（无地址/联系方式）
对照：粘贴 333333 → Needs input + 8 缺失
     换 strict → Findings · 3/5 · 2 条不符合（管辖法律、制裁声明）

审批：applicant Submit new version → bankops First approval → compliance Second approval
法规：Open document… → sanctions-zh → Legal/Document check → Scan
  期望：Gate Blocked · 12/10 (83%) · 4 findings（3 Critical）

日志：journalctl -u smart-edit -f
```

> 更细的逐页操作见 `Demo_audit.md`（模板审计/审计变体）；审批与自动投递的单步流程见
> `DEMO_auto_dispatch.md`；完整 API 与能力清单见 `how_to_use.md`；部署细节见 `deploy/README.md`。