# Proposal

## Why

通用联网通道（`general_web`）目前把模型检索到的每条结果都按**准入域名白名单**过滤，白名单只有 5 个官方站点（`iccwbo.org / ecb.europa.eu / bis.org / wto.org / uncitral.un.org`）。

对"术语解释"类问题，这个策略必然失效：问 `guarantee 是什么` 或 `What does escrow mean?` 时，搜索引擎返回的是词典、百科与律所科普，一条都不在名单内 → 全部丢弃 → 模型写好的解释也被连带清空 → 用户只看到 `insufficient_evidence` 和四条限制说明。实测复现：

```
route=general_web  layers=[('web','ok','general_web')]
citations=[]       audit: web_evidence_dropped {"dropped": 3}
limitations: "None of the web results came from an approved domain, so no citation was produced."
```

白名单本身是为**半官方来源**（`approved_web` 通道）设计的；把它套在"未核验的通用检索"上，等于用一个为相反目的写的规则去否决这个通道的存在意义。

## What Changes

- **`general_web` 通道不再按准入域名过滤引用**：模型检索到的结果只要带**可解析的 http(s) 链接**就可引用；每条引用继续强制标注未核验，答案继续受"联网证据不得升为 `strong`"的约束。
- **`approved_web` 通道保持不变**：仍然只接受准入域名，非准入结果一律丢弃（这是另一条通道的既有语义，本次不动）。
- **没有可解析链接时仍然不得产出引用**：把 `apply_general_web_policy` 的判据从"是否有准入域名引用"改为"是否有带链接的引用"，并改写对应文案（不再提"准入域名"）。
- **审计改为记录域名而非只记数量**：`web_evidence_dropped` 的载荷从 `{"dropped": 3}` 变成 `{"hosts": [...]}`，便于以后判断"该不该扩充白名单"。

**Out of scope**：不改变 `approved_web` 的准入清单；不改变联网开关与默认值；不改变"联网结论不得作为发布来源"的层级策略；不做引用去重/排序调整。

## Capabilities

### New Capabilities

- `general-web-citations`: 通用联网结果的引用条件——不受准入域名约束、必须带可解析链接、一律未核验、条数受限；同时明确 `approved_web` 仍按准入域名过滤。

### Modified Capabilities

<!-- 无：`knowledge-general-web` 仍只在未归档的 change 中，`openspec/specs/` 下没有该能力，无法写 MODIFIED delta。两者关系见 Impact 与 Open Questions。 -->

## Impact

- **后端**：`app/assistant/service.py`（`_run_general_web` 去掉域名过滤、审计记域名）、`app/assistant/pipeline.py`（`apply_general_web_policy` 判据与文案）。
- **规范**：`knowledge-general-web` 中"准入域名在结果返回后过滤"这条要求改为**只对 `approved_web` 生效**；该 change 归档时需按其 owner 流程更新。
- **测试**：`tests/test_assistant_general_web.py` 两条断言改写（不再期望"被域名丢弃"），新增"非白名单域名保留 + 标注未核验""缺少可解析链接时丢弃"两条；`approved_web` 的丢弃测试保持不变。
- **文档**：`web/README.md` 与根 `README.md` 中关于准入域名的描述需要区分两条通道。
- **风险（需要知情）**：`general_web` 的引用将来自任意公开站点；已有"未核验"标注与层级封顶，但这是把"权威性"从域名白名单交给标签与来源可核验性。