## 现状（刚实测）

| 能跑 | 结果 |
|---|---|
| 单元测试 | `.venv/bin/python -m pytest -q` → **78 passed** |
| 接缝断言 | `.venv/bin/python -m pytest fixtures/ -q` → **24 passed** |
| 进程内跑 `parse → extract → normalize` | 上面刚跑通：`[('parse','done'),('extract','done'),('normalize','done')]`，金额 `500000.00 / extracted / from: USD 500K`，6 个必填字段出 `missing` 占位，10 条 trail，`_candidates` 已清空 |

| 跑不了 | 原因 |
|---|---|
| 任何 HTTP 接口 | `app/api/` 不存在，`fastapi`/`uvicorn` 也没装进 `.venv` |
| 三栏编辑器页面 | `web/` 不存在，连 `package.json` 都没有 |
| 真实模型抽取 | 没有 provider 配置；上面我是用桩函数顶替 `llm` 的 |

**根因**：`frontend-console`（0/52 任务）和 `editor-shell`（0/31 任务）都还是**规划稿**。规划边界内我不写代码，所以现在一行界面代码都没有。

## 要跑起来：两步 apply，然后两条命令

### 第 1 步：把后端 API 做出来（`console-api`）
```bash
# 先跳到实现（建议先把它裁成 API-only，见上次讨论）
/opsx-apply frontend-console
```
完成后会出现 `app/api/main.py` 等，然后：
```bash
# 装依赖（这个 .venv 没有 pip，用 uv；fastapi/uvicorn 已在 pyproject 里声明）
~/.local/bin/uv pip install --python .venv/bin/python -e '.[dev]'

# 起服务
.venv/bin/uvicorn app.api.main:app --reload
```
自测（不依赖界面）：
```bash
curl -s -X POST localhost:8000/runs -H 'Content-Type: application/json' \
     -d '{"text":"GUARANTEE NO: BG-2026-0001\nAMOUNT: USD 500K"}' | python3 -m json.tool
# 拿到 thread_id 后
curl -s -X POST localhost:8000/runs/<thread_id>/stages/normalize | python3 -m json.tool

curl -s -X POST localhost:8000/runs/R-590d97756112/stages/normalize | python3 -m json.tool
```

### 第 2 步：把三栏界面做出来（`editor-shell`）
```bash
/opsx-apply editor-shell
```
完成后：
```bash
cd web && npm install && cd ..
SMART_EDIT_LLM=fixture:<某个 fixture 路径> .venv/bin/uvicorn app.api.main:app --reload   # 终端 A
npm --prefix web run dev                                                                # 终端 B
# 浏览器打开 http://localhost:5173

SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json .venv/bin/uvicorn app.api.main:app --reload   # terminal A
npm --prefix web run dev                                                                              # terminal B → http://localhost:5173

```

两条环境变量路径，正好演示两种结果（这是设计里特意安排的）：

| `SMART_EDIT_LLM` | 界面会看到 |
|---|---|
| `fixture:<path>` | 完整审计结果：stage 条 + 字段检查 + 计数 + 快照摘要，但顶部有「本次使用 fixture」横幅 |
| **不设** | `extract` 阶段红掉，面板写「字段检查未执行 + 原因」，**不会**诬告你的文档缺 7 个字段 |

## 建议的推进顺序

1. **我先帮你把 `frontend-console` 裁成 API-only**（删它的 UI 规格 + 任务组 5–8），避免两份 UI 计划打架；
2. `/opsx-apply frontend-console` → 得到可 curl 的 API（这一步就能开始验证 agent-normalize 的 HTTP 行为）；
3. `/opsx-apply editor-shell` → 三栏页面 + 规范审计按钮；
4. 打开 `localhost:5173` 走一遍 `editor-shell/tasks.md` 的 8.3 原型对齐清单。

## 如果你今天就想看到点东西

不用等完整 apply，有两个更快的选择：

- **A（推荐）**：只 apply 第 1 步的 API 部分（约 20 个任务），一次会话内就能 `curl` 出 `fields/stages/trail`，比界面更能证明链路通；
- **B**：我把刚才那个 `/tmp/demo_chain.py` 扩成"跑一份文档 → 生成一份 HTML/JSON 审计报告"的脚本，你能在浏览器里打开看，但它**不是产品界面**，只是数据链路演示。

要我从哪个开始？说一句"裁 frontend-console"或"直接 apply API 部分"我就动手。