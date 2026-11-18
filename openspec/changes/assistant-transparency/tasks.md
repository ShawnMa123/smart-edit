# Tasks

## 1. 能力端点与网关标志

- [x] 1.1 在 `app/assistant/schemas.py` 定义 `Capabilities`（`model{configured,label,approved_processor}`、`layers{local,approved_web,general_web}`、`egress{policy_version,allowed_domains,loaded}`、`web{provider}`）；验证：单元测试断言字段齐全且 `extra="forbid"`。
- [x] 1.2 在 `app/api/assistant.py` 增加 `GET /assistant/capabilities`，由 `AssistantService.capabilities()` 从 settings/gateway/egress 汇总；验证：`tests/test_assistant_api.py` 新增用例断言“全未配置 → 全 false”“配置模型+通用 → general_web=true”。
- [x] 1.3 断言响应不含敏感信息：不含 `key`、`token`、`http://`、用户标识；验证：新增用例扫描响应 JSON 字符串。
- [x] 1.4 网关声明 `DoubaoGateway.supports_tool_search = True`，并把 `_general_route` 的类名判断改为读取该标志；验证：新增用例用一个声明标志的 stub 网关走通路由，删除标志后路由返回 False。

## 2. 回答的路径与联网摘要

- [x] 2.1 `Answer` 增加可选 `route`（`published|document|general_web|handoff|none`）与 `web`（`WebSummary{requested,status,reason,hint}`）；验证：旧 JSON（无这两个字段）仍可 `model_validate`，新增字段默认 `None`。
- [x] 2.2 `execute_run` 在答案定稿处写入 `route`（按 design D4 表）与 `web`（按 D5 表：off/skipped/blocked/failed/ok + reason + hint）；验证：三条服务层用例分别断言 published、general_web、handoff 的 route 与 web。
- [x] 2.3 保证 `route=general_web` 的回答引用全部为 `general_web`，`route=published` 的引用不含 `general_web`；验证：新增交叉断言用例。

## 3. 前端能力与状态

- [x] 3.1 `web/src/api/assistantTypes.ts` / `assistant.ts` 增加能力类型与 `getCapabilities()`；验证：`npm --prefix web run typecheck` 通过，API 单测覆盖请求路径与解析。
- [x] 3.2 `KnowledgePanel` 打开时读取能力：无任何外部层时开关置灰并显示原因；只有通用通道时改写开关文案；验证：新增单测覆盖三种能力形态的开关状态与文案。
- [x] 3.3 渲染 `route` 与 `web`：`skipped/blocked/failed` 均显示 notice + hint（不再只写 limitations），in-scope 且请求了联网时显示 “answered from published sources · web not needed”，缺字段的旧回答不显示；验证：新增单测各一条。

## 4. 文档与集成验证

- [x] 4.1 `web/README.md` 增加“为什么没联网”排查表（能力端点字段 → 对应开关状态与提示），`how_to_use.md` §8.1 同步；验证：两处均可 grep 到 `/assistant/capabilities` 与 `web.reason`。
- [x] 4.2 e2e：拦截 run 响应分别返回 `skipped` 与 `ok` 的 `web` 摘要，断言 notice 与来源分区；验证：`web/e2e/knowledge.spec.ts` 在 desktop 项目通过。
- [x] 4.3 运行 `pytest` 与 `npm --prefix web run verify`，确认无回归；验证：两条命令以 0 退出。

## Workflow follow-up

- W3（`SMART_EDIT_ASSISTANT_WEB_MODE` 与 `assistant_doctor.py`）与 W4（in-scope 联网）另开 change，不复用本 change 的范围。
- 归档时确认 `assistant-capabilities` 与 `assistant-answer-provenance` 的 Purpose 被正确带入主 spec。