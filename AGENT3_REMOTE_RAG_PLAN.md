# Agent 3 接入远程 RAG 服务 · 执行计划（harness 版）

> 计划日期：2026-11-19 ｜ **最后更新：2026-11-19（执行完毕，见 §7）**
> 范围：让 `agent3`（legal/regulatory 模块）直连 Shawn 部署的 mercatoria 公网服务，替代本机建索引
> 服务：`http://59.110.213.187:8080`（mercatoria:prod，143 部法规 / 11562 chunks，rerank 开启）
> 契约出处：`mercatoria.postman_collection.json`（27 端点实测记录）＝ 丢失的 rag-service-handoff 文档的真身

> ⚠️ **本文 §0–§6 是最初的计划，保留作为 harness 判据的历史证据；实际执行结果与修订见 §7。**
> 特别注意 **§2 Phase 4、§3 验证矩阵 P4 行、§6 交付物清单已被修订取代**：
> 8.3/8.4/8.5 最终**不用 `/v1/chat`**、8.5 实测**未达标且保持未勾**、`eval/` 最终**全提**。
> 完整结论以 `eval/report.md` 为准；指标由 `eval/run_eval.py` 生成到 `eval/l3_metrics.md`。

---

## 0. 已验证事实（动手前先钉死的基线）

| # | 事实 | 验证方式 |
|---|---|---|
| F1 | 服务在线：`/health` 免鉴权返回 `status=ready, documents=143, chunks=11562` | `curl http://59.110.213.187:8080/health`（已实测 2026-11-18） |
| F2 | 无 token 的 `POST /v1/retrieve` → `401 {"error":{"code":"unauthorized"}}` | 已实测 |
| F3 | 带 `Authorization: Bearer <token>` → `200`，返回 `chunks[]` + `corpus{documents:143}`，与 `app/regulatory/retriever.py::validate_response()` 的校验要求兼容 | 已实测 |
| F4 | 服务端同时注册 `/retrieve` 与 `/v1/retrieve`（无 v1 路由带 token 通过鉴权）→ 客户端 URL 拼接 `{base}/retrieve` 不用改 | 已实测（422 = 鉴权通过后 body 校验） |
| F5 | **缺口**：仓库的 `HttpRetriever`（`app/regulatory/retriever.py:122`）不发送任何鉴权头 → 直连必 401 | 代码事实 |
| F6 | 本机无本地索引（`index status` → `not_built`），语料 md 从未抓取 → 不接远程服务则 agent3 必然 `knowledge_base_empty` 失败 | 已实测 |
| F7 | token 由微信 resource.txt 提供，**只走环境变量、不写入任何被跟踪文件**；服务端 env 名 `MERCATORIA_API_TOKEN`，`Bearer` 与 `X-API-Key` 两种头都认 | 截图 + 实测 |

---

## 1. Harness 思维怎么落在这个任务上

四条原则，每条都对应本任务的具体动作：

| 原则 | 本任务的落法 |
|---|---|
| **先判据后改动**（red → green） | Phase 1 先写 4 个会失败的鉴权测试，再写实现；失败输出本身就是规格 |
| **外部依赖双轨隔离** | 单测 mock `urlopen`（沿用 `tests/test_regulatory_http.py` 现有模式，进程内、离线、确定性）；真实服务只进**显式开关的 live 冒烟**（沿用 `tests/test_live_llm_optional.py` 的 `skipif` 模式，默认 skip、不进回归） |
| **负路径与正路径同权重** | 401 / 断连 / 超时 / `off` 必须被断言为**结构化失败**（`StageReport(failed, reason=…)`），绝不允许 401 被吞成"空结果"——这是项目最高原则"没检查 ≠ 没问题"的直接应用 |
| **基线锁定 + 全量对照** | 动代码前先跑绿现有测试（Phase 0），动完后跑同一批 + 全量回归，确保零行为回退（无 token 场景的行为完全不变） |

---

## 2. 分阶段执行

### Phase 0 · 基线锁定（不改任何代码）

**做**：跑现有相关测试，确认起点全绿。

```powershell
cd e:\tech\IdeaProjects\smart-edit
.\.venv\Scripts\python.exe -m pytest tests/test_regulatory_http.py tests/test_regulatory.py tests/test_regulatory_stage.py -q
```

**验证**：全部 pass（655 基线的子集）。若有红，先停下查基线，不带伤动工。

---

### Phase 1 · 客户端鉴权支持（TDD）

**改哪些文件**：

| 文件 | 改动 |
|---|---|
| `app/regulatory/retriever.py` | ① `HttpRetriever.__init__` 增加 `token: str | None = None`；② 请求头按需追加 `"Authorization": "Bearer <token>"`（token 为空则**完全不加头**，保持向后兼容）；③ `resolve_retriever()` 读新环境变量 `SMART_EDIT_RAG_TOKEN`（空/未设 = 无鉴权）并传入 |
| `tests/test_regulatory_http.py` | 新增 4 个测试（先写，先看它们红） |
| `HANDOVER.md` | 环境变量表补一行 `SMART_EDIT_RAG_TOKEN` |

**命名决策**：客户端统一用 `SMART_EDIT_RAG_*` 前缀（与现有 `SMART_EDIT_RAG` / `SMART_EDIT_RAG_TIMEOUT` / `SMART_EDIT_RAG_CONFIG` / `SMART_EDIT_RAG_KEYWORD_ONLY` 一致），不引入服务端的 `MERCATORIA_API_TOKEN` 名字（那是 Shawn 的服务器侧 env，混用会让人以为要配服务端文件）。

**先写的 4 个测试（red）**：

```text
test_http_retriever_sends_bearer_token_when_configured   # mock urlopen 捕获 request，断言 headers 含 Authorization: Bearer sk-xxx
test_http_retriever_omits_auth_header_without_token      # 不传 token 时 headers 里没有 Authorization（向后兼容）
test_http_retriever_maps_401_to_retrieval_unavailable    # urlopen 抛 HTTPError(401) → RetrievalUnavailable 且 "HTTP 401" in message
test_resolve_retriever_reads_token                       # resolve_retriever({"SMART_EDIT_RAG": url, "SMART_EDIT_RAG_TOKEN": "sk"}) 返回的 HttpRetriever 带上 token
```

**验证（green）**：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_regulatory_http.py -q          # 新 4 条 + 旧 5 条全绿
.\.venv\Scripts\python.exe -m pytest tests/test_regulatory*.py -q              # 模块内零回退
.\.venv\Scripts\python.exe -m pytest -q                                        # 全量 655+ 基线零回退
```

**对照点**：`test_http_retriever_maps_chunks_and_corpus`（现有）断言的请求体形状（queries/top_k/filters）必须原样不变——鉴权只是加头，不动 body。

---

### Phase 2 · 远程服务 live 冒烟（显式开关，不进回归）

**做**：新增 `tests/test_live_rag_optional.py`，完全照抄 `test_live_llm_optional.py` 的模式：`pytest.mark.skipif(os.environ.get("SMART_EDIT_LIVE_RAG") != "1")`。

断言**只锁契约性质**，不锁内容（内容是 Shawn 侧的，会随 rebuild 变）：

```text
1. GET /health        → 200, status=ready, documents > 0
2. POST /v1/retrieve  → 200, chunks 是非空 list, corpus.documents > 0
3. 不带 token 的 retrieve → 401（服务端鉴权仍在生效，防止某天被关掉而不自知）
```

**验证**：

```powershell
$env:SMART_EDIT_LIVE_RAG = "1"
$env:SMART_EDIT_RAG = "http://59.110.213.187:8080"
$env:SMART_EDIT_RAG_TOKEN = "<token>"
.\.venv\Scripts\python.exe -m pytest tests/test_live_rag_optional.py -q     # 3 条全过

# 不设 SMART_EDIT_LIVE_RAG 再跑一遍 → 全部 skip（默认回归不受外网影响）
```

---

### Phase 3 · 端到端：agent3 走远程服务（正路径 + 三条负路径）

**做**：起后端，用真实 HTTP 控制面触发 agent3，检查状态契约。

```powershell
# 终端 A
$env:SMART_EDIT_RAG = "http://59.110.213.187:8080"
$env:SMART_EDIT_RAG_TOKEN = "<token>"
$env:SMART_EDIT_LLM = "fixture:fixtures/llm/extract_sample.json"
.\.venv\Scripts\uvicorn.exe app.api.main:app --port 8000
```

```powershell
# 终端 B：正路径
$t = (Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs" -ContentType "application/json" -Body (@{ text = (Get-Content fixtures/llm/sample_document.txt -Raw) } | ConvertTo-Json)).thread_id
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs/$t/stages/agent3?input_mode=raw" | ConvertTo-Json -Depth 6
Invoke-RestMethod -Uri "http://127.0.0.1:8000/runs/$t" | ConvertTo-Json -Depth 6
```

**正路径判据（对照 `openspec/changes/agent-regulatory/specs/regulatory-advice/spec.md`）**：

| 断言 | 期望 |
|---|---|
| `stages` 里 `agent3` 最新一条 | `status=done`（不再是 `knowledge_base_empty`） |
| `legal.input_mode` | `"raw"` |
| `retrieved` | 非空，chunk 的 `jurisdictions` ⊆ {AU,CN,EU,INT,JP,US,WTO} |
| `legal.coverage` | 非空（`unavailable=false`） |
| `trail` | 有 `agent3` 的留痕条目 |
| findings | R- 前缀结构合规；**不得出现"未发现问题/合规"类措辞** |

**负路径判据（harness 核心：失败必须诚实且可分辨）**：

| 场景 | 操作 | 期望（三条必须互相可区分） |
|---|---|---|
| 错 token | `SMART_EDIT_RAG_TOKEN=sk-wrong` 重启后端重跑 | `agent3` stage `failed`，reason 含 `HTTP 401`；`findings` **不是**空成功 |
| 服务禁用 | `SMART_EDIT_RAG=off` | stage `failed`，reason = `retrieval_not_configured` |
| 超时/不可达 | `SMART_EDIT_RAG=http://127.0.0.1:9` 且 `SMART_EDIT_RAG_TIMEOUT=1` | stage `failed`，reason 含 `cannot reach` |

三条负路径的 reason 字符串互不相同 → 证明失败没有糊成一种，运维能定位。

---

### Phase 4 · 评测收尾（远程版，对应 agent-regulatory tasks 剩余项）

> 🚩 **本表为原始设想，已被 §7 修订**：8.3/8.4/8.5 后来全部改用 `regulatory_node()` 的真实输出，
> 不再打 `/v1/chat`；8.5 实测 0/10 未达标、owner 决定保持未勾；gold 单位用 doc_id 而非 chunk_id；
> 「eval 不入库」改为「eval 全提」。以下保留原文仅为对照。

前置说明：远程服务让本机**免做**抓语料 + 建索引；tasks 1.2/1.3（bank_policy / conventions 语料）仍需 A/B 提供内容、且要由 Shawn 加进远程 corpus 后 rebuild，不归本机流程。

| 任务 | 做法 | 验证 |
|---|---|---|
| 2.4 自测 20 题 | 脚本打远程 `/v1/retrieve`，20 个问题 × top-5 落盘 | 人工核对命中率，记入 `eval/notes-20q.md` |
| 8.1 gold | `eval/gold_retrieval.json`：20 题 + 每题应命中 chunk_id | 用 `/v1/corpus/documents` 反查 chunk 存在性，防标错 |
| 8.2 指标 | 小脚本算 Recall@5 / MRR | 输出 `eval/report.md`，数字可复算 |
| 8.3–8.4 | `/v1/chat` 抽 50 条 citations 人工判 supported/partial/unsupported | `eval/citations_50.csv` + 支持率公式落 report |
| 8.5 拒答 | 10 个超纲问题（语料无此话题） | `refusal_rate ≥ 0.9`（answer_status=unsupported/insufficient 计为拒答） |
| 8.6 声明 | report 固定段落 | 声明：无本地 rerank 对照、cite_check 只做实体覆盖、远程语料由第三方维护 |
| 9.5 重建闭环 | `POST /v1/admin/rebuild` → `GET /v1/jobs/{job_id}` → `/health` 版本变化 | job `running→done`、index.version 变化、同问题检索结果随之变化；注意 `409 management_busy` 与 `/v1/admin/activate/{gen}` 可回滚 |

**注意（原文，已修订）**：原计划写「`eval/` 目录不入库（沿 HANDOVER 约定）」——**实际按 owner 决定 `eval/` 全提**，理由是 `eval-benchmark/spec.md:214` 要求 gold 入库、`:208` 要求 report.md 交付时附上，且内容均为脱敏公开法规数据。所有评测脚本放在 `scripts/`，token 一律读环境变量（这条未变）。

---

## 3. 验证矩阵总表

| 阶段 | 命令 | 期望 | 性质 |
|---|---|---|---|
| P0 | `pytest tests/test_regulatory_http.py … -q` | 全绿 | 回归 |
| P1-red | `pytest tests/test_regulatory_http.py -q` | 新 4 条失败 | 判据先行 |
| P1-green | `pytest -q` | 全绿，655 基线零回退 | 回归 |
| P2 | `SMART_EDIT_LIVE_RAG=1 pytest tests/test_live_rag_optional.py -q` | 3 条过；不设开关则 skip | 显式冒烟 |
| P3 正 | `POST /runs/{tid}/stages/agent3?input_mode=raw` | stage done + legal/retrieved 非空 | 端到端 |
| P3 负 ×3 | 错 token / off / 不可达 | 三种**可区分**的 failed reason | 诚实性 |
| P4 | 评测脚本 + report | Recall@5/MRR/支持率/拒答率可复算 | 评测 |

---

## 4. 明确不做（边界）

1. 不改主图 / `STAGE_TARGETS` / `NODES`（agent3 早已接线完成）
2. token 不写进任何被 git 跟踪的文件（只走环境变量 / 本地不提交的 `.env`）
3. 不动 `mercatoria/`（那是服务端旧版代码，线上是 Shawn 的新镜像；仓库副本只读参考）
4. 远程冒烟不进默认回归（CI 永不依赖外网）
5. 不给 `agent2` / 闸门做任何顺手改动（那是另一个 change 的边界）

---

## 5. 风险与回退

| 风险 | 缓解 |
|---|---|
| token 泄漏 | 仅环境变量传递；测试里的 token 是假值；真实 token 只在运行时注入 |
| 服务漂移（契约变化） | P2 live 冒烟 3 条断言 + Postman collection 作为冻结契约参照 |
| 服务不可用 | `SMART_EDIT_RAG` 不设 → 自动回落本地 `InProcessRetriever`（现有行为，零改动）；本机建索引仍是离线开发兜底 |
| token 轮换 | 只改环境变量，零代码改动（服务端截图已说明轮换只动服务端 `.env` + 重启容器） |
| 行为回退 | P0 基线 + 全量 pytest 对照；`omits_auth_header_without_token` 测试锁死无 token 场景不变 |

---

## 6. 交付物清单（已全部完成）

- [x] `app/regulatory/retriever.py`：token 支持（Bearer 头 + `SMART_EDIT_RAG_TOKEN`）
- [x] `tests/test_regulatory_http.py`：+4 测试（含 401 映射与向后兼容）
- [x] `tests/test_live_rag_optional.py`：远程冒烟 3 断言（默认 skip；后去掉硬编码 IP）
- [x] `HANDOVER.md`：环境变量表 +1 行
- [x] `scripts/`：5 个 eval 脚本（3 个正式 + 2 个标 DEPRECATED）
- [x] `eval/`：gold / CSV / 报告 / 复核包 / `run_eval.py` 一键入口 —— **全提**（口径已改）
- [x] `eval/report.md`：指标、限制声明、偏离与已知缺口
- [x] `eval/SHAWN_ISSUE.md`：远程检索中文召回问题，转告 Shawn
- [ ] ~~`eval/notes-20q.md`~~：原计划的 20 题笔记未单独产出，内容并入 `eval/retrieval_report.md`

---

## 7. 执行实录与偏差登记（2026-11-19 收口）

### 7.1 各阶段实际结果

| 阶段 | 实际结果 | 与计划差异 |
|---|---|---|
| P0 | 652 passed / 3 failed（环境性：本机无语料索引）/ 1 skip | 基线不是「全绿」，3 个失败是环境缺文件，Docker 的 655 基线是在有索引的机器上跑的 |
| P1 | 4 测试先红后绿（9/9）→ 全量 656 passed，3 个环境失败原样 | 零回退，符合计划 |
| P2 | 3 live 断言过（0.63s），默认 3 skip | 符合计划 |
| P3 | 正路径 `agent3.status=done`、5 chunks、corpus=143；负路径×3 的 reason 互异 | 符合计划 |
| P4 | 见 7.2 | **多处修订** |

### 7.2 P4 修订明细

| 任务 | 原计划 | 实际 |
|---|---|---|
| 8.1 | gold 用 `chunk_id` | 用 `doc_id` + 已核实条文标签；远程 chunk_id 是哈希、人工不可预标。独立文件 `eval/gold_retrieval.json`（按 spec §L3） |
| 8.2 | Recall@5/MRR 写 report | **0.817 / 0.817**，明细 `eval/retrieval_report.md`；数字由 `eval/run_eval.py` 复算到 `eval/l3_metrics.md` |
| 8.3/8.4 | 打 `/v1/chat` 抽 50 条 citations | **改为 `regulatory_node()` 的 `legal.claims`**（chat 不在 agent3 路径上）。双口径：`引用可定位率 1.000`（50/50）｜`主题相关率 0.12`（**豆包专家版**独立复核 6/1/43）。43 条跑题登记为检索质量缺口 |
| 8.5 | `refusal_rate ≥ 0.9` 用 answer_status | **实测 spec 判据 `coverage.unavailable` = 0/10 = 0.00**；`escalate_to_human` 10/10 但属 raw 模式恒定副产品（域内也 true），不能当证据。**owner 决定保持未勾**，见 7.3 |
| 8.6 | 声明 rerank / 实体覆盖 | 补齐 4 条（含样本量、模型判定不可完全复算） |
| 9.5 | rebuild 版本变化 | **PASS**：上传→重建 8.7s→命中；删除→重建 8.6s→消失；服务已还原。踩到并适配 `409 management_busy` |

### 7.3 已知缺口（owner 决定保持未勾）

**任务 8.5**：spec.md:155 判据与实现不匹配，实测 0/10。根因 `answer.py:122` 的
`unavailable = not retrieved` 只看「有没有返回」，而远程 BM25 对超纲文本仍返回 5 条无关 chunk。
**不是设计变更**（判据与 escalate 逻辑同日 11-07 写入、实现 11-09 一次落地），
变的是外部检索服务（本地 20 条手写语料 → 远程 143 部 BM25）。

实测输出形态：`stage=done`、`unavailable=false`、summary 写「检索到 5 条**相关**条文」、
5 条 claim 全 `supported`（问个税却返回独立保函条文）——**既不是拒绝回答，也不是编造，
而是把无关条文当相关结果照常输出**。

此前给出的修复建议「所有 claim insufficient 时置 unavailable=true」经 6 组实测**作废**
（claims 全 supported、超纲 top1 分数也是 1.0）。剩余路径均需引入 `proposal.md:21`
明确排除的语义蕴含判断，或改动 Shawn 的服务端。详见 `eval/refusal_agent3.md`。

### 7.4 复核与协作

- **豆包专家版**独立复核（`eval/for_doubao.txt` 无锚定材料）：gold 19/20 一致、
  第 15 题主动 UNDECIDED；claim 主题相关性 6/1/43；超纲 10/10 判是
- 复核交付包 `eval/REVIEW_HANDOFF.md`；服务侧问题 `eval/SHAWN_ISSUE.md`
- **不能改评测脚本迁就答案、不能改 spec 冻结判据**；产品代码可改但属新 change
- 模型名「豆包 专家版」已按 spec「数字可追溯」写进所有相关报告

### 7.5 tasks.md 状态

51 条中 **40 勾 / 11 未勾**。可勾：2.4、8.2、8.6、9.5（4 项，客观完成）；
带条件：8.1（doc_id 偏离）、8.3（需人工抽检）、8.4（勾则注明缺口）；
不勾：1.2、1.3（等 A/B 语料）、1.4（放置位置待定）、8.5（owner 决定）。

**待 owner 终裁**：第 15 题 gold 口径（收窄则 MRR 0.817→0.792）、8.4 是否勾、
约 15–30 分钟人工复核与最终签收。
