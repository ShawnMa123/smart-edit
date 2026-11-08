# Demo record — rich text editor (`rich-text-editor`)

Evidence for tasks 6.1–6.3. Artifacts are zh per `openspec/config.yaml`; numbers are measured on this machine.

## 环境

| 项 | 值 |
|---|---|
| 编辑器 | TipTap 3.33（`@tiptap/react` / `starter-kit` / `extension-table` / `extension-underline` / `extension-find-and-replace`） |
| 后端 | `SMART_EDIT_LLM=fixture:fixtures/llm/extract_sample.json .venv/bin/uvicorn app.api.main:app --port 8010` |
| 前端 | `npm --prefix web run dev`（浏览器经 `/api` 代理到 8000） |

## 命令

```bash
# 投影（纯函数，先锁契约）
npm --prefix web run test -- src/rich/plainText.test.ts        # 11 passed
# 编辑器（格式 / 工具栏 / 表格 / 查找替换 / 回退）
npm --prefix web run test -- src/components/RichEditor.test.tsx # 11 passed
# 富结构映射（DOCX 确定性 / PDF 启发式 / 退化）
.venv/bin/python -m pytest tests/test_rich_mapping.py -q        # 10 passed
# 诚实性（格式不改变判定、OCR 值仍待确认）
.venv/bin/python -m pytest tests/test_rich_honesty.py -q        # 2 passed
# 端到端（真实 HTTP：DOCX 与真实 PDF 的富结构）
VITE_E2E=1 VITE_E2E_RICH=1 VITE_API_BASE=http://127.0.0.1:8010 \
  npm --prefix web run test -- src/e2e.rich.test.ts             # 2 passed
```

## 6.1 实测：导入后的富结构

| 输入 | `provenance` | 块数 | 标题 | 表格 | 判读 |
|---|---|---|---|---|---|
| `fixtures/imports/guarantee.docx`（含标题样式 + 2×2 表格 + 宏部件） | `deterministic` | 4 | 0 | **1** | 表格按 OOXML 还原为真表格；宏部件被忽略 |
| `t1_contract.pdf`（6 页、66 块、3994 字符） | `heuristic` | **66** | **3** | 0 | `委托代订/代办合同` 等被判为标题；表格行按 `bbox` 聚合成"一行一条 ` \| ` 文本" |

投影样例（表格行留住了表头与值的对应关系）：

```
姓名 王雪聪等 2 位 | 联系电话 办/宅 | 手机 13925131801
```

**为什么 PDF 没有真表格**：PDF 只有坐标没有表格语义，凭空造一张表等于在数据里说假话（design D5）。
升级为真 table 节点留给有更多样本后的细化（Open Questions 1）。

## 6.2 实测：审计结论不变

```
E2E stages: parse:done extract:done normalize:done audit:done
            | audit: 33/51 no_findings | gate: not-asked
```

与 `how_to_use.md` §3 记录的改造前数字**逐项一致**（51 个单元、33 项已评估、0.647、`not-asked`）。
另有 `tests/test_rich_honesty.py` 在服务端断言：给同一份 state 加上 `rich` 之后，`counts` /
`outcome` / `coverage` / `findings` 全部不变——排版进不了引擎。

## 6.3 体积与降级（诚实记录）

- `npm --prefix web run build`：**783 KB**（单个 `index-*.js`，改造前 169 KB）。TipTap 是主要增量。
  design D8 的"过大则懒加载"在这里**没有采用**：编辑器是首屏主面板，懒加载并不能减少首屏所需字节，
  只会多一次加载态。此决定与体积实测一并记录，供后续决定是否拆包。
- 编辑器启动失败时（schema 异常等）回退纯文本 textarea，并在界面写明原因（`RichEditor` 的 fallback），
  测试 `falls back to a textarea and says why when the editor cannot start` 覆盖。

## 7.1 回归数字

| 套件 | 结果 |
|---|---|
| `pytest -q` | **359 passed**（347 → +10 映射 +2 诚实性） |
| `npm --prefix web run test` | **145 passed / 11 skipped**（其中 4 个 HTTP e2e 需 `VITE_E2E*`） |
| `npm --prefix web run typecheck` | clean |
| `npm --prefix web run build` | 通过（783 KB，见上） |

## 7.2 纯文本用户不受影响

用与界面相同的 HTTP 路径（`POST /runs {text}` → `stages/normalize` → `stages/audit`）粘贴
`fixtures/llm/sample_document.txt`，输出与 `how_to_use.md` §3 的期望值一致（见 6.2）。前端另有
`plainTextToDocument` 的往返测试断言：纯文本经"文档 → 投影"后与原文本逐字一致，因此老用户看到的
摘要、字段与结论都不变。

## 已知边界

1. 富文档只存在浏览器（无 DB）：换机器/清缓存后仅剩投影文本；版本历史里保存了富文档（`versionStore.rich`）。
2. jsdom 无法可靠输入 ProseMirror 文本，编辑器测试用"工具栏命令"制造真实编辑；文本输入的手工验证见
   `how_to_use.md` §7。
3. `editor-shell` 的 `document-editor` delta 仍写着"plain textarea on purpose"，需要它的所有者同步
   （本 change 的 `Workflow follow-up` 已记录）。
4. PDF 标题级别是启发式（字号 ≥1.3× 正文基准），会误判；界面上标 `heuristic`，且用户可自行修改。