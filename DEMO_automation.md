这是当前版本（两个 tab：`Automate` / `Sandbox`）的完整页面测试指引，每一步的预期都是我刚在线上实测的输出。

## 0. 前置（30 秒）

```
① 打开 http://59.110.213.187:8082/ ，登录 applicant@atlas-trade.test / Applicant!2026
② 回显服务（决定"发送"能不能拿到真实回执）：
   ssh -i ~/.ssh/team04_ecs root@59.110.213.187 'curl -s http://127.0.0.1:18080/health'
   期望：{"status": "ok"}
```

现场已有：

| 类型 | 对象 |
|---|---|
| 模板 | `Trade application (spec demo)` v1.0.1（6 变量）· `Demo (from draft)` v1.0.1（6 变量）· `Export contract (prose)` v1.0.0（0 变量） |
| 连接器 | `Local echo (demo)`（flat）· `Refusal demo`（flat，故意不在白名单）· `Trade intake (spec demo)`（openapi，`POST /trade/applications`） |

## 1. 样例文档（粘贴进编辑器）

文件也在仓库：`fixtures/automation-samples/trade-application.txt`

```text
TRADE APPLICATION
Application type: guarantee
Applicant: Atlas Trading Ltd
Beneficiary: Meridian Exports Pte Ltd
Amount: USD 250,000.00
Currency: USD
Expiry date: 2027-06-30
```

为什么用它：7 行里 6 行是 `Label: value`，正好对上模板的 6 个变量；`Amount` 带币种和千分位，能验证"数字转换"。

## 2. 进入模块

点编辑器 → `Cmd/Ctrl+A` → 粘贴 → 等 2 秒（约 **179 字符**自动保存）。

右侧面板 → **`Automation`** → 默认就在 **`Automate`**：

```text
tabs:     Automate | Sandbox
sections: 1 · Template (server) | 2 · Fields | 3 · Downstream | 4 · Review & send
引导条:   Step 4/5 …（会随状态变化）
```

> `Sandbox` 是本地演练（不发请求），测试真实链路只在 `Automate` 里做。

## 3. 逐步骤（每步都写了预期）

### 步骤 1 · 选模板（`1 · Template (server)`）

点 **`Trade application (spec demo) v1.0.1 · 6 vars`**。

预期：`2 · Fields` 显示 `6 confirmed: Application type, Applicant, Beneficiary, Amount, Currency, Expiry date`。

管理动作（都在同一区块）：`Rename` / `Duplicate` / `Delete`（删除需 `Yes, delete` 二次确认）。

### 步骤 2 · 选下游（`3 · Downstream`）

连接器下拉选 **`Trade intake (spec demo) · http://127.0.0.1:18080`**。

预期：

```text
Trade Intake API 1.4.0 · POST /trade/applications · application/json
字段：application_type, amount, expiry_date, beneficiary.name, beneficiary.country,
      references(array，不可映射), structured.next.back(circular，不可映射)
映射预填：amount=amount（beneficiary.name=beneficiary, expiry_date=expiry_date）
```

> 映射按（模板 × 连接器）保存，现在都处于"自动建议"状态；想改就在下方折叠的 **`Field mapping`** 里改，
> 点 **`Save mapping`** 才会固定下来（`Reset to suggestions` 回到按标签自动建议）。

### 步骤 3 · 复核（`4 · Review & send`）

取值**自动完成**，不需要点按钮：模板、连接器、映射都就绪后，面板会从草稿取值并渲染复核卡
（`Template → 连接器 · operation`、只读映射表、每个变量的值与来源、请求体预览）。

预期：`bound 6/6`，`Payload preview`（就是下游请求体）：

```json
{
  "application_type": "guarantee",
  "amount": 250000,
  "expiry_date": "2027-06-30",
  "beneficiary": { "name": "Meridian Exports Pte Ltd" }
}
```

注意 `amount` 是**数字** `250000`，草稿里写的是 `USD 250,000.00`。

### 步骤 4 · 不发送也能看（dry-run）

点 **`Preview request`**。

预期：

```text
POST http://127.0.0.1:18080/trade/applications · openapi
Content-Type: application/json
{ "application_type": "guarantee", "amount": 250000, "expiry_date": "2027-06-30",
  "beneficiary": { "name": "Meridian Exports Pte Ltd" } }
```

不会产生回执（历史条数不变）。

### 步骤 5 · 真实发送

点 **`Send`**。

预期回执：

```text
succeeded | 200 · 15 ms · dsp_…
{"accepted": true, "path": "/trade/applications", "authorization": "absent",
 "echo": {"application_type": "guarantee", "amount": 250000.0, "expiry_date": "2027-06-30",
          "beneficiary": {"name": "Meridian Exports Pte Ltd"}}}
```

两个验证点：`path` 是 **`/trade/applications`**（来自 spec，不是手填），body 与第 3 步预览逐字段一致。

### 步骤 6 · 回执（只读）

`4 · Review & send` 里只有两个动作：**`Preview request`** 和 **`Send`**；回执卡只展示结果
（`status · 200 · 15 ms · dispatch_id` 与响应摘录），不再有额外按钮。
`Recent dispatches` 折叠起来，展开后可按 `All / Succeeded / Failed / Refused` 过滤。

> 模板套用（`POST …/apply`）与值回填草稿（`POST …/write-back`）仍保留在 API；简化后的面板不再提供这两个按钮。

## 4. 反向验证（各 20 秒）

| 想验证 | 操作 | 预期 |
|---|---|---|
| 不在白名单就不发 | 连接器改选 `Refusal demo` → `Send` | 红字 `That downstream host is not on the server allow-list, so nothing was sent. An operator adds hosts to SMART_EDIT_AUTOMATION_ALLOW_HOSTS.`；历史里一条 `refused` |
| 必填没映射就不发 | `3 · Downstream` → 展开 `Field mapping` → `beneficiary.name` 改 `(not sent)` → `Save mapping` | `beneficiary.name — Required field has no mapped variable.`，`Send` 变灰 |
| 映射互不覆盖 | 切到 `Demo (from draft)`，把 `amount` 清空并 `Save mapping`，再切回 `Trade application (spec demo)` | 后者的 `amount` 仍是 `amount` |
| 沙箱不发请求 | 切到 `Sandbox` → `Payload preview` → 选 `OpenAPI` | 顶部横幅 `Sandbox — nothing leaves this browser`；只有 `Download JSON`，没有发送按钮 |

## 5. Sandbox 快速走查（1 分钟，可选）

`Sandbox` 分三段：`Templates`（本地存模板、`Save as template`、应用到编辑器）、`Variables & fill`（框选文本标记变量、填值回文档）、`Payload preview`（选 fixture 或 OpenAPI → 预览 + `Download JSON`）。

`Payload preview` 的 OpenAPI 解析与组包**已改由服务端**（`/automation/spec/parse`、`/spec/build`）完成，页面会显示 `Trade Intake API · 1.4.0 · 4 operation(s)`。

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| 按钮全灰、提示只读 | 先点编辑器正文拿编辑锁（工具栏出现编辑态） |
| `bound 0/6` | 编辑器里不是第 1 步那段文本（只按 `Label: value` 取值） |
| `Send` 灰 | 看预览下方 issues；或连接器没选 |
| 回执 `failed · transport_error` | 回显服务没起（见第 0 步） |
| 回执 `refused · host_not_allowed` | 用的是 `Refusal demo`，属于预期 |
| 想看服务端实际记录 | `ssh … 'cd /opt/smart-edit && .venv/bin/python -c "import sqlite3;c=sqlite3.connect(\"data/host.db\");print(c.execute(\"select status,count(*) from automation_dispatches group by status\").fetchall())"'` |

## 7. 测完复原

```bash
# 草稿恢复成种子演示文本（188 字，sha e5fbb2ec…）
cd /tmp && python3 /tmp/restore_demo_draft.py
# 映射恢复成"自动建议"、清掉配对映射
ssh -i ~/.ssh/team04_ecs root@59.110.213.187 \
  'cd /opt/smart-edit && .venv/bin/python /tmp/reset_mappings.py && systemctl restart smart-edit'
```

我刚测完已复原：`demo-document` rev 7 / 188 字（sha `e5fbb2ec0816…`）、配对映射 0 条、三个连接器映射均回到自动（历史遗留的 `doc_fd15c1fc94a6` 属正常业务数据，不影响演示）。

截图参考：`/tmp/automation-guide-final.png`。

## 8. 一页速记

```text
Automation → Automate
  1 选模板 Trade application (spec demo)
  2 选连接器 Trade intake (spec demo)      → 看 7 个字段 + 预填映射
  3 Review & send（自动取值）               → bound 6/6 + 嵌套 body
  4 Preview request                        → 不发请求的 dry-run
  5 Send                                   → succeeded 200 15ms，path=/trade/applications
  6 回执只读；Recent dispatches 可展开
  7 （反向）Refusal demo → refused；删映射 → Send 变灰
```