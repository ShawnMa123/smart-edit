# Tasks

## 1. 撰写网关迁移到 Responses API

- [x] 1.1 在 `app/assistant/gateway.py` 把撰写请求改为 `POST {base}/responses`（`input[]`、`stream: false`、无 `tools`），并实现 `output_text` / `output[].content[].output_text` 两种解析路径；验证：`tests/test_assistant_gateway.py` 用 `httpx.MockTransport` 覆盖两种响应形状。
- [x] 1.2 保留并加强校验：JSON 解析失败、字段缺失、citation 不在证据包内 → `MODEL_OUTPUT_INVALID`；超时/非 200 的错误码不变；验证：既有网关测试全绿并新增 Responses 形状用例。
- [x] 1.3 确认撰写请求体不含 `tools`/`tool_choice`，且只含问题与证据包；验证：新增断言读取请求体字段白名单。

## 2. 契约扩展：general_web 与开关

- [x] 2.1 `app/assistant/schemas.py` 的 `SourceType` 增加 `general_web`，`web/src/api/assistantTypes.ts` 同步；验证：`pytest tests/test_assistant_contracts.py` 与 `npm --prefix web run typecheck` 通过。
- [x] 2.2 `app/assistant/settings.py` 增加 `general_web`（`SMART_EDIT_ASSISTANT_GENERAL_WEB`）与 `web_search_max_keyword`（默认 3、上限 5）；验证：`tests/test_assistant_settings.py` 覆盖默认值、非法值与上限截断。
- [x] 2.3 `app/assistant/egress.py` 增加 `purpose="tool_search"`：要求 `provider_approved`，并在 `general_web` 关闭时返回 `deny(tool_search_disabled)`；验证：`tests/test_egress_policy.py` 覆盖允许/未批准/通道关闭三种结果。

## 3. 路由与通用联网执行

- [x] 3.1 `service.execute_run` 增加路由：`handoff_target` 非空 → 转交；`out_of_scope` + 用户开启 + `settings.general_web` → 通用通道；其余保持现状；验证：新增服务层用例断言三种路由各自走到预期分支（含“改写请求仍转交”）。
- [x] 3.2 实现通用联网调用：单个 `web_search` 工具、`max_keyword` 取配置值、只发闸门后的查询、一次运行只调用一次；验证：`httpx.MockTransport` 断言请求体 `tools` 只含该工具且关键字不超过上限。
- [x] 3.3 解析联网结果：annotation → `general_web` citation（`url/title/retrieved_at/annotation`），按准入域名过滤并记录 `dropped`；验证：新增用例覆盖命中、越界丢弃、全部丢弃三种情况。

## 4. 等级、标注与复核

- [x] 4.1 通用答案强制追加“未核验第三方内容”limitation，`support_level` 封顶 `qualified`；无准入引用时降为 `insufficient` 并说明；验证：新增单测覆盖三种组合。
- [x] 4.2 通用答案走精简复核（citation ID 存在、claim 引用有效），不执行“摘录⊆全文”；验证：新增用例断言通用路径跳过全文校验、in-scope 路径行为不变。
- [x] 4.3 规则类结论保护：通用通道的证据不得支撑规则版本/生效日/适用范围；验证：新增用例断言此类问题即使开启联网也不走通用通道或降级为 `unable_to_assess`。

## 5. 前端与文档

- [x] 5.1 `KnowledgePanel` 增加 `General web (n)` 引用分区、未核验提示与开关文案（On/Off 两种说明）；验证：`KnowledgePanel.test.tsx` 新增用例覆盖分区、提示与文案。
- [x] 5.2 e2e：开启联网后对范围外问题断言出现 `General web` 分区与未核验提示（使用 mock provider/fixture 数据），并断言未开启时不出现；验证：`web/e2e/knowledge.spec.ts` 在 desktop 项目通过。
- [x] 5.3 更新 `web/README.md` 与 `how_to_use.md`：Responses 端点、`GENERAL_WEB`、`WEB_SEARCH_MAX_KEYWORD`、通用答案的标注与回滚方式；验证：文档可 grep 到这些变量，命令与环境变量一致。

## 6. 集成验证

- [x] 6.1 运行 `pytest` 与 `npm --prefix web run verify`，确认无回归；验证：两条命令以 0 退出。
- [ ] 6.2 用真实（轮换后的）Ark key 做一次人工验证：in-scope 问题仍走规则语料；范围外问题在开启 `GENERAL_WEB` 后返回带 URL 的通用答案，且标注未核验；验证：记录两次调用的请求体差异（一次无 tools、一次只有 web_search）。

## Workflow follow-up

- 归档时把本 change 的 `doubao-responses-gateway` 与未归档的 `assistant-model-gateway` 合并，删除 chat/completions 段。
- 真实搜索 provider（非豆包自带）与流式输出仍不在范围内，后续单独评估。