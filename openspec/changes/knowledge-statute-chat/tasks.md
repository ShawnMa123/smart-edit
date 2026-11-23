# Tasks

## 1. chat 适配器与映射

- [x] 1.1 在 `statute.py` 增加 `/v1/chat` 调用（`answer.enabled=true`）：发送 `question`（已脱敏）、`retrieval_query`（问题 + 扩展词）、`rewrite_query=false`、`filters`、`top_k`；超时使用 `settings.chat_timeout`。验证：`httpx.MockTransport` 单测断言请求体字段与 URL
- [x] 1.2 扩展 `StatuteOutcome`（`draft / answer_status / cited_ids / coverage`），把 `references[]` 映射为证据（locator 带 `chunk_id/doc_id/article_label/jurisdiction/effective_from/to/score`）、`citations[]` 映射为 `cited_ids`。验证：单测断言每条 locator 字段与 cited 标记
- [x] 1.3 状态映射：`answered`/`partial` 且至少一条 reference 视为有文本；`unsupported`/`unavailable`/`error`/零 chunks 视为无文本；`answered` 但零引用按 `unsupported`。验证：六种状态各一条单测
- [x] 1.4 传输错误映射：401/403 → `unauthorized`、503 → `corpus_updating`、超时 → `timeout`、其它非 200 → `http_<code>`。验证：MockTransport 单测覆盖四种

## 2. 流水线切换到 chat

- [x] 2.1 `AssistantSettings` 增加 `MERCATORIA_CHAT_TIMEOUT`（默认 60s）并透传给适配器。验证：设置单测断言默认值与自定义值
- [x] 2.2 `_run_local()` 的法规腿改调 chat；`product_faq` 不再调用法规、也不再与本地合并；`document_explanation` + 选区仍不调用。验证：单测断言规则问题只调用 chat（retrieve 适配器零调用）、产品问题不调用、选区问题不调用
- [x] 2.3 法规层 `detail` 写 `answer_status`，新增日志 `retrieval chat run=… status=… answer_status=… hits=N`；出站审计载荷增加 `endpoint="chat"`。验证：单测断言日志字段与审计 payload
- [x] 2.4 `_retrieve_layers()` 的本地 worker 预算改为 `max(5, chat_timeout + 10)`，web worker 仍 8s。验证：单测用短 `chat_timeout` + 慢假适配器断言法规层 `failed/timeout` 且本地/联网仍完成

## 3. 两段式合成（chat 草稿 → 豆包结构化）

- [x] 3.1 `DoubaoGateway.compose` 接受可选 draft（经 `context`），`_compose_payload` 增加 `draft_answer`，提示词写明“可用 draft 组织语言，但只能引用给定证据 id、不得新增事实、必须保留覆盖边界”。验证：gateway 单测断言 payload 含 draft 与三条约束
- [x] 3.2 服务层把 `chat_outcome.draft` 与 `cited_ids` 放进 compose context；豆包最终答案引用证据 id。验证：录制型 gateway 单测断言收到的 draft/cited_ids，且最终 `route=statute`
- [x] 3.3 结构化失败兜底：豆包 invalid/refused/超时时，用 `EvidenceComposer` 摘录 chat 引用的 references，并追加“chat 草稿已生成但结构化失败”说明。验证：三条失败分支各一条单测，均产出引用且含说明
- [x] 3.4 剩余 deadline < 20s 时跳过润色，直接用摘录兜底。验证：把 run deadline 设为接近当前时间，断言 gateway 未被调用且答案含引用与说明

## 4. 状态、限制说明与来源标记

- [x] 4.1 `partial` 与 `coverage.notes` 写入 limitations；`unsupported/unavailable/error` 不再写成“没有相关规定”。验证：单测断言三种状态的 limitations 文案
- [x] 4.2 `_route_for()` 行为不变：含 statute 引用 → `statute`；仅本地 → `published`；联网 → `general_web`。验证：四条分支单测
- [x] 4.3 前端 `statuteNotice()` 支持 `answered/partial/unsupported`（partial 显示“依据不完整”，unsupported 显示“法规服务未给出可用答案”），不再出现“not used”。验证：`KnowledgePanel.test.tsx` 三条组件测试通过

## 5. 文档

- [x] 5.1 更新 `how_to_use.md` 8.2 与 `README.md`：法规腿改用 `/v1/chat`、`MERCATORIA_CHAT_TIMEOUT`、两次模型调用的成本、chat 生成侧不在本服务审计内、产品 FAQ 不再查法规。验证：按文档配置一次，启动日志 `statute=True`，一次规则问题能看到 chat + 豆包两次调用
- [x] 5.2 更新 `scripts/mercatoria_chat.py` 的 docstring：说明它直连 `/v1/chat`，与助手的「chat 草稿 + 豆包结构化」链路区别。验证：`--help` 输出包含该说明

## 6. 验收

- [x] 6.1 真实服务：`独立保函的定义是什么` → `answered`、`route=statute`、引用来自 chat 的 chunk、日志含 `retrieval chat … answer_status=answered`、审计 `endpoint="chat"`。验证：一次 run 的 JSON 记录
- [x] 6.2 真实服务：`guarantee` + `jurisdictions=["WTO"]` → `partial`，limitations 含“依据不完整”，引用仍可用。验证：一次 run 的 JSON 记录
- [x] 6.3 降级验收：①chat `unsupported`/零结果 → 自动联网；②chat 超时 → `failed/timeout` + 回退；③豆包失败 → 摘录兜底 + 说明。验证：三条记录写入 `acceptance-<date>.json`
- [x] 6.4 产品 FAQ 不调用 chat：`提交版本后编辑锁会释放吗？` → 无 chat 调用、引用来自本地。验证：日志与运行记录

## 7. 回归

- [x] 7.1 `.venv/bin/python -m pytest tests -q`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate knowledge-statute-chat --strict` 全绿。验证：四条命令通过

## 8. 修正：references 即证据（实现后）

- [x] 8.1 `judge_chat()` 对 `unsupported/unavailable/error` 仍把 references 映射为证据（draft 仅 `answered/partial`）；零 references 才算无证据。验证：adapter 单测（非 answered 状态保留证据 + 零引用无证据）
- [x] 8.2 服务层：有 references 时不触发联网；豆包收到 evidence-only（无 draft）；豆包失败用“条文证据已返回但结构化失败”摘录兜底。验证：服务单测三条
- [x] 8.3 验收：`在wto里，什么是guarantee`（chat `unavailable` + 5 references）→ `route=statute`、不联网、说明“服务自身答案不可用”；零 references 用例仍自动联网。验证：`case_7` + `case_3`

## Workflow follow-up

- 评审通过后归档本 change；归档前确认与 `ragflow-first-web-fallback` 的产品合并规则冲突已在其说明/归档备注中记录。
- 归档后确认主 spec 含 `knowledge-statute-chat` 的 Purpose 与全部 scenarios。