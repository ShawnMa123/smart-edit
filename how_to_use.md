# 怎么从界面跑一次端到端（UI → normalize → audit）

> 这份文件回答一个问题：**现在想让一份保函从浏览器点进去、走完标准化再走完规范审计，我该敲什么、该点哪、该看到什么。**
> 所有数字都是本机实测（2026-11-08），不是估算。

## 0. 现在能跑什么（先对齐预期）

| 能力 | 状态 | 证据 |
|---|---|---|
| 后端 HTTP（创建 run、触发阶段、读信封） | 能跑 | `app/api/main.py`，`supported_stages = audit/extract/normalize/parse` |
| 标准化（`agent1`：parse → extract → normalize） | 能跑 | fixture 模型下 8 个字段 `extracted`，出处可定位 |
| 规范审计（`agent4`：`stages/audit`） | 能跑 | 每份保函 **51** 个计划单元，干净文档评估 **33** 项（ratio 0.647），引擎模型调用 **0** |
| 三栏界面 + 右栏「Rule audit」 | 能跑 | `npm --prefix web run dev` → http://localhost:5173 |
| 右栏「Knowledge Q&A」知识助手（fixture 语料） | 能跑 | `/api/assistant/*`：202 + 轮询、Claim 级引用、support_level、澄清/弃答/转交、反馈 |
| 后端 / 前端测试 | 539 后端 / 345 前端全绿 | `.venv/bin/python -m pytest -q`、`npm --prefix web run test` |

还没做（跑的时候会看到"未实现"而不是假成功）：审批流、法规 tab、语义检查、法规覆盖；Automation tab 只有
前端工作台（template 为浏览器本地快照并支持 apply/更新；下游系统 browser-local + 绑定 spec；variable 与 synthetic mapping 为 mock；OpenAPI JSON 在本地解析、下载，并可用不触网的 mock send 模拟 200/500），服务端 template/系统持久化、真实模型匹配与真实发送未实现；
知识助手的 PostgreSQL / Worker / 真实身份与快照 / 真实模型与向量检索 / 联网、语音、管理端 UI 都不在 A 里，
界面用 `Fixture-backed` 横幅明确标注。

## 1. 起服务

### 一条命令（推荐）

```bash
./scripts/dev.sh              # 后端 :8000（fixture 模型）+ 前端 :5173
./scripts/dev.sh --honest     # 同上，但后端不配模型 → 诚实路径（字段检查不会运行）
PORT=8010 WEB_PORT=5174 ./scripts/dev.sh     # 换端口，前端代理自动跟着走
./scripts/stop.sh             # 停掉 :8000 与 :5173（幂等，没起也不报错）
./scripts/stop.sh --all       # 连 e2e 的 :8010 / :5174 一起清
```

Ctrl+C **一起停**；如果终端已经关掉、或进程是 `nohup` 起的，用 `./scripts/stop.sh` 收尾。
脚本会先清掉这两个端口上的残留进程、等后端 `/openapi.json` 就绪再起前端。
后端/前端日志都会以 `[backend]` / `[web]` 前缀实时打印在终端，同时落到
`runs/logs/backend-<时间>.log` 与 `runs/logs/web-<时间>.log`；退出时也会打印这两个路径。
`SMART_EDIT_LOG_LEVEL=DEBUG ./scripts/dev.sh` 可额外看到每次 GET/轮询请求。

### 两个终端（想分别盯着两边日志时）

**终端 A — 后端（带 fixture 模型，所以抽取一定有候选值）**

```bash
cd ~/Desktop/AI/projects/smart-edit
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
  .venv/bin/uvicorn app.api.main:app --port 8000 --log-level warning
```

**终端 B — 前端**

```bash
cd ~/Desktop/AI/projects/smart-edit
npm --prefix web run dev          # 看到 Local: http://localhost:5173/
```

打开 **http://localhost:5173**。前端把 `/api/*` 代理到 `127.0.0.1:8000`（`web/vite.config.ts`），
所以**不需要 CORS**，也**不要**去访问 8000 的页面。

> 端口被占（`Port 5173 is in use, trying another one...`、`Errno 48 address already in use`）说明有**上一个会话
> 遗留的进程**，它跑的是旧代码，会给出 "unregistered stage target: audit" 这类假故障。先清掉：
>
> ```bash
> for p in 8000 8010 8011 5173 5174; do lsof -nP -iTCP:$p -sTCP:LISTEN -t | xargs -r kill -9; done
> ```

## 2. 在浏览器里做什么

1. **文档栏**：把 `fixtures/llm/sample_document.txt` 全文复制进去。
   必须是**这份文件**——`fixtures/llm/extract_sample.json` 是照着它录制的，换文本就不是在测链路了。
2. （可选）左栏「Version history」点 Capture 存一版，报告会绑定到这一版的快照摘要。
3. **右栏 → Rule audit 标签 → 点 `Run spec audit`**。
4. （可选）右栏 → **Knowledge Q&A** → 输入问题（或先在中间栏选中一段文字再提问），点 `Ask`；
   见 §8。

界面内部发三个请求（可在浏览器 Network 面板看到）：

```
POST /api/runs                                  {text: <document>}
POST /api/runs/{thread_id}/stages/normalize     ← 标准化（自动补齐 parse、extract）
POST /api/runs/{thread_id}/stages/audit         ← 规范审计（前置已完成，所以只跑审计）
```

## 3. 应该看到什么（实测值）

| 区域 | 期望 |
|---|---|
| Stages | `parse / extract / normalize / audit` **全部 Done**；`extract` 带 `fixture:fixtures/llm/extract_sample.json` 横幅 |
| Rule audit | **`No findings reported`**，`33 of 51 planned checks assessed · ratio 0.647` |
| 指标卡 | Planned 51 · Assessed 33 · Not applicable 18 · Needs input 0 · Hard blocks 0 |
| Gate | **`Not asked`** + "nothing is allowed"（审计本身不判定任何操作，这是设计） |
| 字段表 | 8 个字段 `Extracted`；金额 `500000.00`，原文 `USD 500,000.00` 可回溯 |
| 页脚 | `engine 1.0.0 · schema 044a959e73af · bundle guarantee-core v1.0.0 · server digest …` |

**验证它不说谎**：回到文档栏随便改一个字，右栏立刻变成 `Report is stale`，仍保留上次结论，
但明确写着不能用它审批（结论不会被"重新绑定"到新文本上）。

## 4. 诚实路径（无模型）

把终端 A 换成**不设** `SMART_EDIT_LLM` 重启：

```bash
.venv/bin/uvicorn app.api.main:app --port 8000 --log-level warning
```

再点 `Run spec audit`，应当看到：`Checks did not run` + `no model provider configured (set SMART_EDIT_LLM)`
+ `Rule audit did not run`，**且没有任何缺失字段清单**——那些空字段是占位符，不是这份文档的缺陷。
（前端在 `extract` 未成功时**不会**发起 `/stages/audit`，避免拿占位符审出假问题。）

## 5. 按客户模板审（模板驱动审计）

审计默认只按"基础字段字典 + 银行规则包"跑（51 个单元）。**模板驱动是显式请求的**：你要审的是"和阿迪达斯的
那份保函"，就点名模板；系统不会因为目录里有模板就擅自套用。

```bash
# 引擎本体：模板命中的场景
.venv/bin/python scripts/audit_demo.py      # 看 [template matched] 与 [two templates match] 两段

# 规则包 + 模板体检（字段可评性、条款能否在模板正文里定位、每条期望能否产出 pass/finding/needs_input）
.venv/bin/python -m app.rules.doctor
```

HTTP 上点名模板（`?template=<id>` 只会**缩小**候选，永远不能指定未发布版本或改版本号）：

```bash
curl -s -X POST "localhost:8000/runs/$TID/stages/audit?template=adidas-guarantee" | python3 -m json.tool | head -40
```

模板命中时（实测，`app/templates/adidas-guarantee.yaml`）：

| 项 | 实测值 |
|---|---|
| 计划单元 | **58** = 39 基础字段 + `origin_country` 类型单元 + 6 规则 + 6 证据 + **6 模板单元**（3 字段期望 + 2 条款 + 1 声明） |
| 结论 | `no_findings`，`complete`，覆盖率 **0.69**（40 项已评估） |
| 模板基线 | `verification.audit.template`：`adidas-guarantee` v1.0.0、`synthetic: true`、`resolved_from.beneficiary_name = Adidas AG`、`policy_packs: guarantee-core v1.0.0`、`conflicts: []` |

模板没命中（文档对手方不是 Adidas）或同时命中两份时，**不猜**：

| 情形 | 结果 |
|---|---|
| 0 份匹配 | 计划 52（多一个 `TEMPLATE:resolution`），`unable_to_assess` + `no_applicable_template`，闸门不放行 |
| ≥2 份匹配 | `unable_to_assess` + `ambiguous_template`，报告列出候选 `{template_id, version}` |

三种条款判断必须分清（这是 AUD-08 的要点）：

| 声明 | 行为 |
|---|---|
| `required` | 文档里找不到该条款 → **finding** |
| `controlled` | 规范化后仍与受控文本不一致 → **finding**（绝不说"语义等价"） |
| `optional` | 缺失 → `not_applicable`，不是缺陷 |
| `semantic_equivalent` | **恒 `unable_to_assess`** + `semantic_equivalence_not_implemented`：本构建不接模型，不靠关键词假装判断 |

模板字段（如 `origin_country`）不在 `fields.yaml` 里，它从 `extra_fields` 读：**抽不到就是"没读到"
（`needs_input`），不是"文档缺值"**。

## 6. 从文件导入（PDF / Word / 图片）

客户不用再手打：点页面右上角 **Import file**，选一个 PDF、Word（`.docx`）或图片（`.png/.jpg`），
服务器解析成文本后填进中间栏，你再改再点 `Run spec audit`。

**前置条件（仅图片和扫描件需要）**：本地 OCR 引擎。macOS：

```bash
brew install tesseract tesseract-lang     # 5.5.4；语言包提供 chi_sim
# 可选：语言与 dpi（默认 chi_sim+eng / 300）
export SMART_EDIT_OCR_LANGS=chi_sim+eng
```

纯文本 PDF 与 DOCX **不需要**它；引擎缺失时只有图片/扫描件会失败，并且会明确告诉你原因。

| 输入 | 怎么读 | 结果里的 `form` |
|---|---|---|
| 带文本层的 PDF | pymupdf 文本层，带页号与区域 | `pdf_text` |
| 扫描版 PDF | 逐页 OCR（需 tesseract） | `pdf_text`（但文本是识别来的） |
| Word `.docx` | 标准库解 zip + XML，只取段落与表格文字，**不执行宏** | `docx_text` |
| PNG / JPEG | OCR（需 tesseract），区域坐标指向图片 | `image_ocr` |
| 纯文本 / `.eml` | 直接读 | `plain_text` / `email` |

界面会做的事：每个文件一行结果（`PDF · text layer` / `Image · recognised text, please check` 等）；
**失败的文件不给"使用这段文本"按钮**，只给原因和「重新上传 / 从空白开始」；多个成功时由你选一个填进去；
若编辑框里已有你打的字，会先问一句再覆盖。

**为什么识别出来的文本要你核对**：OCR 会认错金额和公司名，而审计只认"已确认"的值。OCR 文本对应的
字段一律按 `inferred` 落库，`app/audit/bind.py` 保证未确认的 `inferred` 值让相关检查落到
`needs_input`，**不可能**算通过。所以错字最多变成"请确认"，不会变成"合规"。

失败原因对照（面板上会同时显示人话和错误码）：

| 错误码 | 人话 | 怎么办 |
|---|---|---|
| `unsupported_mime` | 这个类型不支持 | 换 PDF / DOCX / PNG / JPEG；旧版 `.doc` 不支持 |
| `ocr_engine_missing` | 服务器没装 OCR 引擎 | 按上面的 `brew install` 装，或从空白手输 |
| `no_text_recognized` | 识别不出文字 | 传更清晰/正着的图，或手输 |
| `image_open_failed` / `docx_unreadable` / `pdf_open_failed` | 文件打不开 | 重新导出再传 |
| `file_too_large` | 超过 20 MB 上限 | 压缩或拆分 |
| `too_many_pages` | 超过 30 页 OCR 上限 | 只传相关页 |

## 7. 富文本编辑（工具栏 / 表格 / 查找替换）

中间栏现在是**富文本编辑器**（TipTap / ProseMirror），不再是纯文本框。原文的格式（标题、粗斜体、列表、
表格）在导入后会保留下来；**审计仍然只读一份纯文本投影**，所以"看得见格式"没有让审计变得不确定。

| 操作 | 怎么做 |
|---|---|
| 段落 / 标题 H1–H3 | 工具栏 `¶` `H1` `H2` `H3`；按钮会跟随光标所在位置高亮 |
| 粗体 / 斜体 / 下划线 | `B` `I` `U`（或 `⌘/Ctrl + B / I / U`） |
| 无序 / 有序列表 | `•` / `1.` |
| 插入表格 | `⊞`；光标在表格内时 `+R` `−R` `+C` `−C` 增删行列 |
| 撤销 / 重做 | `↶` `↷`（或 `⌘/Ctrl + Z` / `⇧⌘Z`） |
| 查找替换 | `⌕`，可上一处/下一处、替换单个、全部替换（只改命中的文字，不动格式） |

**审计读什么**：编辑器内容先投影成纯文本 —— 标题写成 `# 标题`、列表写成 `- 项` / `1. 项`、表格一行一条
`表头 | 值`，粗体/斜体/下划线**不进入**审计文本（审计判断的是值，不是排版）。这套规则是可测的、
每次结果相同的函数（`web/src/rich/plainText.ts`）；因此同一份文字只改格式，审计结论不会变。

导入后中间栏标题里的 `· imported (deterministic)` / `(heuristic)` 说明结构是怎么来的：
DOCX 是按文件里的样式**确定性**映射；PDF 是按字号与位置**推断**（可能猜错标题级别，改了就好）；
`fallback` 表示这份文件没有可用结构，按段落显示。

**注意**：富文档现在同时存在于**服务端草稿**（`runs/host.db`）和这个浏览器里；版本历史仍是浏览器本地的捕获。
换机器/清缓存后，编辑器会从服务端草稿恢复正文；本地版本历史不会跟着走。

## 7.1 服务端草稿、自动保存与冲突（Hybrid）

- 第一次打开会读取 `GET /documents/demo-document`；没有就创建一个初始草稿。随后自动获取编辑锁。
- 停止输入 2 秒后自动保存：`PUT /documents/{id}/drafts/{draft_id}`，带 `If-Match: "draft-<revision>"` 和
  `lock_id` / `fencing_token`。编辑器底部会显示 `Saving…` / `Saved to server` / `Save failed` /
  `Save conflict`；只有服务端接受后才显示 `Saved to server`。
- **412 冲突时不会替换编辑器内容**：本地文字保留，恢复草稿写入
  `localStorage["smart-edit:recovery:demo-document"]`，冲突面板显示服务端 revision/摘要，并提供
  `Use server version` / `Overwrite with local content` / `Keep local as recovery draft`。
- 恢复本地版本会通过正常自动保存写成**新的服务端 revision**，不会改写历史。
- 变量独立于正文版本：正文 autosave 不再携带 `variables`，不会清空变量或推进 `variables_version`；变量更新走
  `PATCH /documents/{id}/drafts/{draft_id}/variables`，带 `If-Match: "variables-<version>"`。本 build 的变量编辑
  UI 只存在于 Automation 工作台 mock 层（`variableReference` 是正文节点），不会写服务端 variable table。
- 这是 local/test 的本地宿主：单进程、单 writer、fake 身份；production 会失败关闭。不能据此声称支持多用户或生产部署。

## 7.2 Automation tab（fixture-backed 三块工作台）

右栏 **AI assistant → Automation · fixture only** 现在是前端先行工作台，同一页面内有三块区域：

1. **Template**：把当前**导入或本地编辑**的文档存为 template。保存前有 live preview：来源
   （`Imported · deterministic/heuristic/fallback`，含 provenance note，或 `Edited in this browser`）、draft
   revision（无 draft 显示 `No server draft`）、字符数、variable 摘要、下一个版本；同名时提示“另存为新版本 vN”，
   不会覆盖。保存后生成卡片列表，可选中查看详情（来源、捕获时间、字符数、variables、240 字内容摘录）、
   inline 重命名（空值拒绝）和两步确认删除；模板是**快照**，之后编辑正文不会改变已保存内容。
   模板保存在浏览器 `localStorage`（key `smart-edit:automation-templates`，最多 20 个，最旧淘汰），刷新/重开
   仍在；UI 明确写 `Saved in this browser — not on the server`，不是服务端持久化，也不能跨设备。
   模板详情可 `Apply to editor`：当前文档有内容时两步确认，空文档直接应用；保留模板里的变量值/provenance，
   应用后走 editor 的 autosave，模板本身不变。Variables 区域的 `Save to template` 用当前文档更新某个已有模板：
   同一 id/name，version+1，旧快照被替换（两步确认；本 build 没有版本历史/回滚）。
2. **Variables & Fill**：在正文选中一个 paragraph/heading 内的非空文本 → 右键 `Mark as variable`、工具栏按钮或
   `Alt+Shift+V` → 填写 label/type/required → 选区变成一个 `variableReference` chip（初始值是选中文本）。
   变量列表显示 value/type/required 与每个 occurrence；`Fill all occurrences` 会先显示每个 occurrence 的
   before/after，确认后只改同一 `variableId` 的节点，不改变同名普通文本。同名变量被删除时，required 变量会显示
   “reported as missing”，不会静默消失。
3. **Downstream Mapping**：`Downstream source` 可选 `Synthetic fixture` 或 `OpenAPI JSON`。
   - `Synthetic fixture`：选择一个 synthetic 下游 API template（`application_type` enum
     `[guarantee, standby_dc]`），`Match document` 做确定性关键词匹配并给出 evidence；每个字段必须显式
     `Confirm` 后才进入 payload；冲突显示 `ambiguous`，没有依据显示 `missing`。JSON preview 绑定 mock template
     version + 当前文档 digest，缺口时状态是 `mapping_not_ready`。
     日期字段（如 `Expiry date`）支持 ISO、`YYYY/MM/DD`、`DD/MM/YYYY`、`DD/MM/YY`、`YYYY年MM月DD日`
     和英文月份名，统一规范化成 `YYYY-MM-DD` 后再进入 payload；`12/03/27` → `2027-03-12`（DD/MM 默认，
     MM/DD 仅在第二段 >12 时使用）；无效日历日期保持 `missing`。
   - `OpenAPI JSON`：先选择/创建一个**下游系统**（`Downstream system`）；系统包含 name、baseUrl、environment、enabled、auth type/hint 与绑定的 OpenAPI 3.x JSON，存浏览器 `localStorage`（首次从 mock 预设种入，最多 10 个，单 spec ≤ 512 KB；不存真实 token）。`Manage systems` 里新增/编辑/删除系统并上传或粘贴 spec；选择系统后自动解析其 spec，切换系统会清空 operation/mapping（变量保留）。
   - 选择带 `application/json` requestBody 的 operation，schema 的 object properties 会展开成 dotted path；变量按 label 自动建议、可手动改；required 缺失、enum 不匹配、number/integer/boolean 转换失败都会 `not_ready` 并指出字段。就绪后可 `Download JSON` 下载请求文件；界面固定 `Not sent`。
   - `Send (mock)`：只有 payload ready 且 system enabled 时可用；默认返回 200 `mock_success`，勾选 `Simulate failure` 返回 500 `MOCK_DOWNSTREAM_ERROR`。receipt 显示 method + endpoint、status、requestId、payload 与 `Simulated — no network request`；不触网、不保存发送历史。
   - 支持本地 `$ref`（含循环检测）；YAML、Swagger 2.0、URL 拉取、外部 `$ref`、`oneOf`/`anyOf` 明确不支持。

边界与未实现：

- Synthetic fixture mapping 是 **mock**；OpenAPI JSON 在浏览器内**真实解析**并支持不触网的 mock send；template 与下游系统配置是**浏览器本地存储**（非服务端）。都不调用真实解析服务、模型或下游系统。
- **真实发送未实现**：`Send (mock)` 只生成模拟 receipt，固定 `Simulated — no network request`；`Download JSON` 只下载本地生成的文件。没有真实 HTTP 请求、代理、token 读取或发送历史。
- 未实现：template/下游系统的服务端持久化与凭据 DB、用模板新建新文档、真实 HTTP 发送/后端代理/审计/幂等、Swagger 2.0/YAML/URL 拉取/外部 `$ref`/`oneOf`·`anyOf`、真实 extract/confirm、真实语义匹配/模型、compare、rewrite、voice。
- 浏览器存储失败（配额、隐私模式）或数据损坏时：界面显示可读提示，条目标记 `Session only — browser storage failed`
  或忽略无效数据；不会伪造“已保存”。
- 旧的 `rewrite/replace_text` fixture run 面板不再占据 Automation 主视图；run/result/apply/undo 合同仍由
  API 与 `tests/test_automation_apply.py` 覆盖。
- rich editor 无法启动时（textarea fallback），正文只显示 `{{label}}`，变量动作被禁用并说明需要 rich editor。

## 8. 知识助手（Knowledge Q&A）

右栏除了 **Rule audit**，还有 **Knowledge Q&A**（Legal 仍明确标 `not implemented`；Automation 为 `fixture only`）。它只做
"解释 + 引用 + 弃答/澄清/转交"，**不改正文、不审批、不提交、不联网**。

当前演示语料为 **8 个 synthetic source / 74 chunks**（中文 37 + 英文 37：产品 12、规则 13、内部政策 8、帮助指南 4，各一份英文镜像），全部标
`Fixture-backed`；评测集为 **33 题**（31 个回答题 + 2 个澄清题）。已有本地 `runs/assistant.db` 会在 local/test 启动时补种/升级；若补种失败，删除重建或按下面的 CLI 走 `import → review`。

首次打开知识 tab 默认显示英文 **Can / Cannot / How** 引导卡片和 3 个英文快捷问题（有选区时为
`What does this passage mean?`）。点击快捷问题只填入输入框，不会自动提交；第一次回答后折叠为 `Show examples`。

可直接演示的问题：`What can you do?`、`What can this assistant not do?`、`How should I ask a question?`、
`What documents are required for the application?`、`What does URDG 758 article 20 require for claims?`、
`What is guarantee?`。
中文问题仍按中文语料回答；`什么是guarantee` 会解释保函定义，`URDG 758 是否适用于德国？` 会走澄清，
`帮我改写这段条款` 会转交。

一次提问做的事（Network 面板可见）：

```
POST /api/assistant/snapshots                 {document_id, text, content_sha256, version_label}
POST /api/assistant/sessions                  首次提问时创建，绑定当前快照摘要
POST /api/assistant/sessions/{id}/runs        返回 202 + Run；前端按 poll_after_ms 轮询
GET  /api/assistant/runs/{id}                 直到 succeeded / failed / cancelled / timed_out
GET  /api/assistant/messages/{id}/citations/{cid}   打开引用卡片时读取获准摘录与定位
PUT  /api/assistant/messages/{id}/feedback    Helpful / Not helpful
```

**能看到什么**：`outcome`（answered / needs_clarification / insufficient_evidence / unable_to_assess /
needs_handoff）、`support_level`（strong / qualified / insufficient / not_applicable）、Claim 级引用、
`limitations`、澄清问题、转交目标；点引用卡片只显示**本次获准的摘录**和定位（章节/页码/选区偏移），
不返回整份来源或对象存储地址。会话绑定快照；编辑器改了文字后会话会显示"旧快照，请新建会话"。

**三条诚实边界**：

| 看到 | 含义 |
|---|---|
| 顶部 `Fixture-backed` 横幅 | 语料是 `fixtures/knowledge/*` 的**合成演示**文本，不是真实法规；回答不是法律意见 |
| `insufficient_evidence` | 检索正常但没有足够证据；**不是**"文档合规" |
| `needs_handoff` | 修改正文/审查/法规结论请求被转交；助手没有执行任何操作 |

**不用浏览器也能看知识层**（导入 → 待审核 → 独立审核 → 发布 → 撤回）：

```bash
.venv/bin/python -m app.knowledge.cli --db runs/assistant.db seed
.venv/bin/python -m app.knowledge.cli --db runs/assistant.db list --source KS-PRODUCT-001
.venv/bin/python -m app.knowledge.cli --db runs/assistant.db withdraw \
  --source KS-PRODUCT-001 --reason "superseded by policy"
.venv/bin/python scripts/assistant_eval.py      # 33 个合成问题的引用命中/弃答/澄清报告
# 实测：outcome_accuracy 1.0 · citation_hit_rate 1.0（31 个回答题 + 2 个澄清题）
```

**A 不做（C 再做）**：PostgreSQL、真实 Worker/队列、真实身份/组织 ACL、宿主快照服务、真实向量检索与
重排、真实外部搜索服务商与生产凭据、语音/截图、管理端 UI、导出。`SMART_EDIT_ASSISTANT_MODE=production`
时，除“已登记 approved processor 的真实模型 provider”之外的配置会**启动失败**，而不是假装生产可用。

### 8.1 联网 / 本地 RAG / 出站闸门（knowledge-assistant-web-rag）

默认全部关闭：不配置 provider 时，知识助手仍只查本地已发布语料与文档快照，**不会发出任何外部请求**。

| 能力 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| 真实模型 | `SMART_EDIT_ASSISTANT_MODEL=doubao:<model>` + `SMART_EDIT_ASSISTANT_API_KEY` | 空（fixture composer） | Ark **Responses API**（`POST /responses`、`stream:false`、无 tools）；输出必须通过 schema 校验 |
| 处理方批准 | `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED=1` | 0 | 只有登记为 approved processor 才允许发送“问题 + 证据包”；未登记一律拒绝 |
| 通用联网 | `SMART_EDIT_ASSISTANT_GENERAL_WEB=1` | 0 | 只回答"范围外且非转交"的问题，且只挂一个只读 `web_search` 工具；结果标 `general_web`，等级封顶 `qualified` |
| 检索关键字上限 | `SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD` | 3（1–5） | 传给提供方搜索工具的 `max_keyword` |
| 隐藏推理 | `SMART_EDIT_ASSISTANT_THINKING` | 0 | 默认关闭以降低延迟（单次 10–60s）；需要更强推理时设为 1 |
| 联网层 | `SMART_EDIT_ASSISTANT_WEB=off\|fixture\|http` + `SMART_EDIT_ASSISTANT_WEB_ENDPOINT` | off | 每轮由用户勾选才执行；结果只保留准入域名内的页面 |
| 本地 RAG | `SMART_EDIT_ASSISTANT_RAG_ENDPOINT`（可选 `…_RAG_API_KEY`） | 空（用本地词法检索） | 作为第二层；失败会显式降级，不会冒充“两层都查过” |
| 出站策略 | `SMART_EDIT_ASSISTANT_EGRESS_POLICY` | `app/configs/egress.yaml` | 文件缺失/损坏 = 拒绝所有联网请求；判定结果写审计 |

界面路径：**Knowledge Q&A → 勾选 `Search the web for the latest`** → 面板显示“将发送 / 不会发送”；
回答的引用按 `Published corpus` / `Web` / `General web` / `Document` 分区；网页条目显示域名、抓取时间与
`Unverified third-party`；被拦截时显示 `Web search blocked (<reason>)`，不会伪装成“没搜到”。

通用联网通道（`GENERAL_WEB=1`）对**范围外且不转交**的问题生效（例如“今天有什么热点新闻”），
并在 **in-scope 问题本地语料给不出任何可引用证据时回退**（回答会同时标注“已发布语料未能回答”和
“未核验第三方内容”）。
这类回答会额外显示 `General web answer — unverified third-party content` 提示，引用来自
`general_web`，且规则版本/适用范围类结论永远不会由它支撑；改写、审查、法规类问题仍然转交。

**为什么没联网？** 先看 `GET /assistant/capabilities`，不要靠猜：

| 字段 | 含义 |
|---|---|
| `model.configured` / `label` | 是否配置了真实模型；`false` 时回答里的 `processor` 就是 `fixture` |
| `model.approved_processor` | 是否允许把问题/证据发给该提供方 |
| `layers.approved_web` | 是否装配了准入域名的自建 web provider |
| `layers.general_web` | 是否允许提供方的只读 `web_search` 工具 |
| `egress.loaded` / `allowed_domains` | 出站策略是否可用、准入域名数量 |

**如何确认真的调用了豆包**：能力接口只能证明“已配置”，要证明“这一次真的发了请求”，看回答底部的
`Processor: doubao:<model>` 与运行记录；`fixture` 表示未配置模型。知识类问题（产品 FAQ、规则解释、
文档选区）在配置了豆包后不会回退到 fixture：调用失败会显式 `failed`（`MODEL_*`），不会静默改答。
转交（handoff）、澄清（needs_clarification）和未启用通用联网的范围外问题由确定性分支生成，不调用模型，
其 `processor` 仍显示配置的提供方标签，不能用它证明发生了模型调用。

```bash
# 当前部署能力（不泄露 key）
curl -s http://127.0.0.1:8000/assistant/capabilities -H 'X-Demo-User: user_demo_01' | python3 -m json.tool

# 最近几次运行实际使用的 processor
sqlite3 runs/assistant.db \
  "select id, json_extract(result_json,'\$.processor') from assistant_runs order by created_at desc limit 5;"
```

回答本身也会带 `route`（`published / document / general_web / handoff / none`）与
`web` 摘要（`requested / status / reason / hint`）：面板据此显示
`Web search skipped (web_unavailable)` 或 `Answered from published sources · web not needed`，
两种开关都不具备时联网开关会直接置灰。

回滚：把 `SMART_EDIT_ASSISTANT_WEB` 改回 `off`、`GENERAL_WEB` 置 0、清空模型配置即可回到原行为。

**Sample input from UI
```
建议直接试这些问题（fixture 都能命中）
目的	问题	预期
产品 FAQ	提交版本后编辑锁会释放吗？	answered，引用产品手册
文件导入	支持导入哪些文件类型？	answered，引用文件导入段
规则解释	URDG 758 第 20 条对索赔有什么要求？	answered，引用贸易规则
缺信息澄清	URDG 758 是否适用于德国？	needs_clarification（问规则版本/法域/日期）
文档选区	选中 URDG 758，问 这段规则是什么意思？	answered，引用 document_snapshot，定位带选区偏移
无证据	How do I enable dark mode in the toolbar?	insufficient_evidence，无伪造引用
转交	帮我改写这段条款 / 帮我检查这份文档	needs_handoff（automation / standards_audit）
```

## 9. 不开浏览器也能验证同一条链路

```bash
# 1) 引擎本体（无 HTTP、无模型）
.venv/bin/python scripts/audit_demo.py              # 三种文档：0.647 / 0.529 / 0.020 + 闸门决策
.venv/bin/python -m app.rules.doctor                # 规则包体检，退出码即门禁
.venv/bin/python scripts/automation_demo.py         # fixture 提案→接受→应用→撤销（内存库，无模型）

# 2) 前端 + 真实 HTTP 的端到端（后端放在 8010，避免和浏览器环境互相干扰）
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
  .venv/bin/uvicorn app.api.main:app --port 8010 --log-level warning &
VITE_E2E=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.audit.test.ts
# 期望：parse:done extract:done normalize:done audit:done | audit: 33/51 no_findings | gate: not-asked

# 3) 诚实路径（同一后端去掉 SMART_EDIT_LLM，换端口 8011）
VITE_E2E_HONESTY=1 VITE_API_BASE=http://127.0.0.1:8011 \
  npm --prefix web run test -- src/e2e.audit.test.ts
# 期望：did-not-run | no model provider configured | Field checks did not run

# 4) 全部回归
.venv/bin/python -m pytest -q \
  && npm --prefix web run test \
  && npm --prefix web run typecheck \
  && npm --prefix web run build
# 实测：539 passed（知识助手 HTTP、document host、automation run/result/apply/undo、protected facts、variable projection parity）· 345 前端测试通过（含 template store / apply / template 更新 / 下游系统 store / OpenAPI 解析与下载 / mock send / beneficiary label variants / date normalisation） · typecheck/build clean

# 5) 真浏览器里的知识助手与草稿/冲突/apply（Playwright 会自己起 8000/8010/5173/5174）
PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/knowledge.spec.ts --project=desktop
PW_CHANNEL=chrome npm --prefix web run e2e -- e2e/draft.spec.ts --project=desktop
```

## 10. 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `409 unknown_stage: unregistered stage target: audit` | 起的是**旧进程**（改动前启动的） | 杀掉该端口进程再起，见 §1 的 `kill -9` 一行 |
| `Port 5173 is in use` | 上一个 `npm run dev` 还活着 | 同上 |
| 面板 `HTTP_500 … backend is not running` | 后端没起（vite 日志会有 `ECONNREFUSED 127.0.0.1:8000`） | 起终端 A |
| `Checks did not run` | 后端没设 `SMART_EDIT_LLM` | 按 §1 带 fixture 重启，或接受诚实路径 |
| Gate 一直是 `Not asked` | 正常：UI 目前不问闸门（`/audit/*` 属后续 change） | 想验闸门语义用 `scripts/audit_demo.py`，或 `app/audit/gate.py::evaluate(state, "start_approval", digest)` |
| 刚点完就 `Report is stale` | 审计开始后编辑框内容变了（含末尾多一个换行） | 保持文本不动再跑一次 |
| 编辑器底部 `Save conflict` | 服务端草稿被另一个标签页/操作推进了 revision | 用冲突面板选择 `Use server version` / `Overwrite with local content`；本地内容已存为恢复草稿 |
| `lock_conflict` / `409` | 同一草稿已有活动锁（另一个标签页或旧进程） | 关闭另一个页面，或重启后端释放本地锁；不要绕过锁直接改 `host.db` |
| `undo_conflict` | apply 之后又有人改了正文 | 基于当前头重新生成提案；不要尝试撤销旧回执 |

两个 digest 不要混：面板底部的 `server digest` 是后端对"文件＋字段"做的规范化哈希，左侧快照的
digest 是浏览器对纯文本做的 SHA-256，**算法不同**，代码里也刻意不比较它们。

## 11. 想再进一步

- 换真实文档：不设 `SMART_EDIT_LLM` 走诚实路径；要真抽取需接 provider（`openai:` 仍是保留值）。
- 加规则：改 `app/rules/bundles/guarantee.yaml`，先 `python -m app.rules.doctor` 过门禁（每条规则必须有
  `pass` / `finding` / `needs_input` 向量）。
- 让界面能问闸门：需要"询问某个受保护操作"的入口（`gate` 槽位已就绪，属 `console-api` / `editor-shell`）。


想停服务：`lsof -nP -iTCP:8000,5173 -sTCP:LISTEN -t | xargs kill -9`
