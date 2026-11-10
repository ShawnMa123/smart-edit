# 本地测试与调试指南

> 面向第一次跑这个仓库的人：如何装依赖、跑哪几层测试、端口冲突怎么办、失败时怎么判断是缺陷还是
> 测试坏了。规格矩阵与缺陷记录见：
>
> - `TEST_DESIGN.md`：spec → 测试覆盖矩阵、用例设计
> - `TEST_REPORT.md`：本轮执行结果、49 个缺陷的修复记录

当前范围：**Agent 1（normalize）/ Agent 3（regulatory）/ Agent 4（audit）+ 编排 + 前端**。
Agent 2（`agent-verify`）尚未完成，本指南不评价其内部行为；`agent2` 只在导出闸门的阶段名中出现。

---

## 1. 环境

| 依赖 | 版本/说明 |
|---|---|
| Python | 3.11（仓库 `.venv` 已按此创建） |
| Node | 22+；前端依赖在 `web/node_modules` |
| 浏览器 | 本机 Google Chrome；或 `npx playwright install chromium` |
| OCR（可选） | Tesseract + `chi_sim/eng` 语言包；没有时扫描件会报 `ocr_engine_missing`，不会假成功 |
| Docker | 推荐：后端测试在 `smart-edit-test` 容器内执行；本机 venv 仍可用于调试 |

Windows 与 POSIX 的 Python 路径不同，测试代码已处理：

```text
Windows: .venv\Scripts\python.exe
POSIX:   .venv/bin/python
```

Playwright 配置支持 `PYTHON` 覆盖（CI 指向镜像内解释器时用）。

安装/更新依赖（如需要）：

```bash
python -m venv .venv                 # 已有则跳过
.venv/Scripts/python.exe -m pip install -e ".[dev]"
npm --prefix web install
npx --prefix web playwright install chromium   # 或用本机 Chrome
```

---

## 2. 跑测试

### 2.1 后端全量（Docker）

```bash
docker build -f Dockerfile.test -t smart-edit-test .
docker run --rm -v "$PWD:/workspace" smart-edit-test pytest -q
```

本轮基线：

```text
654 passed, 1 skipped
```

- `1 skipped` = `tests/test_live_llm_optional.py`，只在显式开启时调用真实模型。
- 49 个曾以 strict `xfail` 固定的规格缺陷已全部修复；`tests/test_spec_bugs.py` 现在是普通回归
  测试，行为回退会直接失败。记录见 `TEST_REPORT.md`。

只跑设计/回归测试：

```bash
docker run --rm -v "$PWD:/workspace" smart-edit-test \
  pytest tests/test_spec_coverage.py tests/test_spec_bugs.py -q
```

只跑一个缺陷簇：

```bash
docker run --rm -v "$PWD:/workspace" smart-edit-test \
  pytest tests/test_spec_bugs.py -q -k "gate or export or citation"
```

本机调试仍可直接用 venv：

```bash
# Windows
.venv/Scripts/python.exe -m pytest -q
# POSIX
.venv/bin/python -m pytest -q
```

### 2.2 后端单层/单文件

```bash
# 只跑审计
.venv/Scripts/python.exe -m pytest tests/test_audit_*.py -q

# 只跑 Agent 3
.venv/Scripts/python.exe -m pytest tests/test_regulatory*.py -q

# 只跑一个节点/函数
.venv/Scripts/python.exe -m pytest tests/test_normalize.py -k "span or date" -q

# 失败即停 + 详细
.venv/Scripts/python.exe -m pytest -x -vv
```

覆盖率（可选）：

```bash
.venv/Scripts/python.exe -m pip install pytest-cov
.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing -q
```

### 2.3 前端类型 + 单元/组件

```bash
npm --prefix web run typecheck
npm --prefix web run test
```

本轮基线：`178 passed, 12 skipped`。其中 6 条是 `it.fails`（预期失败），对应
`BUG-F1/F2/F3/F4/F5/A13`；它们“通过”表示缺陷仍存在。

只跑一个文件/一条：

```bash
npm --prefix web run test -- src/components/RichEditor.test.tsx
npm --prefix web run test -- -t "stale"
```

### 2.4 浏览器 E2E

本机（需要 Chrome 或 `playwright install chromium`）：

```bash
npm --prefix web run e2e
```

容器（Playwright 镜像已带 Chromium 与 Node，`Dockerfile.e2e` 补 Python 3.11）：

```bash
docker build -f Dockerfile.e2e -t smart-edit-e2e .
docker run --rm -v "$PWD:/workspace" -v smart-edit-web-node:/workspace/web/node_modules \
  -w /workspace/web smart-edit-e2e npm ci
docker run --rm --ipc=host -v "$PWD:/workspace" \
  -v smart-edit-web-node:/workspace/web/node_modules \
  -w /workspace/web smart-edit-e2e npx playwright test
```

默认会**自动启动**四个进程：

| 进程 | 默认端口 | 作用 |
|---|---|---|
| uvicorn fixture | 8000 | `SMART_EDIT_LLM=fixture:...`，确定性 happy path |
| uvicorn no-provider | 8010 | `SMART_EDIT_LLM=''`，诚实路径 |
| vite | 5173 | 代理到 8000 |
| vite | 5174 | 代理到 8010（`VITE_PROXY_TARGET`） |

**端口被占用时**（本机 8000 常被 RAGFlow 占用）不用手写配置，直接覆盖：

```bash
SMART_EDIT_E2E_API_PORT=8300 \
SMART_EDIT_E2E_HONEST_API_PORT=8310 \
SMART_EDIT_E2E_WEB_PORT=5373 \
SMART_EDIT_E2E_HONEST_WEB_PORT=5374 \
PW_CHANNEL=chrome \
npm --prefix web run e2e
```

PowerShell：

```powershell
$env:SMART_EDIT_E2E_API_PORT="8300"
$env:SMART_EDIT_E2E_HONEST_API_PORT="8310"
$env:SMART_EDIT_E2E_WEB_PORT="5373"
$env:SMART_EDIT_E2E_HONEST_WEB_PORT="5374"
$env:PW_CHANNEL="chrome"
npm --prefix web run e2e
```

浏览器选择：

- `PW_CHANNEL=chrome`：用本机 Chrome（Windows 推荐）。
- `PW_EXECUTABLE_PATH=/path/to/chrome`：用镜像内预装浏览器。
- 都不设：用 Playwright 自带 Chromium（需要 `playwright install`）。

只跑一个 spec：

```bash
cd web
npx playwright test e2e/gate.spec.ts --project=desktop
npx playwright test e2e/rich-editor.spec.ts --headed --project=desktop
```

失败时查看：

```bash
npx playwright show-report                  # CI 下生成 html
npx playwright show-trace test-results/<...>/trace.zip
```

E2E 全部为普通断言；stale 报告下 `Ask gate` 必须禁用，编辑后重放旧 digest 必须得到
`stale_report`。

### 2.5 真实模型冒烟（可选）

只在需要验证 OpenAI-compatible 接线时跑，默认 skip：

```bash
SMART_EDIT_LIVE_LLM=1 \
SMART_EDIT_ANSWER_BASE=http://localhost:3425/v1 \
SMART_EDIT_ANSWER_MODEL=my-local-2k/deepseek-v4.1-flash-1017 \
.venv/Scripts/python.exe -m pytest tests/test_live_llm_optional.py -q
```

本轮实测：`1 passed`，`agent3` done，1 次模型调用，2 条 `supported` claim，无禁止措辞。
Provider 漂移/限流属于外部因素，不纳入 CI。

---

## 3. 常见问题

| 现象 | 原因/处理 |
|---|---|
| `bash: .venv/bin/python: No such file` | Windows 用 `.venv/Scripts/python.exe`；E2E 配置已自动识别 |
| `audit failed · EMPTY_SUBMISSION` | 编辑器为空；测试应传非空文本 |
| `no model provider configured` | 后端未设 `SMART_EDIT_LLM`；诚实路径就是这样，不是 bug |
| E2E 找不到 `[data-testid="editor-text"]` | 当前编辑器是 TipTap：`[data-testid="editor-rich"] .ProseMirror`；旧的 textarea 只在 fallback 出现 |
| E2E `Process from config.webServer ...` | 端口冲突或 Python 路径错；用第 2.4 节端口变量，或设 `PYTHON` |
| `ocr_engine_missing` | 未装 Tesseract；安装 `tesseract` + `tessdata` 语言包，或只跑不依赖 OCR 的用例 |
| 审计显示 `33 of 51` | fixture + 干净样本的正常值；不是固定契约，断言看计划/计数 |
| `test_spec_bugs.py` 失败 | 该条是已修复缺陷的回归测试；对照 `TEST_REPORT.md` 的同 ID 修复说明 |
| 浏览器告警 `unique "key" prop` | 已修复（F3）；若再次出现，检查宽屏 pane 的 key |

---

## 4. 写新测试的约定

1. **先看 spec**：`openspec/changes/<change>/specs/<capability>/spec.md`，一条 Scenario 至少一个行为断言。
2. **不要把实现细节写死**：断言 `code` / `status` / `counts` / `snapshot_digest`，不要断言整段文案。
3. **正向用例**放 `tests/test_spec_coverage.py`；**已修复缺陷的回归**放 `tests/test_spec_bugs.py`，
   写清原缺陷 ID 与期望行为。行为回退必须直接失败，不加 `xfail`。
4. 前端同理：缺陷回归写普通断言，不再用 Vitest `it.fails` / Playwright `test.fail`。
5. 涉及 Agent 2 的用例先不加；等 `agent-verify` 冻结后另起矩阵。
6. 新增/修复缺陷后同步 `TEST_REPORT.md` 的修复表与 `TEST_DESIGN.md` 的矩阵。

---

## 5. 目录导航

```text
tests/
  test_spec_coverage.py      # 46 条正向规格断言
  test_spec_bugs.py          # 49 个已修复缺陷的回归测试
  test_live_llm_optional.py  # 默认为 skip 的真实模型冒烟
web/e2e/
  audit.spec.ts              # fixture 审计 happy path
  errors.spec.ts             # 空提交 / 未实现 tab
  honesty.spec.ts            # 无 provider 的诚实路径
  gate.spec.ts               # gate 决策 + stale 时禁用 gate
  legal.spec.ts              # 无审计直接跑 Agent 3
  rich-editor.spec.ts        # TipTap 格式/表格/查找替换/审计入参
  accessibility.spec.ts      # 键盘/焦点/状态文字
  version.spec.ts            # 捕获/恢复/清空
  layout.spec.ts / narrow.spec.ts / stale.spec.ts / fillable-blank.spec.ts
```

更细的覆盖矩阵与缺陷证据见 `TEST_DESIGN.md` 与 `TEST_REPORT.md`。
