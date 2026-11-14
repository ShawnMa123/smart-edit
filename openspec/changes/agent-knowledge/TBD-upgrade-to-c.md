# TBD — 从 A 升级到 C（预留计划与改善途径）

> **状态：TBD（未排期、未批准）**。本文件只记录“现在不做、但已经预留接缝”的事项，不改变 A 的范围。
> 依据：`proposal.md`、`design.md`（D1–D12）、`AI_assistance_reqirement.md` §13.3（I1–I5）、`Requirements.md` §8/§11。
> **原则：C 升级只换 Adapter、存储、执行器与数据来源；不重写外部合同、领域规则、权限判定与 Reviewer。**

## 1. 当前 A 是什么 / 不是什么

**A（本 change）实现：** Session/Run/Message/Answer/Citation/Feedback 合同；202 + 轮询；Run 状态机/取消/超时/幂等；服务端 owner 与快照绑定；SQLite repository（表镜像 PG）；合成知识源与最小发布/撤回；词法检索；确定性路由；fixture Composer + 真实代码 Reviewer；Knowledge Q&A 面板；fixture/合成语料明确标注。

**A 不实现（本文件记录）：** PostgreSQL、Worker/队列、真实身份/组织/ACL、宿主快照/附件、真实模型/embedding、向量/重排、知识导入/审核/管理端 UI、受控联网、语音/截图、导出、SSE、观测/限流、生产保留策略。

## 2. 不可动摇的接缝（升级时不得改）

1. `/assistant/*` 的 Session/Run/Message/Citation/Feedback/Error DTO 与 `202 + 轮询` 合同；
2. Run 状态机与终态竞争、幂等键、单 Session 一个活跃 Run；
3. `outcome` / `support_level` / Claim / Citation 的语义与代码 Reviewer；
4. 服务端授权、owner 隔离、撤权/撤回 redacted、跨用户 404；
5. 知识来源/版本/分块的状态、生效期、scope/ACL、独立审核与原子发布；
6. local/test 才能用 Fake；production 检测到 Fake/合成源必须失败关闭。

## 3. 升级通道总表

| ID | 现在 A | 目标 C | 预留接缝 | 迁移动作 | 验收 / 触发 |
|---|---|---|---|---|---|
| K01 | SQLite repository | PostgreSQL repository | `StorePort`；表/列/约束按规格 §7.3 | 建 PG schema/迁移；表驱动 repository 合同测试 | 同一合同测试跑 PG；业务层无 SQL |
| K02 | 进程内/后台执行器 | Worker + 队列 + 租约/fencing | `Runner` + Run 状态机 | 入队/领取/心跳/超时/恢复；替换 Runner | 重复执行只一个答案；取消/超时不覆盖终态 |
| K03 | Fake principal / 本地 snapshot | 宿主身份/组织/ACL/不可变快照 | `IdentityPort` / `AuthorizationPort` / `SnapshotPort` | 接宿主 Adapter；移除 POC snapshot 注册端点 | 跨用户 404；撤权 redacted；快照摘要一致 |
| K04 | 最小 CLI/种子 | 知识导入/独立审核/管理端 API/UI | `KnowledgeAdminPort` + 状态模型 | 接导入/审核/发布/撤回 API；加审核 UI | 自审拒绝；原子发布；撤回立即生效 |
| K05 | Fixture/确定性 Composer | 批准 ModelGateway + 结构化输出 | `ModelGateway` | 换生成器；保留 Schema/Reviewer | 伪造引用被拦；support_level 由检查计算 |
| K06 | 词法检索 | 混合向量/词法 + RRF + 重排 | `RetrieverPort` | 接 embedding/向量/重排 Adapter | Recall/引用支持率基线；score 不当置信度 |
| K07 | 轮询、最小观测 | SSE/历史/观测/限流 | API 合同 + `AuditPort` | 加 SSE/指标/限流；不改 DTO | 终端停止轮询；429/Retry-After；按 run_id 串联 |
| K08 | 联网/语音/截图明确未启用 | P1 受控联网/多模态/导出 | 独立 Adapter；不改 P0 | 评审后单独 change | 不伪造抓取时间；权限沿用 |
| K09 | 20 个合成问题 | 专家标注集 + 离线评测 | `eval/` fixtures | 建立 Recall/支持率/弃答率基线 | 专家复核；区分“未评测”与“已达标” |
| K10 | 本 change 拥有 `app/knowledge/` | `agent-regulatory` 只读消费 | 共享 repository/端口 | 法规组接只读 Adapter；不复制语料 | 两处检索同源；无重复知识库 |
| K11 | 单节点选区/已解析文档 | 多节点/附件/OCR 待确认 | `SnapshotPort` + Selection | 扩展锚点与附件引用 | `ANCHOR_MISMATCH`；OCR 提示核对原件 |
| K12 | 本地审计表 | Outbox/审计平台/保留策略 | `AuditPort` + `outbox_events` | 接审计/保留/删除策略 | 审计失败不报成功；可追踪证据版本 |
| K13 | 禁止跨用户缓存 | 受控缓存（主体/ACL/快照/发布版本） | 缓存键规范 | 加缓存层；回源校验授权 | 撤权/发布变化后不复用旧答案 |
| K14 | 单一 fake workspace | 多组织/内容级别/ACL | `AuthorizationPort` | 接组织/角色/内容分级 | 内部层不泄漏；不靠 UI 隐藏 |
| K15 | 本地运行 | 容量/可用性/成本/SLA | 观测 + 配置 | 压测、限流、预算、告警 | 达到评审门槛后才称生产 |

## 4. 高优先级通道的详细计划

### K01 PostgreSQL（最优先）

- **A 的接缝：** 所有读写经 repository；表名/列名/唯一约束已按规格 §7.3；SQLite 只是实现。
- **迁移：** 建 PG schema（同表、同约束）；把 repository 合同测试参数化跑 SQLite/PG；一次性数据迁移脚本（仅演示数据）。
- **回滚：** 保留 SQLite 实现与开关；PG 不可用时回到 local/test，不改变 API。
- **验收：** 同一组合同测试在 PG 上通过；事务/并发（单活跃 Run、幂等、终态竞争）通过；业务层没有 SQL。

### K02 Worker / 异步

- **A 的接缝：** Run 状态机、`Runner`、deadline、取消、CAS 已实现；进程内执行只是 Runner 的一种。
- **迁移：** 加任务表/队列（P0 可 `FOR UPDATE SKIP LOCKED`）、租约与 fencing token、启动恢复、重试上限；替换 Runner。
- **验收：** 双 Worker 不重复助手消息；取消/超时与发布竞争只有一个终态；重试不延长总 deadline。

### K03 真实身份 / 快照

- **A 的接缝：** `IdentityPort` / `AuthorizationPort` / `SnapshotPort`；owner 检查在服务端；POC snapshot 注册端点独立。
- **迁移：** 接宿主 principal/组织/角色/授权版本；用宿主不可变快照/附件替换本地注册表；移除 POC 端点或仅在 local 开启。
- **验收：** 跨用户/跨组织 404；撤权后历史 redacted；快照摘要由宿主生成，助手不自行重算。

### K04 知识导入 / 审核 / 管理端

- **A 的接缝：** 状态模型、`submitted_by/reviewed_by`、原子发布指针、`KnowledgeAdminPort`；CLI 只是最小入口。
- **迁移：** 文件上传/解析/分块/暂存索引；独立审核 API/UI；发布/替代/撤回；审核与发布事务化。
- **验收：** 提交人不能自审；未完成版本不可召回；撤回立即影响检索/引用；部分失败不发布。

### K05 真实模型

- **A 的接缝：** `ModelGateway` 只输出结构化 Answer；Reviewer/权限/发布不依赖模型实现。
- **迁移：** 接批准 Provider；输出 Schema 校验；记录模型/提示词/用量版本；禁止任意工具/URL/无限循环。
- **验收：** 伪造引用/无依据 Claim 仍被 Reviewer 拦截；失败有明确错误，不降级为“知识不足”。

### K06 混合检索

- **A 的接缝：** `RetrieverPort`；检索前已做 published/ACL/生效期过滤。
- **迁移：** 接 embedding/向量库/重排；RRF 合并；保留词法兜底；控制上下文预算。
- **验收：** Recall@K/引用支持率/弃答率基线；模型/检索分数不展示为置信度；中文/英文评测集。

## 5. 建议升级顺序

1. **K01 PostgreSQL**：先把 repository 合同测试跑在 PG 上，锁住数据层。
2. **K02 Worker**：用 PG 任务表/租约替换进程内 Runner；状态机不动。
3. **K03 身份/快照**：多用户/外部试点前必须完成；否则不要开放。
4. **K04 知识导入/审核**：接真实知识源与独立审核；与 K10 一起做。
5. **K05/K06 + K09**：批准模型与混合检索；先建评测基线，再接真实用户问题。
6. **K07 观测/限流**：并发与 SLA 前完成；SSE 可选。
7. **K11/K12/K13/K14**：附件/OCR、保留/审计、缓存、多租户按试点需求推进。
8. **K08 P1**：联网/语音/截图/导出，单独评审。

每一步都可以独立停下；外部 DTO、领域规则、Reviewer 与权限不变。

## 6. 触发条件（什么时候必须启动 C）

| 触发 | 必须先做的通道 |
|---|---|
| 真实外部用户、多组织、内部层内容 | K03、K14 |
| 真实法规/政策/客户知识入库 | K04、K10（含许可与审核人） |
| 并发用户、长任务、需要取消/恢复 | K02、K07 |
| 批准的真实模型/embedding | K05、K06、K09 |
| 合规保留、审计平台接入 | K12 |
| 数据量/并发超过 SQLite 单进程 | K01、K02 |
| 客户要求联网/语音/截图/导出 | K08（P1 单独 change） |

## 7. 待决策 / 负责人

| 决策 | 影响 | 建议 |
|---|---|---|
| 知识层所有权（本 change vs `agent-regulatory`） | 两套语料/索引的风险 | 本 change 拥有 `app/knowledge/`；法规组只读消费 |
| 批准模型/embedding Provider、驻留与成本 | K05/K06 能否启动 | 数据治理/技术评审后冻结 |
| 知识许可、可展示摘录长度、更新负责人 | K04 的发布与引用范围 | 知识负责人/法务；未批准来源不得发布 |
| 会话/证据/运行/反馈保留期 | K12 与合规 | 数据治理；生产前给出具体值 |
| 审核人角色与职责分离 | K04 的独立审核 | 内容管理员提交、独立审核人批准 |
| 双语语料与评测集 | K06/K09 的质量基线 | 先建受控合成集，再接真实语料 |
| SLA、限流、成本预算 | K07/K15 | 试点容量确认后冻结 |
| P1 优先级（联网/语音/导出） | K08 | 独立 change，不阻塞 P0 |

这些问题都不阻塞 A；它们阻塞的是 C 的相应通道。

## 8. 明确不做 / 反模式

- **不要**新增 `POST /assistant/ask` 或第二套 Session/Run 协议；C 的客户端合同必须从 A 开始就一致。
- **不要**把答案写死在 UI/handler，或返回固定 citation；fixture 只能是可替换的生成器。
- **不要**把知识助手塞进 `EditState`、`AGENT_IDS` 或现有 audit stage。
- **不要**让提交人自审、自动发布知识，或用用户点赞直接改知识/提示词。
- **不要**在日志/审计里保存客户正文或模型隐式思维链；不要返回对象存储地址/模型生成 URL。
- **不要**用 fixture/合成语料声称“模型已核验”“已联网”“真实法规已覆盖”。
- **不要**让 `agent-regulatory` 与本 change 各建一套知识库；读同一层。
- **不要**把检索/模型分数当成回答置信度。
- **不要**把权限隔离交给 UI；跨用户 404、撤权 redacted 必须在服务端。

## 9. C 的 Definition of Done（摘要）

- KA-01～KA-14 / KT-01～KT-21 的 P0 证据齐全；
- PostgreSQL + Worker + 真实身份/快照 + 知识导入/独立审核/撤回 + 真实模型/混合检索；
- 引用支持率/可回答覆盖率/弃答率/权限隔离达到评审门槛；
- 审计/保留/观测/限流可用；production 无 Fake/合成源；
- 外部 DTO、领域规则与 Reviewer 与 A 保持同一套，只换实现。