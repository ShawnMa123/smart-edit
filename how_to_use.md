# 怎么从界面跑一次端到端（UI → normalize → audit）

> 这份文件回答一个问题：**现在想让一份保函从浏览器点进去、走完标准化再走完规范审计，我该敲什么、该点哪、该看到什么。**
> 所有数字都是本机实测（2026-11-08），不是估算。

## 0. 现在能跑什么（先对齐预期）

| 能力 | 状态 | 证据 |
|---|---|---|
| 后端 HTTP（创建 run、触发阶段、读信封） | 能跑 | `app/api/main.py`，`supported_stages = audit/extract/normalize/parse` |
| 标准化（`agent1`：parse → extract → normalize） | 能跑 | fixture 模型下 8 个字段 `extracted`，出处可定位 |
| 规范审计（`agent4`：`stages/audit`） | 能跑 | 每份保函 **56** 个计划单元，干净文档评估 **37** 项（ratio 0.661），引擎模型调用 **0** |
| 三栏界面 + 右栏「Rule audit」 | 能跑 | `npm --prefix web run dev` → http://localhost:5173 |
| 右栏「Knowledge Q&A」知识助手（fixture 语料） | 能跑 | `/api/assistant/*`：202 + 轮询、Claim 级引用、support_level、澄清/弃答/转交、反馈 |
| 后端 / 前端测试 | 539 后端 / 345 前端全绿 | `.venv/bin/python -m pytest -q`、`npm --prefix web run test` |

还没做（跑的时候会看到"未实现"而不是假成功）：语义检查、法规覆盖；Legal tab 已点亮 L1（法规问答 +
合成规则检查，见 §7.4）；Automation tab 只有
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
   > `fixture:` 只是 demo / 回归路径；真实文本请用 `?profile=guarantee-default`（见 §5.5），否则审计的是
   > 录制文件里的值，而不是你编辑的内容。
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
| Rule audit | **`No findings reported`**，`37 of 56 planned checks assessed · ratio 0.661`（审计日期用 `?as_of=2026-03-12`） |
| 指标卡 | Planned 56 · Assessed 37 · Not applicable 19 · Needs input 0 · Hard blocks 0 |
| 提取来源 | 「Where the values came from」显示 `Fixture replay (demo, not this document)` + `audit date 2026-03-12` |
| Gate | **`Not asked`** + "nothing is allowed"（审计本身不判定任何操作，这是设计） |
| 字段表 | 8 个字段 `Extracted`；金额 `500000.00`，原文 `USD 500,000.00` 可回溯 |
| 页脚 | `engine 1.0.0 · schema 044a959e73af · bundle company-guarantee v1.0.0, guarantee-core v1.0.0 · server digest …` |

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
> 这条路径只适用于**既没有 profile、也没有模型**。指定 `?profile=guarantee-default` 时提取是确定性的，
> 不需要模型，`extract` 仍会 `done`（`model_calls=0`）。

## 5. 按客户模板审（模板驱动审计）

审计默认只按"基础字段字典 + 银行/公司规则包"跑（56 个单元）。**模板驱动是显式请求的**：你要审的是"和阿迪达斯的
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
| 计划单元 | **63** = 39 基础字段 + `origin_country` 类型单元 + 11 规则 + 6 证据 + **6 模板单元**（3 字段期望 + 2 条款 + 1 声明） |
| 结论 | `no_findings`，`complete`，覆盖率 **0.698**（44 项已评估） |
| 模板基线 | `verification.audit.template`：`adidas-guarantee` v1.0.0、`synthetic: true`、`resolved_from.beneficiary_name = Adidas AG`、`policy_packs: company-guarantee v1.0.0 + guarantee-core v1.0.0`、`conflicts: []` |

模板没命中（文档对手方不是 Adidas）或同时命中两份时，**不猜**：

| 情形 | 结果 |
|---|---|
| 0 份匹配 | 计划 57（多一个 `TEMPLATE:resolution`），`unable_to_assess` + `no_applicable_template`，闸门不放行 |
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

## 5.5 确定性提取（真实文本，不再回放 fixture）

`fixture:` 只用于 demo / 回归：它不看编辑区文本，永远返回录制好的那 8 个候选值。真实文本请指定**已发布的
extraction profile**；`extract` 会按 label/alias 从当前 `docs.blocks` 定位值，`model_calls=0`，同一文本 +
同一 profile 的结果可复现。

- profile 位置：`app/configs/extraction/guarantee-default.json`；目录可用
  `SMART_EDIT_EXTRACTION_PROFILES=<dir>` 覆盖。
- `fields.yaml` 决定“字段是什么”，profile 只**引用** key，声明 labels、`value_kind`、`search`
  （`same_block` / `same_or_next_block`）、`max_chars`、confidence。profile 不接受正则或脚本；未知 key、
  未知 `value_kind`、未发布、`document_types` 不匹配都会加载失败。
- 解析顺序：请求 `?profile=` > template 的 `extraction_profile` > 无 profile（走原 fixture/LLM 路径）。
- 显式 profile 只替换提取，**不会**跳过 template fields/clauses 或公司规则包；未知/未发布/类型不匹配的
  profile 直接 `400 invalid_extraction_profile`，不会静默回落 fixture。

```bash
# 不设 SMART_EDIT_LLM 也能跑确定性提取
curl -s -X POST \
  "localhost:8000/runs/$TID/stages/audit?profile=guarantee-default&as_of=2026-03-12" \
  | python3 -m json.tool | head -40
```

报告里看什么：

| 字段 | 含义 |
|---|---|
| `verification.extraction.source` | `deterministic` / `fixture` / `llm` / `unknown`（绝不冒充 deterministic） |
| `verification.extraction.profile_id / version / content_sha256` | 哪一版 profile 读的这份文档 |
| `fields_found` / `fields_missing` | 定位成功/缺失的字段数；缺字段由 `normalize` 生成 missing 占位 |
| `verification.policy.as_of` / `verification.audit.as_of` | 本次审计基准日（`relative_date: today` 用它） |
| 字段 `notes` 里的 `extraction_conflict` | 同一字段出现两个不同值，已降级为 `inferred`，规则不会 pass |

`?as_of=YYYY-MM-DD` 固定审计日期（缺省服务器当天并回显）；同一文本 + 同一 `as_of` 重放结果一致。
公司规则包在 `app/rules/bundles/company-guarantee.yaml`（Issue Date 不早于 today、金额上限、URDG 758、
付款条款、允许币种）；每条规则带 pass/finding/needs_input 向量，发布前跑：

```bash
.venv/bin/python -m app.rules.doctor
```

新增字段：在 `fields.yaml` 声明 key/type，在 profile JSON 加 locator（必要时新增受测 `value_kind`）；
新增公司规则：复制 bundle、改版本与向量，doctor 全绿后再发布。

### 在页面上测（不需要模型）

1. `./scripts/dev.sh --honest` —— 后端**不配** `SMART_EDIT_LLM`。没有 profile 时它会诚实失败；
   这一步用来证明确定性 profile 不依赖模型。
2. 中间栏粘贴（`开立日期` 用**服务器当天**；本机环境是 2026-11-20）：

   ```text
   保函编号：BG-2026-0001
   保函金额：USD 500,000.00
   币种：USD
   开立日期：2026-11-20
   到期日：2027-11-20
   适用规则：URDG 758
   付款条件：
   Payment shall be made in USD within 30 days of presentation.
   ```

3. 右栏 **Rule audit** → **Customer template** 填 `adidas-guarantee`（该模板声明
   `extraction_profile: guarantee-default`）→ **Run spec audit**。
4. 期望：Stages 四个 `Done`；`extract` 的 reason 是 `deterministic profile guarantee-default@1.0.0`；
   「Where the values came from」显示 `Deterministic profile · guarantee-default v1.0.0`、
   `6 fields found · 0 missing`、`audit date 2026-11-20`。
   因为当前 profile 只覆盖 6 个字段，`guarantee_number / applicant_name / beneficiary_name` 会是
   `missing` 并产生 3 条 required finding —— 这是 profile 覆盖范围的预期结果，不是读取失败。
5. 再验证“读的是当前文本”：把 `开立日期` 改成前一天（2026-11-19）→ 再点 Run → 出现
   `CO-ISSUE-NOT-PAST`；把 `保函金额` 改成 `-500.00` → 再点 Run → 出现 `GR-AMOUNT-POSITIVE`。

已知限制：页面没有 `?as_of=` / `?profile=` 输入框（`as_of` 用服务器当天，profile 由模板选出）；
当前 `guarantee-default` 只覆盖 6 个字段，不含 `beneficiary_name`，所以模板的对手方匹配会显示
「Template could not be resolved」。这不影响确定性提取与公司规则包，来源块仍会显示 `deterministic`。
需要完整模板/条款演示时，用 §5.5 的 API 调用，或在 profile 中补充 `beneficiary_name` locator。

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

### 7.3 提交、审批与只读

`Submit new version` 在 `AUTH_MODE=pg` 下是真实提交：冻结当前 revision 与正文，释放编辑锁，并把文档变为只读。`Pending first / Pending second / Approved` 期间不能加锁或保存；`Returned` 后可以修改并重新提交。操作流程与预置账号见 §8.3.1。

提交后界面使用同一套审批状态：

- 文档头显示真实状态徽标（`Pending first approval` / `Pending second approval` / `Approved` / `Returned` / `Rejected`），不再固定显示 `Draft`；`Draft` 只在尚未提交时出现。
- 文档上方出现 **Waiting banner + 四步进度**（Submitted → Bank Operations → Compliance → Approved），显示当前等待角色、提交时间、revision、最近意见与只读原因；退回时显示退回意见并提示重新提交。
- **审批路由按提交方**：`applicant` 提交 → `bankops` 一审 → `compliance` 二审；`bankops` / `org_admin` 提交 →
  **`applicant`（对方公司）一审** → `compliance` 二审。首审标签会显示 `Applicant (counterparty)`，
  文头提示 `Waiting for the counterparty (Applicant)`。自审仍被禁止（提交人不能审自己的单）。
- 顶部 **Approval** 入口显示当前角色的服务端待办数（0 时隐藏，>99 显示 `99+`）；**Activity** badge 使用 `/activity/unread-count`，不再拿浏览器本地通知冒充服务器待办。
- 提交成功、审批决策、复制邀请使用 success / info / warning / error **Toast**；失败保留当前表单或详情并显示 error。只读、退回意见和冲突仍使用内联 banner。
- 申请人在 pending 状态每 **10s** 自动刷新：页面隐藏时暂停，`Approved / Returned / Rejected` 后停止；审批人通过后无需手动刷新即可看到下一阶段。

端到端演示（使用 seed 账号，自动跑完两级审批与退回重提）：

```bash
.venv/bin/python scripts/demo_submission_approval.py
```

## 7.4 Legal advice tab（L1，`/legal/*`）

右栏 **AI assistant → Legal advice** 已点亮（角标 `Full`），有两个子模式：

1. **Statute advice**：输入法律问题（或点一个建议问题）→ `POST /legal/reviews`（`modes=["legal"]`）→
   展示法规建议 + 引用卡片（条文号 / 法域 / 生效日 / 摘录 / chunk id）。正文里的 `[chunk_id]`
   是可点击 chip，会跳到对应引用卡片。没有 `MERCATORIA_*` 配置时 legal 模式返回
   `unable_to_assess · statute_unavailable`，不会假装“无发现”。
2. **Rule check**：`DEMO-AMOUNT-REQUIRED` 合成规则的三种事实态——金额缺失 → `Critical` finding；
   确认 → `pass`；未确认 → `unable_to_assess`。这是 L1 的确定性内核，不是完整 DSL。

诚实性约定（UI 与后端一致）：

- 服务超时 / 法规库更新 / 无命中 / 离题分别显示独立原因，**不会**归为“无发现”；
- `answer_status=unavailable/unsupported` 时即使服务返回了 references，也不会把无关引用展示成答案；
- Finding 卡显示 support level（Strong/Qualified/Insufficient）、gate（Blocks/Advisory）和 limitations。

L1 边界：同步 + 进程内报告（最多保留最近 200 份）、只实现 `exists/compare`；异步 Worker、PG 持久化、
完整 DSL、规则包治理属于后续阶段。

```bash
.venv/bin/python -m pytest tests/test_legal_review.py tests/test_legal_review_legal.py tests/test_legal_api.py
```

## 8. 知识助手（Knowledge Q&A）

右栏除了 **Rule audit**，还有 **Knowledge Q&A**、**Legal advice**（L1，见 §7.4）与 **Automation**（`fixture only`）。它只做
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

检索顺序是固定的：**先查法规语料（RAGFlow / Mercatoria）→ 豆包总结 → 只有语料零结果才自动联网**。
没有配置任何外部 provider 时，知识助手仍只查本地已发布语料与文档快照，**不会发出任何外部请求**。

| 能力 | 环境变量 | 默认 | 说明 |
|---|---|---|---|
| 真实模型 | `SMART_EDIT_ASSISTANT_MODEL=doubao:<model>` + `SMART_EDIT_ASSISTANT_API_KEY` | 空（fixture composer） | Ark **Responses API**（`POST /responses`、`stream:false`、无 tools）；输出必须通过 schema 校验 |
| 处理方批准 | `SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED=1` | 0 | 只有登记为 approved processor 才允许发送“问题 + 证据包”；未登记一律拒绝 |
| 通用联网 | `SMART_EDIT_ASSISTANT_GENERAL_WEB=1` | 0 | 提供只读 `web_search` 工具；结果标 `general_web`，等级封顶 `qualified` |
| 检索关键字上限 | `SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD` | 3（1–5） | 传给提供方搜索工具的 `max_keyword` |
| 隐藏推理 | `SMART_EDIT_ASSISTANT_THINKING` | 0 | 默认关闭以降低延迟（单次 10–60s）；需要更强推理时设为 1 |
| 联网层 | `SMART_EDIT_ASSISTANT_WEB=off\|fixture\|http` + `SMART_EDIT_ASSISTANT_WEB_ENDPOINT` | off | 自建 provider；结果只保留准入域名内的页面 |
| 联网默认开关 | `SMART_EDIT_ASSISTANT_WEB_DEFAULT=on\|off` | **on** | 面板开关的初始值；关闭即本次不联网（仍查 RAG 与本地语料） |
| 本地 RAG | `SMART_EDIT_ASSISTANT_RAG_ENDPOINT`（可选 `…_RAG_API_KEY`） | 空（用本地词法检索） | 作为第二层；失败会显式降级，不会冒充“两层都查过” |
| 出站策略 | `SMART_EDIT_ASSISTANT_EGRESS_POLICY` | `app/configs/egress.yaml` | 文件缺失/损坏 = 拒绝所有联网请求；判定结果写审计 |

**RAG 优先**：法规命中（包括 `confidence=low`、`requested_uncovered`）不再被丢弃，统一交给豆包总结并附
“低置信，仅供参考 / 该法域未被语料覆盖”的限定说明。只有 `/v1/retrieve` 返回**零条文本、失败或超时**时，
系统才自动走豆包联网；联网同样过出站策略、写审计，并标注“未核验第三方内容”。

**界面路径**：`Knowledge Q&A` → 联网开关默认勾选，可显式关闭 → 提问。面板显示“将发送 / 不会发送”；
引用按 `Published corpus` / `Statute` / `Web` / `General web` / `Document` 分区；网页条目显示域名、抓取时间与
`Unverified third-party`；RAG 零结果自动联网时显示
`RAG returned no result — searched the web automatically (unverified)`；被拦截时显示
`Web search blocked (<reason>)`，不会伪装成“没搜到”。

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

回答本身也会带 `route`（`published / statute / document / general_web / handoff / none`）与
`web` 摘要（`requested / status / reason / hint`）：面板据此显示
`Web search skipped (web_unavailable)` 或 `Answered from published sources · web not needed`，
两种开关都不具备时联网开关会直接置灰。

回滚：把 `SMART_EDIT_ASSISTANT_WEB` 改回 `off`、`GENERAL_WEB` 置 0、清空模型配置即可回到原行为。

### 8.2 法规腿（Mercatoria `/v1/chat` + 豆包结构化，`knowledge-statute-chat`）

默认关闭。开启后，**规则解释与显式声明法域/交易日/规则版本的问题**会先调用 `/v1/chat`（检索 + 服务端草稿），
再把草稿交给豆包做结构化/润色，最终由本服务评审、标注来源（`source_type="statute"`、`route="statute"`）。
`/v1/retrieve` 适配器仍保留（离线回放/回滚），但流水线**不再调用**。产品 FAQ 不查法规——`/v1/chat` 会用
法律语料回答产品问题，因此产品问题只查本地已发布语料。

| 环境变量 | 值 | 说明 |
|---|---|---|
| `SMART_EDIT_STATUTE` | `1` | 总开关；缺 URL 或 token 时**启动失败**，不静默降级 |
| `MERCATORIA_BASE_URL` | 例：`http://59.110.213.187:8080` | 法规语料服务地址（可直连或经 SSH 隧道） |
| `MERCATORIA_API_TOKEN` | `<token>` | Bearer token，只放服务端 |
| `MERCATORIA_CHAT_TIMEOUT` | 默认 `60` | `/v1/chat` 的请求超时（含服务端生成）；检索层预算为它 +10s |

```bash
# 1) 起隧道（实测：mercatoria 容器在 team04-pg 上发布 8080；本地 18080 只是本地端口）
ssh -f -N -L 127.0.0.1:18080:127.0.0.1:8080 team04-pg
#    其他部署把后两段换成 <mercatoria-host>:<port>
curl -s http://127.0.0.1:18080/health | head -c 200   # 应返回 {"status":"ready",...}

# 2) 配置并重启后端
#    .env 里加：SMART_EDIT_STATUTE=1 / MERCATORIA_BASE_URL=http://127.0.0.1:18080 / MERCATORIA_API_TOKEN=...
./scripts/dev.sh

# 3) 启动日志必须出现 statute=True（同时能看到 rag / web 的实际状态）
grep "assistant: model=" runs/logs/backend-*.log | tail -1
# assistant: model=doubao:... web=off rag=False statute=True egress=2026-11-18.1
```

**界面路径**：浏览器打开 `http://127.0.0.1:5173` → 右侧助手面板的 **`Knowledge Q&A`** 标签 → 法域 chips 保持
**`Any`（任意）** → 联网开关默认勾选（可关闭；关闭后仍查 RAG 与本地语料）→ 输入问题 → `Ask`。界面上没有
“法规腿”单独开关，它由服务端 `.env` 决定；打开后**规则类/显式范围问题**先走 chat，**产品 FAQ 不查法规**。回答里：

- `answered`：引用区分组出现 **`Statute (N)`**，徽章带 `jurisdiction / effective <date>`，点开只看获准摘录与条号。
- `partial`：提示 **`Statute answer is partial — the cited evidence is incomplete`**，引用仍可用。
- `unsupported` / `unavailable`：有 references 时**仍用条文证据**作答，并提示 **`The statute service did not return a usable answer`**（回答注明“服务自身答案不可用”）；零 references 才本地/联网回退。
- RAG 零结果：自动联网，显示 **`RAG returned no result — searched the web automatically (unverified)`**。
- 出站被拒：**`Statute search blocked by outbound policy — not covered`**，本次没有任何法规出站。
- 超时/重建：分别显示 `Statute search timed out` / `Statute corpus is being rebuilt`，随后自动联网。
- 豆包结构化失败：用 chat 引用的证据原文作答，并注明“草稿已生成但结构化失败”。

> 注意：`Any` 是推荐值。实测（`knowledge-statute-live` 5.2）定义类问题带法域反而更差：选 `WTO` 后 top chunk
> 变成 WTO 贸易便利化条文且 `confidence=low`；不带法域 + 扩展词才能命中《独立保函规定》。

**触发条件**：规则解释（如 `什么是guarantee`、`URDG 758 第 20 条…`）与显式选了法域/交易日/规则版本的问题；
产品 FAQ 与"选中文字问这段/这句"都不查法规（后者以选区快照为证据）。编辑器里选中一个词**不会**再把主题问题判成文档解释。

**出站闸与合规**：法规调用与联网共用一套判定（用途 `statute`，审计里带 `endpoint="chat"`）——金额/单号/账号/邮箱会被脱敏，
规则号保留；问题与选中文本重叠达到 40 字会被拒绝；隧道/内网地址不参与公网域名白名单。判定结果写审计
（`egress_allowed` / `egress_blocked`，只存 query digest）。被拒绝时不发请求，法规层状态为 `blocked`。
注意：chat 的**生成发生在 Mercatoria 侧**（其自带 LLM），不在本服务的出站审计范围内；部署方需在语料服务侧单独审计。

**成本**：一次规则问题包含**两次模型调用**（Mercatoria chat 生成 + 豆包结构化），延迟与费用都高于旧的 retrieve-only 链路。
若剩余 run deadline < 20 秒，会跳过豆包润色，直接用证据摘录作答。

**各状态都可在运行结果里自证**：

```bash
# 最近一次法规层记录：status / detail（answer_status）/ hits
sqlite3 runs/assistant.db \
  "select json_extract(result_json,'\$.route'),
          json_extract(result_json,'\$.retrieval')
   from assistant_runs order by created_at desc limit 3;"
```

| 状态 | 你会看到 | 含义 |
|---|---|---|
| `answered` | `route="statute"`、`statute/ok/answered`、引用徽章 `Statute`、locator 带条号/法域/生效日 | chat 草稿 + 豆包结构化完成 |
| `partial` | `statute/ok/partial`，附“依据不完整” | 引用仍可用，但覆盖不全 |
| `unsupported` / `unavailable` | `statute/ok/<status>`；有 references 时仍引用条文并注明“服务自身答案不可用”，零 references 才回退 | chat 未给出可用答案 |
| RAG 零结果 | `statute/ok/zero:*`（或 `failed/*`）→ 自动联网，`web.reason="rag_empty"` | 只有此时才联网 |
| 两处皆空 | 零引用 + “知识库检索与联网搜索都没有找到可用证据” | 如实说明，不编造 |
| 出站被拒 | `statute/blocked/policy_unavailable`（或缺策略） | 本次根本没有出站 |

**术语归一化**：`app/configs/knowledge.sample.json` 的 `query_expansion` 会把 `guarantee` 等通用词扩成
`见索即付保函 / 独立保函 / demand guarantee / URDG 758`；每键 ≤4 条、总字符 ≤120，越界由加载器拦截。
想调整召回，改这张表并重启，不需要改代码。

**直接调用 `/v1/chat`（调试/独立脚本）**：助手内部也调用这个端点（`/v1/chat`，检索 + 服务端生成）；这里介绍如何脱离助手直接调用它做对比或排障。
请求支持 `question` 或 `messages`（多轮）、`retrieval_query`、`rewrite_query:false`、`queries[]`、`top_k`、`filters`，
以及 `answer: {"enabled": false}`（只检索）。响应在检索结果之外多出 `answer`、`answer_status`
（`answered / partial / unsupported / unavailable / skipped / error`）、`citations[]`（chunk 级）与
`references[]`（带 `cited` 标记）。回答里的 `[chunk_id]` 就是引用锚点。

```bash
TOKEN=$(grep '^MERCATORIA_API_TOKEN=' .env | cut -d= -f2-)
BASE=$(grep '^MERCATORIA_BASE_URL=' .env | cut -d= -f2-)

# 1) 只检索（不生成）
curl -s "$BASE/v1/chat" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"在wto里，什么是guarantee","top_k":3,"answer":{"enabled":false}}' \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['answer_status']);print([(r['doc_id'],r['article_label']) for r in d['references']])"

# 2) 检索 + 生成（带引用）
curl -s "$BASE/v1/chat" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"独立保函的定义是什么","top_k":3,"answer":{"enabled":true}}' \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['answer_status']);print(d['answer'][:200]);print([(c['doc_id'],c['article_label']) for c in d['citations']])"

# 3) 带法域过滤 + 多轮
curl -s "$BASE/v1/chat" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"guarantee 是什么"}],"top_k":3,"filters":{"jurisdictions":["WTO"]},"answer":{"enabled":true}}'

# 4) 仓库脚本（自动读 .env）
.venv/bin/python scripts/mercatoria_chat.py "独立保函的定义是什么" --top-k 3
.venv/bin/python scripts/mercatoria_chat.py "guarantee" --jurisdiction WTO --top-k 3
.venv/bin/python scripts/mercatoria_chat.py "在wto里，什么是guarantee" --no-answer --json
```

> 注意：`/v1/chat` 与知识助手是两条独立链路。助手用的是 `/v1/retrieve` + 豆包总结 + 出站闸/审计；
> `/v1/chat` 由 Mercatoria 自己的模型生成，引用是 chunk 级，不经过助手的来源标记与审计。
> 若要把 `/v1/chat` 接进助手（例如替代豆包总结），需要单独起一个 change。

**回滚**：清空 `SMART_EDIT_STATUTE`（或设为 `0`）即回到词法-only；没有数据库迁移，历史运行记录不受影响。
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

## 8.3 账号 / 组织 / Activity / Developer（PG 模式）

默认 `AUTH_MODE=fake`，界面继续使用演示身份；要体验真实账号：

```bash
ssh -f -N team04-pg
SMART_EDIT_AUTH_MODE=pg uvicorn app.api.main:app --reload
SMART_EDIT_AUTH_MODE=pg npm --prefix web run dev
```

1. 首次打开会进入登录页；**没有账号就点 “Create one”**：注册会创建账号 + 个人组织（`workspace_id = org_id`），并写入 HttpOnly 会话 cookie。
2. 顶部 Organisation 选择器可切换组织；切换由服务端重新校验成员状态，非成员会被拒绝且保持原组织。
3. **People**：部门树、成员列表、角色抽屉（祖先部门的角色显示 `inherited · read-only`）；邀请只生成一次性链接（v1 不发邮件），复制后线下发送。
4. **Activity**：服务端事件，支持全部 / 我的部门 / 仅未读、单条或全部标为已读；成员被移除后其历史事件仍保留并显示 `Removed user`。
5. **Developer**：需要 `developer.manage`；创建 Key 后原文**只显示一次**，列表只显示前缀。用 Key 调用接口会产生请求日志（method/path/status/latency），可按天/Key/状态看用量。页面明确写 “Webhooks are not available in this version.”。
6. **权限边界**：组织级文档所有成员可读；部门级文档只有祖先链上有 `document.read` 的人可读（Finance 读 Legal 文档返回 403，且不泄露标题/正文）。`?demo=1` 仍可回退到演示数据。

### 8.3.1 预置角色账号（Applicant / 两级审批）

清空身份 mock 数据并写入真实账号（argon2id 哈希入库，明文只打印/写入本地文件）：

```bash
.venv/bin/python scripts/seed_identity_users.py --reset
cat runs/dev/test-users.md
```

| 邮箱 | 密码 | 角色 | 部门 |
| --- | --- | --- | --- |
| `admin@atlas-trade.test` | `AtlasAdmin!2026` | Organisation administrator | — |
| `applicant@atlas-trade.test` | `Applicant!2026` | Applicant | Trade Operations |
| `bankops@atlas-trade.test` | `BankOps!2026` | Bank Operations (First Approver) | Bank Operations |
| `compliance@atlas-trade.test` | `Compliance!2026` | Compliance (Second Approver) | Compliance |
| `auditor@atlas-trade.test` | `Auditor!2026` | Auditor | — |

行为：Applicant 可编辑/加锁/保存 `demo-document`；First/Second Approver 可打开并加锁但不能保存（`403`，页面显示 read-only 提示）；Auditor 只读且无锁权限。

#### 提交与两级审批（v1）

1. Applicant 打开文档并编辑；未提交时文档头与页脚显示 `Draft`。
2. 点 **Submit new version** → **Submit for approval**：
   - 冻结当前 revision、正文、变量与内容摘要；
   - 释放编辑锁，状态变为 `Pending first approval`；
   - 文档头显示 `Pending first approval` 徽标，文档上方出现 **Waiting for Bank Operations** banner、四步进度、提交时间、revision 与只读说明；
   - 文档变为只读，不能加锁/保存；成功 Toast 提供 **View approval** 动作。
3. Bank Operations 登录 → 顶栏 **Approval**（badge 显示待办数）→ **First approval**：
   - 左侧待办选择请求，右侧看到冻结快照与时间线；
   - **Approve** 进入 `Pending second approval`；**Return** 或 **Reject** 必须填写意见；结果以 success/warning/error Toast 呈现。
4. Compliance 登录 → **Approval** → **Second approval** → **Approve** 后状态为 `Approved`，文档保持只读。Applicant 页面在 10s 内自动刷新为 `Approved`，无需手动刷新。
5. 若被退回：Applicant 在文档头/banner 看到 `Returned` 与退回意见，可重新加锁、修改并再次提交；每次提交生成新的 submission，旧审批记录保留。
6. 申请人在 **Approval** → **My submissions** 看到卡片列表（状态/revision/提交时间/当前阶段/最近意见），选中卡片查看冻结快照摘要与时间线；空态显示 `No submissions yet.`。

服务端规则：提交人不能审批自己的请求；审批按组织/部门范围过滤；本轮不发邮件、不接 AI audit gate。API 形态见 README/`document-submission-approval` change。

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
