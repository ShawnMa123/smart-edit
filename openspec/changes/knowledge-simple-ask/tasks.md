# Tasks

## 1. 预设配置与护栏

- [x] 1.1 新增 `app/configs/knowledge.sample.json`：出站六条脱敏规则、准入域名、查询长度上限、法域预设与示例问题。验证：文件可被 JSON 解析，且每条规则都能编译
- [x] 1.2 配置加载器支持该 JSON，优先级为「显式路径 → knowledge.sample.json → egress.yaml → 拒绝外呼」；结构非法或缺文件时不得加载成功。验证：单测三种来源与一条"全都缺失仍拒绝"的用例
- [x] 1.3 启动时逐条编译规则：任一非法立即失败并指明是哪一条；规则条数 ≤32、单条模式 ≤512 字符，越界拒绝加载。验证：单测非法正则与两个越界用例
- [x] 1.4 规则编号豁免固定在代码中：配置里任何"豁免/白名单"字段被忽略，且脱敏误伤规则编号后仍会补回。验证：单测配置尝试豁免金额时行为不变 + 规则编号存活
- [x] 1.5 单次脱敏的时间预算：超过预算即视为校验失败并拒绝外呼，记录原因。验证：以注入时钟的单测覆盖"正常/超预算"两条路径（不引入真实慢正则用例）

## 2. 默认值与审计

- [x] 2.1 新增 `SMART_EDIT_ASSISTANT_WEB_DEFAULT`（未设置视为开启）与 `SMART_EDIT_KNOWLEDGE_CONFIG`，非法取值启动失败。验证：单测 on/off/未设置/非法四情形
- [x] 2.2 能力自检暴露 `web.default_on`、法域预设与示例问题（未配置时为 `null`，不得伪造）。验证：`curl /assistant/capabilities` 与配置一致；未配置时字段为 null 且接口 200
- [x] 2.3 运行审计记录 `web_source`（用户选择 / 部署默认）。验证：两条单测分别断言 `user` 与 `default`
- [x] 2.4 默认值设为关闭时行为回到现状。验证：一条集成测试（关闭 + 法规不可用 → 不发起联网，且回答说明联网被关闭）

## 3. 界面简化

- [x] 3.1 删除 `As of (trade date)` 与 `Rule (applicability only)` 两个输入及其载荷映射。验证：组件测试断言请求体不再出现这两个 key；typecheck 通过
- [x] 3.2 法域改为一行 chips，选项来自能力响应；未配置或未测量时整行隐藏（不显示假选项）。验证：组件测试两条（有预设时点选发出法域；无预设时该行不存在）
- [x] 3.3 联网开关初值取 `web.default_on`，用户一经切换不再被能力覆盖；面板常驻一行"可能出网"的说明。验证：组件测试两条（默认勾选 + 用户取消后保持取消；能力晚到不覆盖用户选择）
- [x] 3.4 示例问题优先来自配置预设，缺失时回退现有内置问题。验证：组件测试一条
- [x] 3.5 文案全英文并通过界面语言检查。验证：`npm --prefix web run typecheck` 与 `interface-language` e2e 通过

## 4. 文档

- [x] 4.1 更新 `web/README.md`：默认开启、可关闭、法域 chips、配置文件位置与护栏。验证：文档与实现一致，无"必须显式开启"的过时表述
- [x] 4.2 更新根 `README.md`：新增环境变量与示例配置文件的用法。验证：按文档设置一次即可复现演示路径

## 5. 集成验收

- [x] 5.1 手工验证两条主路径：默认开启且法规不可用 → 自动联网并带未核验标注；用户关闭 → 不外呼且说明被关闭。验证：记录两次运行层、引用来源与 `web_source`
- [x] 5.2 全量回归：`pytest`、`npm --prefix web run test`、`npm --prefix web run typecheck`、`openspec validate knowledge-simple-ask --strict` 全部通过。验证：四条命令输出

## Workflow follow-up

- 归档顺序建议：先归档 `knowledge-statute-retrieval` 与 `knowledge-scope-inputs`，再归档本 change。
- 本 change 取代了两处默认值条款（`knowledge-retrieval-layers`、`knowledge-general-web`）；这两个 change 归档时需按各自 owner 流程清理"默认不联网 / 必须显式开启"的表述。
- 法域 chips 的多选与用户选择的跨会话记忆留待后续 change（已列入 design 的 Open Questions）。