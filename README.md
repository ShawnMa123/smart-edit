# smart-edit · 智能编辑器 POC

把客户提交的原始材料（邮件、单据 PDF、合同）转成内部系统可识别的标准文件，并在生成过程中完成格式、业务要件、法规三层校验。

**周期**：至 2026-11-18 ｜ **团队**：3 人 ｜ **规格管理**：OpenSpec

---

## 规格（OpenSpec）

所有设计与规格集中在 `openspec/`，不再另设设计文档。契约的唯一真相源是
`openspec/changes/poc-skeleton/design.md`。

```bash
openspec list          # 查看进行中的 change
openspec status --change <name>
openspec validate --all
```

三人四职。每个 change 目录名即 owner 的责任范围，**不要从名字猜，按下表对照**：

| Change 目录 | Agent | 中文名 | Owner | 内容 |
|---|---|---|---|---|
| `poc-skeleton` | — | 地基 | **待定** | 契约冻结 + 共享层（parse/extract/normalize）+ 主图 + 阶段状态 + 操作留痕 + 独立触发 |
| `agent-normalize` | **Agent 1** | 标准化 | **A** | 原始材料 → 结构化字段 + 出处 |
| `agent-verify` | **Agent 2** | 要件校验 | **B** | 逐字段值校验 + 齐全性 + 业务参数 |
| `agent-regulatory` | **Agent 3** | 法规合规 | **C** | RAG 检索 + 两种输入模式 + 覆盖声明 |
| `agent-audit` | **Agent 4** | 审计 | **C**（框架）/ **A**（`provenance_check`） | 证据链校验 + 可信度 + 受控重跑 |

> ⚠️ **`agent-verify` 是 Agent 2（B），`agent-audit` 是 Agent 4（C）。**
> 早期版本中 Agent 4 叫 `agent-verifier`，与 `agent-verify` 易混，已改名。
> 也不用 `benchmark` —— 在线校验（运行路径上查证据链）与离线 benchmark（开发机上有真值判对错）
> 是两回事，混用会导致"用评测口径做运行时阻断"这类错误。

**执行顺序**：`poc-skeleton` 的**契约（tasks 2.x）与共享层（tasks 3.x）必须先完成并冻结**，
之后四个 Agent 的 change 才能真正并行 —— 因为独立触发要求所有 Agent 共用同一份解析实现。

---

## 架构一句话

```text
ingest → parse → extract → normalize → reset → (Agent2 要件校验 ‖ Agent3 法规合规) → merge
       → Agent4 Verifier → ⏸ 人工核对 → 闸门 → 导出
```

四人分工：① 只改形式不改事实 ｜ ② 值合不合法、材料全不全 ｜ ③ 有没有不符规则之处 ｜ ④ 证据链可不可信。

> 说明：四类能力由三人分担 —— 前三类各一人，第四类与 Agent 3 同一人。

**独立触发**：`agent1/2/3` 可被前端单独调用，系统自动补齐其声明的前置阶段；`agent4` 不可单独触发。

---

## 硬约束（不可违反）

1. **Agent 1 只改形式不改事实**，能跳回原文的字段才标 `extracted`
2. **Agent 1 / 2 用 YAML 配置，不用 RAG**（确定性要求）
3. **Agent 4 只做可判定检查**，不评业务对错；可信度用可复算比率，不用主观分数
4. **闸门不确定时默认 blocked**
5. **检索为空时输出"未覆盖"，永不输出"无问题"**
6. **"没发现问题"与"没检查"必须在数据结构上可区分**（`StageReport`）
7. **对原文的每次自由操作都要留痕**，概括/改写/丢弃即为越界（`TrailEntry`）
8. **前置缺失时拒绝执行，不返回空结果**

---

## 快速开始

```bash
pip install -e .
uvicorn app.api.main:app --reload
langgraph dev          # 在 LangSmith Studio 里看图和回放
```
