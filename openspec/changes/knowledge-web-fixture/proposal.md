# Proposal

## Why

界面上的 “Search the web for the latest” 勾选后没有产生任何联网结果。排查运行记录（`runs/assistant.db`）显示两件事：

1. 请求确实带上了 `web_search: true`，但 web 层状态是 `skipped / web_unavailable`——服务端没有装配任何联网实现（`SMART_EDIT_ASSISTANT_WEB` 默认 `off`）。
2. 即使设成 `fixture`，`bootstrap.build_services` 构造的 `FixtureWebSearch()` **没有任何页面数据**（页面只在测试里注入），所以仍然是"配了等于没配"。

结果就是：本地演示无法端到端验证"开启联网 → 得到网页证据 → 引用分区显示 Web"。本 change 只做一件事：让 fixture provider 自带可复现的数据与一条命令，把这条链路真正跑通。

## What Changes

- **fixture provider 支持从 JSON 加载页面**：`FixtureWebSearch.from_file(path)`，文件缺失/损坏/条目非法时**加载失败**，而不是静默返回空列表；页面仍需通过准入域名过滤。
- **新增配置**：`SMART_EDIT_ASSISTANT_WEB_FIXTURE=<path>`；`SMART_EDIT_ASSISTANT_WEB=fixture` 时必须同时提供该路径才装配 provider，否则 web 层保持"不可用"（如实显示，不假装可搜）。
- **内置演示数据**：`fixtures/assistant/web_pages.json`，包含 2 条准入域名页面（适合回答 URDG/索赔类问题）与 1 条含"忽略之前指令"文本的页面，用于验证网页内容被当作不可信证据。
- **一条本地验证命令**：`scripts/assistant_web_demo.py`，在不启动 HTTP 服务的情况下跑一次 session→run，打印 `outcome / retrieval / citations`；支持 `--web/--no-web` 与 `--question`。
- **文档**：`web/README.md` 与 `how_to_use.md` §8.1 加入这条命令与预期输出。

**不做**（明确留给后续）：真实 HTTP 搜索 provider、UI 的"服务端是否具备联网能力"探测与 `skipped` 提示、`out_of_scope` 问题是否允许联网作答（会改变诚实性边界，需要单独的规格变更）。

## Capabilities

### New Capabilities

- `knowledge-web-fixture`: 定义 fixture 联网层的可复现性——从 JSON 文件加载准入页面、加载失败即不可用（fail closed）、配置后必须产出可引用的 `approved_web` 证据，以及不依赖 HTTP 服务的本地验证入口。

### Modified Capabilities

<!-- 无。knowledge-retrieval-layers 的既有要求不变：本 change 只是给它的 fixture 适配器补上数据来源与验证路径。 -->

## Impact

- **后端**：`app/assistant/retrieval.py`（`FixtureWebSearch.from_file` + 校验）、`app/assistant/settings.py`（新环境变量）、`app/assistant/bootstrap.py`（按配置装配，缺路径则不装配）。
- **数据/脚本**：新增 `fixtures/assistant/web_pages.json`、`scripts/assistant_web_demo.py`。
- **测试/文档**：`tests/test_assistant_retrieval_layers.py` 增加文件加载与失败用例；`web/README.md`、`how_to_use.md` 增加一条命令。
- **风险**：fixture 文本可能被误当成真实法规——页面标题必须自带 "synthetic/demo" 字样，回答仍保留既有 `SYNTHETIC_LIMITATION`；演示脚本使用临时数据库，避免污染 `runs/assistant.db`。