# Agent 1 / Agent 2 联调交接

> 分支：`fix/agent3-agent4-poc`（已推送）。基线验证（全部在 Docker 容器内）：
>
> - 后端：`655 passed, 1 skipped`
> - 前端：`178 passed, 12 skipped`（skipped 为 E2E 专用）
> - Playwright：`17 passed`
>
> 本文面向：
> - **Agent 1**（共享层 `parse / extract / normalize`）负责人：维护与扩展字段抽取、来源定位、三分类。
> - **Agent 2**（`agent-verify`，业务要件校验）负责人：把当前“诚实拒绝”的 `agent2_node` 换成真实实现，
>   并完成与 Agent 3 / Agent 4 / 闸门的联调。
>
> 目标：两个人各自在本地就能构建 RAG 索引、跑完整主图、跑前端操作、跑审计与导出，不依赖远端服务。

---

## 1. 5 分钟跑通

### 1.1 后端（Docker，推荐回归）

```bash
docker build -f Dockerfile.test -t smart-edit-test .
docker run --rm -v "$PWD:/workspace" smart-edit-test pytest -q
```

### 1.2 前端单元 / 类型

```bash
docker run --rm -v "$PWD:/workspace" -v smart-edit-web-node:/workspace/web/node_modules \
  -w /workspace/web node:22-bookworm-slim sh -c \
  "npm ci && npm run typecheck && npm run test -- --run"
```

### 1.3 浏览器 E2E（Playwright 镜像已带 Chromium）

```bash
docker build -f Dockerfile.e2e -t smart-edit-e2e .
docker run --rm --ipc=host -v "$PWD:/workspace" \
  -v smart-edit-web-node:/workspace/web/node_modules \
  -w /workspace/web smart-edit-e2e npx playwright test
```

### 1.4 本机开发（改代码时用）

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"     # POSIX: .venv/bin/python
npm --prefix web ci
./scripts/dev.sh                                        # 后端 :8000 + 前端 :5173
```

`scripts/dev.sh` 默认使用 fixture 抽取：

```text
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json
```

因此不配真实模型也能把 `parse → extract → normalize → audit` 跑完。`--honest` 则不配模型，
用来验证“没检查 ≠ 没问题”的诚实路径。

---

## 2. 代码地图（先看这 8 个文件）

| 文件 | 作用 |
|---|---|
| `app/state.py` | `EditState` 契约：字段、Finding、StageReport、Trail、reducer |
| `app/stages.py` | `AGENT_SPECS` / `STAGE_TARGETS` / 阶段报告 / 前置检查 |
| `app/runtime.py` | `merge_update()`、`execute_chain()`、`NODES` |
| `app/graph.py` | 主图：`ingest → parse → extract → normalize → reset → (agent2 ‖ agent3) → merge → agent4 → hitl → gate → export` |
| `app/nodes/agent2.py` | Agent 2 当前占位实现（诚实失败） |
| `app/nodes/audit.py` | Agent 4 审计节点：只写 `verification` / 自己的 findings / stage / trail |
| `app/nodes/pipeline_gate.py` | 导出闸门：六类检查，要求 `agent2` 阶段为 `done` |
| `app/api/main.py` | HTTP 控制面：创建、阶段触发、gate、disposition、图运行/恢复、事件 |

### 2.1 状态写权（联调最重要的约束）

| key | 唯一写入者 | reducer |
|---|---|---|
| `files` | ingest / API | 普通赋值 |
| `docs` | parse | 普通赋值 |
| `_candidates` | extract（normalize 用 `Overwrite([])` 清空） | 普通赋值 |
| `fields` / `extra_fields` / `business_type` | normalize | 普通赋值；**已确认字段不会被覆盖** |
| `legal` / `retrieved` | agent3 | 普通赋值 |
| `verification` | **只有 agent4** | 普通赋值 |
| `gate` | gate 命令 | 普通赋值；新审计会写 `None` |
| `findings` | agent1 / agent2 / agent3 / agent4 | `operator.add`；`reset`/`merge`/`audit` 用 `Overwrite` |
| `stages` / `trail` | 所有阶段 | 追加，`latest_stage()` 读取最后一条 |

规则：**拒绝 ≠ 空结果**。前置缺失时返回 `StageReport(status="failed", reason=...)` 和结构化拒绝，
绝不能返回 `findings=[]` 假装“检查过且没问题”。

---

## 3. Agent 1 交接

### 3.1 你负责的入口

| 入口 | 位置 | 约束 |
|---|---|---|
| `parse(files)` | `app/parsing/parse.py` | 零模型；单文件失败只进 `errors`；不产出空成功 |
| `parse_node(state)` | `app/nodes/parse.py` | 写 `docs`；`partial` / `failed` 要如实报告 |
| `extract(docs, field_keys, llm)` | `app/parsing/extract.py` | 唯一模型入口；候选不含 `confidence` 以外的私有字段 |
| `extract_node(state)` | `app/nodes/extract.py` | 只写 `_candidates`；全部文件失败必须 `failed` |
| `build_fields(candidates, docs, fields_yaml)` | `app/parsing/normalize.py` | 纯函数；三分类、跨页、业务类型、占位 |
| `normalize_node(state)` | `app/nodes/normalize.py` | 写 `fields` / `extra_fields` / `business_type`；清空 `_candidates` |

`normalize_node` 现在会保留 `confirmed` 或 `edited_by_user` 的旧字段（`document-import / 已确认字段不被导入覆盖`）。
`clear_previous_outputs(state, "normalize")` 也只清未确认字段，不要改回去。

### 3.2 不变量（测试会盯）

1. `normalize_ws` 是**全层唯一**的“是否指向同一段原文”基准：NFKC、去零宽、破折号/引号归一、空白折叠；
   **不折叠大小写、不去标点**。
2. 金额只用 `Decimal`；`NaN / Infinity / 1e999999999 / 带符号 NaN` 必须降级并记录 note，不能抛异常。
3. “约 / approximately / 左右”等模糊金额不能确定化。
4. 跨页拼接才降级；一个 span 完整落在单个 block 里不是跨页。`page` 缺失时从实际包含它的 block 回填。
5. DOCX 单元格保留段落边界；嵌套表格只遍历一次。
6. OCR 文本的 `form` 必须是 `image_ocr`；识别不到文字时是 `no_text_recognized`，不是 `no_text_layer`。
7. 全部文件解析失败：`fields` 为空、`extract` / `normalize` 都 `failed`，不写 7 个占位。
8. `blocking` 永远不由 Agent 1 决定；归一化 finding 的 `blocking=False`，由 Agent 2 的 `requirements.yaml` 决定。

### 3.3 加字段 / 改规则的检查清单

1. 在 `app/configs/fields.yaml` 加定义（类型、required、max_length、charset、date_order）。
2. 若类型是新的：同时改 `app/parsing/normalize.py::_normalize_value` 和 `app/rules/engine.py` 的解析器/coercer。
3. 加正向测试到 `tests/test_normalize.py` / `tests/test_parse_import.py`。
4. 若是已修复缺陷的回归，加到 `tests/test_spec_bugs.py`（**不要加 xfail**）。
5. 跑：

```bash
docker run --rm -v "$PWD:/workspace" smart-edit-test \
  pytest tests/test_normalize.py tests/test_parse.py tests/test_parse_import.py \
         tests/test_agent1_standalone.py tests/test_agent1_trail.py tests/test_spec_bugs.py -q
```

---

## 4. Agent 2 交接

### 4.1 当前状态：占位实现

`app/nodes/agent2.py::agent2_node` 现在**故意失败**：

```python
reason = "agent2 is not implemented in this build; refusing to fabricate findings"
return {"stages": [stage_report("agent2", status="failed", reason=reason, ...)]}
```

后果：
- 主图仍能跑，但导出闸门 `app/nodes/pipeline_gate.py::REQUIRED_STAGES` 要求 `agent2` 为 `done`，
  所以 **export / approval 必然 blocked**，直到你完成实现。
- HTTP `POST /runs/{id}/stages/agent2` 目前会返回 `409 unknown_stage`，因为 `STAGE_TARGETS` 里还没有它。
  这是有意的：注册必须显式，不能猜。

### 4.2 需要你改的 4 个位置

1. **实现节点**：替换 `app/nodes/agent2.py::agent2_node`。
   - 输入：`state["fields"]`、`state["business_type"]`，必要时读 `state["docs"]` 做原文校验。
   - 输出（partial update）：`findings`、`stages`、`trail`；不要写 `verification`。
   - Finding 必须以 `source="business"` 创建，由 `app/findings.py::materialize_findings()` 分配 `B-` id。
   - `blocking` 由 `requirements.yaml` 的规则声明，不能从 `severity` 推导。
2. **注册链式触发**：`app/runtime.py::NODES` 加 `"agent2": agent2_node`。
3. **注册独立触发**：`app/stages.py`：
   - `STAGE_TARGETS["agent2"] = AgentSpec(...)`（前置：`parse/extract/normalize`，`requires_keys=("fields",)`）
   - `AGENT_TARGETS["agent2"] = "agent2"`
4. **主图**：`app/graph.py` 已经接好 `agent2` 节点和 `reset → agent2 → merge`，通常不需要改；
   测试里可以用 `build_graph(agent2=fake_node)` 注入。

### 4.3 Agent 2 与闸门 / 重跑 / HITL 的契约

- **闸门**：`findings` 里 `blocking=true 且未处理` 会阻断；`accepted/rejected/needs_human_review`
  是处理方式，且 disposition 绑定 `snapshot_digest`，重审后旧处理不继承。
- **重跑**：`app/nodes/repair.py::FIXABLE_BY` 里 `field_key_resolvable` 只指向 `agent2`；
  你的 finding 若要可修复，检查器的 reason/checker 名称要落在这个集合里。
- **HITL**：人工改字段后 `confirmed=true`；`app/audit/bind.py` 会把 `inferred + confirmed`
  视为可用值，所以你的规则不要自己再判一次“未确认”。
- **审计**：Agent 4 的 `EVIDENCE:finding_anchor` 会检查 finding 的 `field_keys` 是否都存在；
  不要把不存在的 key 写进 finding。

### 4.4 `requirements.yaml` 建议落地方式

参考 `openspec/changes/agent-verify/design.md` 与 `REVIEW.md`。建议：

```text
app/agents/verify/requirements.yaml     # 按 business_type 分组：字段、阈值、detect 关键词、blocking
app/agents/verify/rules.py              # 纯函数：requirements -> Finding drafts
app/nodes/agent2.py                     # 适配层：读 state -> 调 rules -> materialize
```

不要在 YAML 里写“业务上未确认的阈值”占位；缺业务类型时按设计返回
`StageReport(status="failed", reason="no requirements for <business_type>")`，不要静默通过。

### 4.5 Agent 2 的验收测试

至少覆盖：

1. 已知 `business_type` → 要件齐全时 `done, produced=0`；缺要件时 `finding` 且 `blocking` 与 YAML 一致。
2. 未知 `business_type` → `failed` + 明确 reason，不产 `findings=[]`。
3. `not_found`（交了但没抽出来，不阻断）与 `missing`（没交）必须可区分。
4. 同一 finding 重跑后不会累积重复（依赖 `merge` 的去重键 `(source, rule_id, field_keys, evidence)`）。
5. 端到端：`normalize → agent2 → audit → gate` 能在 `agent2 done` 后给出 `allowed`，且
   `agent2 failed` 时导出被 `STAGE_NOT_DONE` 阻断。

命令：

```bash
docker run --rm -v "$PWD:/workspace" smart-edit-test \
  pytest tests/test_graph_flow.py tests/test_gate.py tests/test_spec_coverage.py -q
```

---

## 5. 本地构建 RAG 库（Agent 2 / Agent 3 联调都适用）

### 5.1 语料

仓库只保留：

- `data/regulatory/corpus/README.md`（目录与格式说明）
- `data/regulatory/corpus/fetch_*.py`（抓取脚本）
- `data/regulatory/config.json`（路径、切块、embedding、检索参数）

原始 `.md` / `.pdf` / eval 结果**不再入库**，在本地生成：

```bash
cd data/regulatory/corpus
python fetch_ecfr.py --title 19
python fetch_ecfr.py --title 15
python fetch_wto.py
python fetch_jp.py
python fetch_au.py
python fetch_cisg.py
```

输出结构见 `data/regulatory/corpus/README.md`。每个条文用 `## <条文标识>` 作为二级标题，
这样 chunker 能按条切块。

### 5.2 构建索引

```bash
# 1) 生成 manifest
python -m app.regulatory.index manifest --config data/regulatory/config.json

# 2) 只用 BM25（不需要 embedding 服务，最快）
python -m app.regulatory.index build --config data/regulatory/config.json --keyword-only

# 3) 混合检索（需要 config.json 的 embedding.base/model 可用）
python -m app.regulatory.index build --config data/regulatory/config.json

# 冒烟：只取前 2 个文档
python -m app.regulatory.index build --limit 2 --keyword-only

# 查看当前激活索引
python -m app.regulatory.index status
```

索引目录 `data/regulatory/index/` 已被 `.gitignore` 忽略；`current.txt` 指向当前 `.db`。
构建完成后再起后端，Agent 3 会自动打开当前索引。

### 5.3 环境变量

| 变量 | 作用 |
|---|---|
| `SMART_EDIT_RAG` | URL = 走外部 HTTP 检索；`off` = 显式禁用（`retrieval_not_configured`） |
| `SMART_EDIT_RAG_CONFIG` | 本地检索配置路径，默认 `data/regulatory/config.json` |
| `SMART_EDIT_RAG_KEYWORD_ONLY=1` | 本地检索强制 BM25，不调用 embedding |
| `SMART_EDIT_RAG_TIMEOUT` | 外部检索超时秒数 |

### 5.4 验证检索

```bash
SMART_EDIT_RAG_KEYWORD_ONLY=1 \
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
.venv/Scripts/python.exe -m uvicorn app.api.main:app --port 8000 --log-level info
```

```bash
curl -X POST localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"text":"保函金额 USD 500,000.00，适用 URDG 758。"}'
# 取 thread_id 后
curl -X POST "localhost:8000/runs/<thread_id>/stages/agent3?input_mode=raw"
```

期望：`legal`, `retrieved` 非空；若索引缺失，阶段是 `failed` 且 reason 为
`knowledge_base_empty: local index is not built ...`，不会假装“无问题”。

---

## 6. 本地跑完整 Flow

### 6.1 启动

```bash
SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json \
SMART_EDIT_RAG_KEYWORD_ONLY=1 \
./scripts/dev.sh
```

打开 `http://localhost:5173`，粘贴 `fixtures/llm/sample_document.txt`。

### 6.2 前端操作路径

1. **Import / 粘贴**：文档进入 TipTap；审计读取的是 `richToPlainText` 投影。
2. **Version history → Capture**：报告绑定当前快照；之后编辑会让报告 stale。
3. **AI assistant → Rule audit → Run spec audit**：
   - 依次触发 `normalize`（自动补 `parse/extract`）和 `audit`。
4. **Ask gate**：选 operation（`save_draft` / `submit_version` / `start_approval` /
   `formal_export` / `handoff` / `formal_mapping`）。
   - stale 报告时按钮禁用；服务端也会拒绝客户端 digest 不匹配的请求（`stale_report`）。
5. **Finding disposition**：`accepted` / `rejected` / `needs_human_review`；
   reject critical 必须写 reason；处理事件绑定审计快照。
6. **主图 / HITL / 导出**（控制面 API，前端目前未全部暴露）：

```bash
# 跑图到第一个 interrupt（通常是 hitl）
curl -X POST localhost:8000/runs/<thread_id>/run
# 恢复：edits 里只能改已有 key
curl -X POST localhost:8000/runs/<thread_id>/resume \
  -H 'content-type: application/json' \
  -d '{"edits":[{"key":"guarantee_amount","value":"500000.00"}]}'
# 只读事件 / 状态
curl localhost:8000/runs/<thread_id>/events
curl localhost:8000/runs/<thread_id>
```

### 6.3 完整 HTTP 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/runs` | JSON `{text}` 或 multipart `files`；`?autostart=true` 直接跑图 |
| POST | `/runs/{id}/stages/{stage}` | 链式阶段触发；`?template=<id>`、`?input_mode=raw|enriched` |
| POST | `/runs/{id}/gate` | 问闸门；body `{operation, candidate_digest?}` |
| POST | `/runs/{id}/findings/{fid}/disposition` | 追加处置事件 |
| POST | `/runs/{id}/run` | 跑主图到 interrupt/END |
| POST | `/runs/{id}/resume` | 恢复 HITL |
| GET | `/runs/{id}/events` | 节点/阶段/trail 时间线 |
| GET | `/runs/{id}` | 完整 envelope（files/fields/findings/stages/trail/legal/verification/gate） |

错误统一为 `{code,message,detail?}`；400/404/409/422 都走封套。

---

## 7. Agent 2 联调顺序（建议）

1. 用 fixture 抽取跑通 `parse → extract → normalize`，确认 `fields` / `business_type` 正确。
2. 用 `FakeRetriever` 或本地 RAG 跑 Agent 3，确认 `legal` / `retrieved` 有内容。
3. 实现 Agent 2 的纯函数规则 + 节点，先用测试 `build_graph(agent2=...)` 注入，避免动生产占位。
4. 注册 `STAGE_TARGETS` / `NODES` 后，跑 `POST /runs/{id}/stages/agent2`。
5. 跑完整图：确认 `agent2` 的 `StageReport` 为 `done`，`export` 不再被 `STAGE_NOT_DONE` 阻断。
6. 故意让 `requirements.yaml` 缺一个业务类型：确认是 `failed`，不是静默通过。
7. 跑 E2E：`docker run ... smart-edit-e2e npx playwright test`。

---

## 8. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `no model provider configured` | 未设 `SMART_EDIT_LLM`；诚实路径就是这样 |
| `retrieval_not_configured` | `SMART_EDIT_RAG=off` 或 mercatoria 导入失败 |
| `knowledge_base_empty: local index is not built` | 先跑 `python -m app.regulatory.index build --keyword-only` |
| `409 unknown_stage: agent2` | Agent 2 尚未在 `STAGE_TARGETS` / `AGENT_TARGETS` 注册 |
| 导出一直 `STAGE_NOT_DONE` | `agent2` 仍是占位 `failed`，或某个必需阶段 latest 不是 `done` |
| `stale_report` | 审计后被编辑；重新 audit，或确认客户端没有重放旧 digest |
| `EMPTY_SUBMISSION` | 编辑器为空；`text` 不能是空串 |
| OCR 报 `ocr_engine_missing` | 未装 Tesseract 语言包；属于预期失败，不是假成功 |
| 前端端口被占 | `./scripts/stop.sh --all`，或按 `TESTING.md` 覆盖端口 |

---

## 9. 交付边界 / 已知缺口

1. Agent 2 的内部行为（`requirements.yaml`、语义校验）仍未实现；本文只给接口与联调约束。
2. Finding 的 disposition 仍以 append-only 事件表达，`findings[]` 本身不冗余 disposition 字段。
3. 模板编辑后的 gate 失效已接到 `gate_node`；如果通过外部 HTTP 直接调用 `evaluate_gate`，仍需自行传
   `template_digest`。
4. OCR 只验证了“无文本层 / 引擎缺失”的诚实路径，未做真实扫描件质量评测。
5. RunStore 的锁覆盖单进程并发；多 worker SQLite 竞争未压测。

更细的缺陷修复记录见 `TEST_REPORT.md`；测试运行方式见 `TESTING.md`。
