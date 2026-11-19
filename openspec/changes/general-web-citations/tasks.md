# Tasks

## 1. 通用通道放开域名约束

- [x] 1.1 `_run_general_web` 不再按准入域名丢弃引用；只保留"必须有可解析 http(s) 链接"这一条门槛。验证：单测一条非白名单域名的结果被保留为引用
- [x] 1.2 缺少可解析链接的结果仍被丢弃，并计入不可引用集合。验证：单测一条无链接结果被丢弃且答案结论为证据不足
- [x] 1.3 把不可引用结果的来源域名写进审计（`hosts` 列表），不再只记数量。验证：单测断言审计载荷包含域名
- [x] 1.4 `approved_web` 通道的准入过滤保持不变。验证：既有的 `domain_not_allowed` 丢弃测试仍通过

## 2. 判据与文案

- [x] 2.1 `apply_general_web_policy` 的判据改为"是否有带链接的引用"，参数同步改名。验证：单测覆盖"有链接引用 → 保留结论"与"无链接引用 → 证据不足"
- [x] 2.2 说明文案改为"未生成引用"，不再归因准入域名。验证：单测断言文案不含 "approved domain"

## 3. 测试与文档

- [x] 3.1 改写 `tests/test_assistant_general_web.py` 两条依赖旧语义的断言。验证：该文件全绿
- [x] 3.2 新增用例：非白名单域名保留但标未核验；支持等级不为强支持。验证：断言 limitations 与 support_level
- [x] 3.3 更新 `web/README.md` 与根 `README.md`：区分 `approved_web`（准入域名）与 `general_web`（未核验、不设域名门槛）。验证：文档与实现一致

## 4. 集成验收

- [x] 4.1 手工验证（**修正预期**）：`What does escrow mean in trade finance?` 走通用联网，保留 3 条非白名单引用（ICBC / Merriam-Webster / 外贸日报）并标注未核验、`support=qualified`；`guarantee 是什么` 因法规 `low_confidence` 回落本地合成语料作答（`support=strong`，不再出网）。验证：记录两次运行的 layers、citations 与 support_level
- [x] 4.2 全量回归：`pytest`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate general-web-citations --strict` 全部通过。验证：四条命令输出

## Workflow follow-up

- `knowledge-general-web` 中"准入域名在结果返回后过滤"需在该 change 归档时改为"仅适用于 `approved_web`"。
- 归档顺序建议：先归档 `knowledge-simple-ask`，再归档本 change。