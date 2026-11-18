# Design

## Context

`bootstrap.build_services` 在 `SMART_EDIT_ASSISTANT_WEB=fixture` 时装配 `FixtureWebSearch()`，但不传任何页面，于是该层永远返回空结果；测试则通过构造函数直接注入 `WebPage`，所以测试绿而演示空。`SMART_EDIT_ASSISTANT_WEB=http` 才是真正的外部 provider，但本地演示不方便立即具备。本设计只补 fixture 的数据来源与验证路径，不改动检索、闸门与合成策略。参见 `proposal.md` 的 Why。

## Goals / Non-Goals

**Goals:**

- 让 `SMART_EDIT_ASSISTANT_WEB=fixture` 在"提供页面文件"时真的返回页面，并在回答中产生 `approved_web` 引用。
- 让"配置缺失/损坏"仍然 fail closed（不可用），不产生"搜了但没结果"的假象。
- 提供一条不启动 HTTP 的命令复现整条链路。

**Non-Goals:**

- 真实搜索 provider 的选型与对接。
- 前端对 `skipped` 的提示与能力探测（另一个 change）。
- `out_of_scope` 问题是否允许联网作答（规格变更，另一个 change）。

## Decisions

### D1 文件格式：一个顶层对象 + 页面数组

```json
{
  "retrieved_at": "2026-11-16T00:00:00Z",
  "pages": [
    {"url": "https://iccwbo.org/...", "title": "Synthetic demo — ...", "text": "...", "rank": 1, "published_at": "2026-05-01"}
  ]
}
```

- `retrieved_at` 是整批抓取时间，进入每条引用的 `locator.retrieved_at` 与 `source_version`。
- `rank` 缺省按数组顺序；`published_at` 可选，仅用于展示。
- 正文上限沿用 `MAX_SOURCE_TEXT`（8000 字符）。

### D2 加载即校验，失败即启动失败

`FixtureWebSearch.from_file(path)` 在构造时读取并校验：

- 文件不存在 / 非法 JSON / 顶层不是对象 / `pages` 不是数组 → `ValueError`（启动失败）。
- 任一条目缺少 `url`、`title` 或 `text`，或 `url` 不含主机 → `ValueError`，并在消息里指出下标。
- 不在加载阶段做域名过滤：域名准入仍由 `web_candidates` 在检索后按 `egress.allowed_domains` 过滤，保持"加载 ≠ 授权"的边界。

### D3 bootstrap 只在路径存在时装配

`AssistantSettings` 增加 `web_fixture: str | None`（`SMART_EDIT_ASSISTANT_WEB_FIXTURE`）。装配规则：

```
WEB=fixture + WEB_FIXTURE=<path>  -> FixtureWebSearch.from_file(path)
WEB=fixture 无 path               -> web=None（运行显示 web_unavailable）
WEB=http + endpoint               -> HttpWebSearch(...)
WEB=off                           -> web=None
```

不做"文件缺失就自动改成 off"的兜底：显式配置错误必须报出来。

### D4 演示脚本走进程内管线

`scripts/assistant_web_demo.py` 直接构造 `build_services` + `AssistantService`，调用 `create_session` / `create_run` / `execute_run`，然后打印：

```json
{"outcome": "...", "support_level": "...", "processor": "fixture",
 "retrieval": [...], "citations": [{"source_type":"approved_web","title":"...","locator":{...}}]}
```

- 默认使用临时目录里的 SQLite，避免污染 `runs/assistant.db`。
- `--web/--no-web` 对应 `RunCreate.web_search`；`--question` 覆盖默认问题。
- 与 HTTP 路径共用同一 service，所以它验证的是真实管线，不是另一套模拟。

### D5 fixture 内容与标注

`fixtures/assistant/web_pages.json` 提供 3 条页面，全部位于 `app/configs/egress.yaml` 的准入域名（`iccwbo.org`）：

1. 索赔审核时限（可支撑“claims examination”类问题）。
2. URDG 758 背景说明（与本地语料互补，不产生"规则版本"结论）。
3. 含 “ignore previous instructions” 文本的页面，用于演示网页内容被当作不可信证据。

标题统一以 `Synthetic demo —` 开头，避免被误认为真实监管原文；回答仍带既有 `SYNTHETIC_LIMITATION`。

### D6 文档

`web/README.md` 的 “Web search, local RAG and outbound screening” 与 `how_to_use.md` §8.1 各加一条命令与预期输出，说明"不开命令就不会有任何联网"。

## Risks / Trade-offs

- **fixture 被当成真实依据** → 标题带 synthetic 标注 + 既有 limitation；文档写清"仅用于演示链路"。
- **演示污染本地库** → 脚本默认临时 DB，必须显式 `--db` 才写真实库。
- **配置错误被静默忽略** → D2/D3 明确抛错或不可用，并各配一条测试。
- **准入域名与 fixture 域名不一致导致"加载成功但全被丢弃"** → 演示脚本在无 `approved_web` 引用时打印被丢弃的原因（复用 `WebSearchOutcome.dropped`），文档给出对应排查提示。

## Migration Plan

纯新增配置与脚本，默认行为不变（`WEB=off`）。回滚：移除 `SMART_EDIT_ASSISTANT_WEB_FIXTURE` 并把 `WEB` 设回 `off`。

## Open Questions

- 是否需要在 CI 里跑这条演示命令（当前只作为人工验证入口）。不影响本 change 的实现与任务拆分。