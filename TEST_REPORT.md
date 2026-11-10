# Spec 测试执行报告与缺陷修复记录（2026-11-10）

> 基线：`c07f650` + 测试设计新增用例；本轮修复分支 `fix/agent3-agent4-poc`。
> 范围：Agent 1（normalize）/ Agent 3（regulatory）/ Agent 4（audit）+ 编排 + POC API；
> 附带修复测试设计发现的 6 个前端缺陷（F1–F5、A13）。
> Agent 2（`agent-verify`）仍未完成，未评价其内部行为；`agent2` 仅作为导出闸门的阶段名出现。

## 1. 执行结果（本地 Docker 测试容器）

| 套件 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `docker run --rm -v "$PWD:/workspace" smart-edit-test pytest -q` | **654 passed, 1 skipped** |
| 前端类型 | `npm run typecheck`（node:22 容器，仓库挂载） | **通过** |
| 前端单元/组件 | `npm run test -- --run`（同上） | **178 passed, 12 skipped** |
| 浏览器 E2E | `docker run ... smart-edit-e2e npx playwright test` | **17 passed**（desktop/honesty/narrow，无 expected fail） |

说明：

- 后端测试只在本地 Docker 容器 `smart-edit-test` 中执行，不依赖宿主 `.venv`。
  `Dockerfile.test` / `Dockerfile.e2e` 与 `.dockerignore` 已入库，镜像构建命令见 `TESTING.md`。
- `1 skipped` = `tests/test_live_llm_optional.py`（默认不调用真实模型）。
- **49 个缺陷全部修复**，`tests/test_spec_bugs.py` 已从 strict `xfail` 转为普通回归测试；
  前端 `it.fails` / E2E `test.fail` 标记已全部移除。
- 生成型 96 MB 法规索引 `data/regulatory/index/*.db` 已从 Git 移除并加入 `.gitignore`，
  不再进入后续提交。

## 2. 修复内容

### Agent 1 / shared normalization / import

| ID | 修复 |
|---|---|
| N1 | `cross_page_span` 先检查单块包含，只有真正拼接的 span 才降级 |
| N2 | `page`/`bbox` 缺失时从实际包含 span 的 block 回填 |
| N3 | “约 / approximately” 等模糊金额不再确定化，记录 `amount_approximate` |
| N4 | 业务类型关键词在共享 `normalize_ws` 文本上匹配（全角可识别） |
| N5/N6/A2 | 非有限值、溢出指数在 normalize + schema/rule coercion 两层都被拒绝，不再崩溃 |
| N7/N8 | DOCX 单元格保留段落边界；嵌套表格只遍历一次 |
| O1 | 回填计划以每个阶段的**最新**报告判断 done |
| O2 | 全部文件解析失败时 extract/normalize 直接 failed，不写占位字段 |
| I1 | OCR 得到的 PDF 文本标记为 `image_ocr`，不再伪装成 `pdf_text` |

### Agent 4 / audit / gate / export

| ID | 修复 |
|---|---|
| A1 | `inferred + confirmed=true` 绑定为 confirmed，HITL 可解除 `needs_input` |
| A3/A13 | 服务端独占 candidate digest；客户端 digest 只作为断言，不匹配返回 `stale_report`；stale 时前端禁用 gate |
| A4/A5/A6 | 审计失败清空 findings；成功重审替换 findings、清空旧 gate、ID 从 001 重新分配 |
| A7/A8 | 重复 result 报错；单个 evaluator 崩溃只把该 unit 记为 failed |
| A9 | 导出按 snapshot 幂等，重复提交返回同一版本 |
| A10 | `accepted/rejected/needs_human_review` 解除 blocking finding |
| A11 | 阻断由 `gate_type` + `method` + `target_operations` 决定，severity 单独不阻断 |
| A14/A15 | 无 `chunk_id` 的 supported claim、空 coverage 对象均不再 pass |
| A16 | `save_draft` 不受报告 stale/findings 影响 |
| A17 | disposition 绑定 `snapshot_digest`，重审复用的 finding id 不会继承旧处理 |
| API4 | actor/reason/finding_id/disposition 类型校验，非法类型返回 400 |

### Agent 3 / regulatory

| ID | 修复 |
|---|---|
| R1 | mock 筛查名单同时扫描文档正文；国家码按 token 边界匹配 |
| R2 | 结构化 finding 的 evidence 取正文片段，不再引用生成摘要 |
| R3/R4 | LLM summary 与 claim 文本去除法律定性；所有结果附带“不替代正式筛查”声明 |
| R5/R6/R7 | `cite_check` 使用共享 `normalize_ws`（不折叠大小写、不压空格）；降级 trail 记录 `after=insufficient` |
| R8 | 单条/同分候选的 `_minmax` 保留正分，不被检索层丢弃 |

### POC API / web

| ID | 修复 |
|---|---|
| API1/API3/API5 | 畸形 JSON、畸形 multipart、非字符串 `text` → 400 `INVALID_BODY`；FastAPI 422 也走统一封套 |
| API2/API2b | 同名上传使用唯一路径；相同内容重传仍有独立 `file_id`/`path` |
| F1 | 相邻 text run 投影不再插入空格；只有填充 blank 获得分隔空格 |
| F2 | Header 的 “Formatting” 改为真实动作，不再标 not implemented |
| F3 | 宽屏 pane 全部带 React key |
| F4 | 浏览器存储中的畸形版本行被过滤，不再抛错 |
| F5 | 表格工具栏补齐 above/left/header toggle |

## 3. 剩余覆盖缺口（非缺陷）

1. **模板变更 staleness 的生产链路**：gate 仍只比较文档 digest；模板 digest 参数尚未由 HTTP
   层传入。模板被编辑但报告未变时，当前只能靠重新审计发现。
2. **Finding 的 disposition state**：仍以 append-only `dispositions` 事件表达，`findings[]`
   本身不含 disposition 字段；读取时派生。
3. **Agent 2**：`requirements.yaml`、字段语义校验、`not_found`/`missing` 双判未纳入矩阵；
   `agent2` 阶段完成后需要重跑导出/审批链路。
4. **OCR 质量**：只覆盖“无文本层/引擎缺失”，未做真实扫描件识别质量评测。
5. **多进程并发**：RunStore 的每 run 锁覆盖单进程并发；未做多 worker SQLite 竞争压测。
6. **浏览器 E2E**：已在 Playwright 容器中跑完 17 条；本机 Chrome 路径未重复验证。

## 4. 复现与回归

```bash
# backend (Docker)
docker build -f Dockerfile.test -t smart-edit-test .
docker run --rm -v "$PWD:/workspace" smart-edit-test pytest -q

# one defect cluster
docker run --rm -v "$PWD:/workspace" smart-edit-test \
  pytest tests/test_spec_bugs.py -q -k "gate or export or citation"
```

修复后若行为再次退化，`tests/test_spec_bugs.py` 中的普通测试会直接失败；不再需要
`--runxfail`。
