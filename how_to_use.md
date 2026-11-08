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
| 后端 / 前端测试 | 281 / 101 全绿 | `.venv/bin/python -m pytest -q`、`npm --prefix web run test` |

还没做（跑的时候会看到"未实现"而不是假成功）：文件导入/OCR、富文本格式、导出、审批流、语义检查、法规覆盖。

## 1. 起两个终端

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

## 5. 不开浏览器也能验证同一条链路

```bash
# 1) 引擎本体（无 HTTP、无模型）
.venv/bin/python scripts/audit_demo.py              # 三种文档：0.647 / 0.529 / 0.020 + 闸门决策
.venv/bin/python -m app.rules.doctor                # 规则包体检，退出码即门禁

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
.venv/bin/python -m pytest -q && npm --prefix web run test && npm --prefix web run typecheck
```

## 6. 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `409 unknown_stage: unregistered stage target: audit` | 起的是**旧进程**（改动前启动的） | 杀掉该端口进程再起，见 §1 的 `kill -9` 一行 |
| `Port 5173 is in use` | 上一个 `npm run dev` 还活着 | 同上 |
| 面板 `HTTP_500 … backend is not running` | 后端没起（vite 日志会有 `ECONNREFUSED 127.0.0.1:8000`） | 起终端 A |
| `Checks did not run` | 后端没设 `SMART_EDIT_LLM` | 按 §1 带 fixture 重启，或接受诚实路径 |
| Gate 一直是 `Not asked` | 正常：UI 目前不问闸门（`/audit/*` 属后续 change） | 想验闸门语义用 `scripts/audit_demo.py`，或 `app/audit/gate.py::evaluate(state, "start_approval", digest)` |
| 刚点完就 `Report is stale` | 审计开始后编辑框内容变了（含末尾多一个换行） | 保持文本不动再跑一次 |

两个 digest 不要混：面板底部的 `server digest` 是后端对"文件＋字段"做的规范化哈希，左侧快照的
digest 是浏览器对纯文本做的 SHA-256，**算法不同**，代码里也刻意不比较它们。

## 7. 想再进一步

- 换真实文档：不设 `SMART_EDIT_LLM` 走诚实路径；要真抽取需接 provider（`openai:` 仍是保留值）。
- 加规则：改 `app/rules/bundles/guarantee.yaml`，先 `python -m app.rules.doctor` 过门禁（每条规则必须有
  `pass` / `finding` / `needs_input` 向量）。
- 让界面能问闸门：需要"询问某个受保护操作"的入口（`gate` 槽位已就绪，属 `console-api` / `editor-shell`）。