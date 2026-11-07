# Proposal: POC 骨架与契约冻结

## Why

三人要并行开发四个 Agent，但没有共享的状态契约时，每个人会长出不同的输入输出结构，整合日全部用来改粘合层。更危险的是**语义分歧**：结构一样、理解不一样，编译能过、整合时全线报错。

同时，产品要求 `agent1/2/3` 可被前端单独触发（用户不想跑完整流程）。这一需求把"解析"从 Agent 1 私有实现变成多人共用的基础设施 —— 若各自实现，同一份文档两次扫描会得出不同结论且无法解释。

本 change 先冻结契约与共享阶段，让后三个 change 真正并行。

## What Changes

- 定义完整 `EditState` 及全部子结构作为唯一数据契约，并**标注字段语义**（结构之外还要定语义）
- 把 `parse` / `extract` / `normalize` 提为共享层，任何 Agent 通过声明前置阶段组合它们
- 建立 LangGraph 主图
- 实现 `ingest` / `reset` / `merge` / `gate` / `export` / `hitl` 确定性节点
- 实现 **`StageReport` 阶段状态**，使"检查过且无问题"与"未检查"可区分
- 实现 **操作日志 `TrailEntry`**，即"Agent 对原文的自由操作必须留痕"这一全局约束的落地载体
- 实现独立触发入口与前置条件校验：前置缺失时**拒绝执行**，而非返回空结果
- 实现受控重跑（one-shot repair）：只由可判定检查触发，携带具体失败项，有全局预算
- 三个 Agent subgraph 以占位实现接入，保证主图当天可跑通

不在本 change 内：四个 Agent 的真实逻辑、RAG、Verifier 检查器、前端。

## Capabilities

### New Capabilities

- `orchestration`：主图编排、状态契约、共享阶段、独立触发、阶段状态、操作日志、受控重跑、闸门判定、导出
- `agent-contract`：**接缝契约** —— 冻结边界、四个接缝的语义约定、前置声明、fixture 作为验收载体

> `agent-contract` 是独立 capability，而非 `orchestration` 的一部分。
> 原因：它约束的是**人与人之间**的交接，不是图内节点的行为。三位成员各自实现时不看主图，
> 但必须看这一份。混进 `orchestration` 会让它被当成"编排细节"而跳过。

### Modified Capabilities

无（首个 change）。

## Impact

- 新增 `app/state.py`、`app/graph.py`、`app/parsing/*`、`app/trail.py`、`app/stages.py`、`app/nodes/*`、`app/api/main.py`
- 新增依赖：`langgraph==1.2.*`、`langgraph-checkpoint-sqlite`、`fastapi`、`uvicorn`、`pydantic>=2`、`pymupdf`
- 后续三个 change 全部依赖本 change 的 `state.py` 与 `parsing/`，**D1 冻结后不得单方面修改**
- 风险：契约返工会拖累三人，因此本 change 的 tasks 优先于其他三个

## 关键约定（新增，需三人确认）

| 约定 | 内容 |
|---|---|
| Finding ID 命名空间 | `N-` / `B-` / `R-` 各自编号，`merge` 不重新编号，只排序去重 |
| 空结果两态 | `StageReport` 区分"检查过无问题"与"没检查"，下游不得混用 |
| 越界操作 | `summarize` / `rewrite` / `drop` 出现在日志即触发 Agent 4 fail |
| 分数地位 | `verification.score` 仅展示，MUST NOT 参与阻断或重跑判定 |
