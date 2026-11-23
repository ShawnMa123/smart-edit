# Tasks

## 1. 配置与装配

- [ ] 1.1 在 `app/assistant/settings.py` 增加 `web_fixture`（`SMART_EDIT_ASSISTANT_WEB_FIXTURE`）并在 `AssistantSettings.from_env` 中解析；验证：`tests/test_assistant_settings.py` 新增用例覆盖"有路径/无路径"两种解析结果。
- [ ] 1.2 在 `app/assistant/bootstrap.py` 按 design D3 装配：`WEB=fixture` 且有路径时构造 `FixtureWebSearch.from_file(path)`，无路径时保持 `web=None`；验证：新增 `build_services` 用例断言两种配置下的 `services.web` 类型。

## 2. fixture provider 加载页面

- [ ] 2.1 在 `app/assistant/retrieval.py` 实现 `FixtureWebSearch.from_file(path)`：读取 `{retrieved_at, pages[]}`，逐条校验 `url/title/text`，失败时抛 `ValueError` 并指出下标；验证：新增单测覆盖有效文件、缺字段、非法 JSON、文件不存在四种情况。
- [ ] 2.2 确认加载不绕过准入域名：用 `web_candidates` 对加载结果过滤，不匹配的页面进入 `dropped`；验证：单测断言 `dropped` 命中与 `candidates` 为空。
- [ ] 2.3 新增 `fixtures/assistant/web_pages.json`（3 条，含 1 条注入文本页面，标题带 `Synthetic demo —`）；验证：`FixtureWebSearch.from_file` 能加载该文件且条目数为 3。

## 3. 本地验证入口

- [ ] 3.1 新增 `scripts/assistant_web_demo.py`：进程内构建 services、创建会话与运行、执行并打印 `outcome / support_level / processor / retrieval / citations`，支持 `--web/--no-web`、`--question`、`--db`，默认临时数据库；验证：命令在默认参数下退出码 0，输出包含 `retrieval` 与 `citations` 两个键。
- [ ] 3.2 让脚本在"开启了联网但没有 `approved_web` 引用"时打印 `dropped` 原因与排查提示（域名不一致/策略未加载）；验证：把 `WEB_FIXTURE` 指向空页面文件时脚本给出该提示。

## 4. 文档

- [ ] 4.1 `web/README.md` 的 "Web search, local RAG and outbound screening" 小节补充：`SMART_EDIT_ASSISTANT_WEB_FIXTURE`、演示命令与预期输出；验证：README 中可 grep 到 `assistant_web_demo.py` 与 `WEB_FIXTURE`。
- [ ] 4.2 `how_to_use.md` §8.1 同步一条命令与"不配置就不会联网"的说明；验证：文档内命令可复制运行，且与环境变量名一致。

## 5. 集成验证

- [ ] 5.1 运行 `pytest` 与 `npm --prefix web run verify`，确认既有测试无回归；验证：两条命令均以 0 退出。
- [ ] 5.2 实跑演示命令两条路径：`--no-web`（本地语料，无 `approved_web`）与 `--web`（出现 `approved_web` 引用、`retrieval.web.status=ok`）；验证：两次输出的关键字段符合预期。

## Workflow follow-up

- 归档前确认 `knowledge-assistant-web-rag` 已归档或顺序明确，避免 `knowledge-retrieval-layers` 相关 spec 顺序混乱。
- 后续单独讨论：前端对 `skipped` 的提示与能力探测、`out_of_scope` 是否允许联网作答。