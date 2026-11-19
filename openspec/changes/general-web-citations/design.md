# Design

## Context

- 通用联网通道的引用过滤在 `service._run_general_web`：逐条取 `citation.locator.url` 的主机名，用 `_domain_allowed(host, allowed_domains)` 判断，不通过就 `dropped += 1` 并跳过。
- 之后 `pipeline.apply_general_web_policy(answer, has_approved_citation=bool(kept), ...)` 在"没有准入引用"时强制 `outcome=insufficient_evidence`、清空 claims 与 citations，并附加 `GENERAL_WEB_NO_SOURCE_*` 说明。
- 准入清单来自知识配置（`knowledge.sample.json` 的 `egress.allowed_domains`），当前是 5 个官方站点。
- `approved_web` 通道（`service._run_web` + `_search_decision`）**也**用同一清单，但那条通道的语义确实是"受控来源"，必须保留过滤。
- 实测：`guarantee 是什么` / `What does escrow mean?` 在通用通道返回 3 条词典类结果，全部因域名被丢弃，最终答案为空。

## Goals / Non-Goals

**Goals:**

- 通用通道的"术语解释"类问题能给出带链接、明确标注未核验的回答。
- `approved_web` 的准入过滤一字不改。
- 不可引用的结果仍然挡住，并把域名记进审计（可运维）。

**Non-Goals:**

- 不改联网开关、默认值、层级封顶（联网证据永远不能升为 `strong`）。
- 不为联网结果引入新的排序/去重策略。
- 不改 `approved_web` 的准入清单内容。

## Decisions

### D1 · 只放开 `general_web`，`approved_web` 保持严格

两条通道的信任模型不同：`approved_web` 是"我们认可的来源"，`general_web` 是"模型自己搜到的公开结果 + 未核验标签"。用同一份白名单同时约束两者，会让后者永远无法引用任何通用资料。

- 备选：扩充 `allowed_domains` —— 否决：对"术语解释"没有稳定集合，下次换词又撞墙。
- 备选：两条通道都放开 —— 否决：`approved_web` 的准入语义是既有契约，且它承载"半官方"预期。

### D2 · 引用条件从"域名合规"改为"链接可解析"

保留一条硬门槛：`locator.url` 必须是 `http(s)` 且能解析出主机名。没有链接的结果不可引用——引用必须能被读者点开核对。

### D3 · 判据与文案一起改

`apply_general_web_policy` 的参数从 `has_approved_citation` 改为 `has_url_citation`，说明文案从"没有落在准入域名内"改为"没有生成可引用来源"。否则代码放开了、文案还在怪域名，用户会以为策略没生效。

### D4 · 审计记域名而不是计数

`web_evidence_dropped` 载荷改为 `{"hosts": [...]}`。现在只记 `{"dropped": 3}`，导致无法判断"该扩充白名单还是该放开策略"——这次就是靠人工复现才看清。

## Risks / Trade-offs

- [引用来自任意公开站点，权威性下降] → 未核验声明强制存在；支持等级封顶 `qualified`；引用必须可点开核对；审计保留域名。
- [与 `knowledge-general-web` 既有要求冲突] → 本 change 声明取代"准入域名在结果返回后过滤"对 `general_web` 的适用范围；该要求今后只约束 `approved_web`（见 Open Questions）。
- [测试大量依赖旧语义] → 只有 `tests/test_assistant_general_web.py` 的两条断言需要改写；`approved_web` 的丢弃测试保持不变，正好验证两条通道没有被混为一谈。

## Migration Plan

1. 先改 `service._run_general_web`（去过滤、改审计），此时旧测试会红——用它们确认改动范围。
2. 再改 `pipeline.apply_general_web_policy` 的判据与文案。
3. 更新/新增测试，跑全量回归。
4. 回滚：把两处过滤各自加回即可；无数据迁移、无配置变更。

## Open Questions

- `knowledge-general-web` 里"准入域名在结果返回后过滤"这条要求的措辞何时改为"仅适用于 `approved_web`"（建议随该 change 归档一并处理）。
- 是否需要对通用联网引用做条数上限（当前沿用既有 `MAX_WEB_RESULTS`）。