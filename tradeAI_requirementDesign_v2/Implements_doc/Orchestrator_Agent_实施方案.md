# Orchestrator Agent 层实施方案

版本：v0.1 / 待评审
日期：2026-11-08
适用阶段：Phase 1 / 编排层
读者：架构师、开发人员、后续编码 Agent

## 1. 定位与职责

Orchestrator 是控制平面的核心，负责接收用户请求、分类意图、路由到对应 Agent 能力组、管理任务生命周期、聚合结果、触发质量复核、原子发布。

### 1.1 设计原则

| 原则 | 实现约束 |
|------|---------|
| 状态机驱动 | 持久化状态 + 预定义 DAG 工作流；LLM 仅辅助意图分类，不决定授权或路由 |
| 写入分离 | Agent 只发布结构化结果（Answer/Finding/Proposal）；业务写入由宿主 Command 层执行 |
| 最小上下文 | 每个 Agent 只获得其职责所需的授权上下文，不共享全部会话历史 |
| 幂等与可重入 | 同一幂等键不重复创建任务；Worker 崩溃后租约过期可重新领取 |
| 预算继承 | 子任务继承父任务剩余 deadline 和预算，不因转交或重试重新获得额度 |
| 失败关闭 | 授权服务或必要持久化不可用时拒绝请求；AI 不可用不阻止人工编辑 |

### 1.2 职责边界

```
Orchestrator 负责：                    Orchestrator 不负责：
─────────────────                     ──────────────────
✓ 意图分类与路由                       ✗ 文档正文写入
✓ 任务生命周期管理                      ✗ 业务审批执行
✓ 预算与超时控制                       ✗ 规则引擎执行
✓ 结果聚合与冲突检测                    ✗ 模型推理（委托给 Agent）
✓ 触发质量复核                         ✗ 权限授予（委托给宿主身份服务）
✓ 原子发布结果                         ✗ 编辑锁管理
```

## 2. 技术基线

| 组件 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12 | 需求文档建议；生态成熟 |
| Web 框架 | FastAPI + Pydantic v2 | 异步原生、Schema 校验、OpenAPI 生成 |
| 编排框架 | LangGraph | 基于状态图的工作流引擎，支持条件路由、循环、持久化 |
| 数据库 | PostgreSQL + pgvector | 需求文档建议；向量检索 + 事务保证 |
| 任务队列 | PostgreSQL Job 表 + FOR UPDATE SKIP LOCKED | 轻量级，无需额外中间件 |
| 缓存 | Redis（可选） | 会话状态、限流计数 |
| 模型网关 | 统一 Adapter 接口 | 可替换 LLM Provider |

## 3. 核心数据合同

### 3.1 TaskEnvelope — 任务信封

```python
# orchestrator/contracts/task_envelope.py

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AgentCapability(str, Enum):
    """Agent 能力白名单"""
    KNOWLEDGE = "knowledge"
    AUTOMATION = "automation"
    STANDARDS_AUDIT = "standards_audit"
    REGULATORY_ADVICE = "regulatory_advice"


class WorkflowVersion(str, Enum):
    """预定义工作流版本"""
    SINGLE_AGENT = "v1_single"          # 单 Agent 直接路由
    PARALLEL_AUDIT = "v1_parallel_audit" # 并行审计（规范 + 法规）
    SEQUENTIAL_PIPELINE = "v1_sequential" # 串行管道（提取 → 审计 → 建议）
    CLARIFICATION_LOOP = "v1_clarify"    # 澄清循环


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskBudget(BaseModel):
    """任务预算约束"""
    max_steps: int = Field(ge=1, le=50, default=10)
    max_model_calls: int = Field(ge=1, le=100, default=20)
    max_input_tokens: int = Field(ge=1000, le=500_000, default=50_000)
    max_output_tokens: int = Field(ge=1000, le=200_000, default=20_000)
    max_tool_calls: int = Field(ge=1, le=50, default=10)
    tool_timeout_seconds: int = Field(ge=5, le=300, default=60)
    max_concurrent_agents: int = Field(ge=1, le=4, default=2)


class TaskEnvelope(BaseModel):
    """
    任务信封 — Orchestrator 的核心输入合同。
    
    由可信服务（API 层）生成，Agent 不可修改。
    包含任务标识、路由目标、预算约束和截止时间。
    """
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    idempotency_key: str = Field(min_length=8, max_length=128)
    
    # 主体与权限 — 只能由可信服务生成
    actor_user_id: str
    actor_org_id: str
    access_context_id: str
    active_capabilities: list[AgentCapability]
    
    # 路由目标
    parent_task_id: Optional[str] = None
    workflow_version: WorkflowVersion = WorkflowVersion.SINGLE_AGENT
    target_capabilities: list[AgentCapability] = Field(min_length=1)
    
    # 资源引用
    workspace_id: str
    document_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    selection_anchor: Optional[dict] = None  # {node_id, start_offset, end_offset}
    attachment_ids: list[str] = Field(default_factory=list)
    
    # 请求内容
    intent: str  # 分类后的意图标签
    user_message: str = Field(min_length=1, max_length=10_000)
    metadata: dict = Field(default_factory=dict)
    
    # 预算与时间
    priority: TaskPriority = TaskPriority.NORMAL
    budget: TaskBudget = Field(default_factory=TaskBudget)
    deadline_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 状态追踪
    attempt: int = Field(default=0, ge=0, le=3)
    status: str = "queued"
    
    @field_validator("deadline_at")
    @classmethod
    def deadline_must_be_future(cls, v: datetime) -> datetime:
        if v <= datetime.utcnow():
            raise ValueError("deadline_at must be in the future")
        return v
    
    @field_validator("target_capabilities")
    @classmethod
    def capabilities_not_empty(cls, v: list[AgentCapability]) -> list[AgentCapability]:
        if not v:
            raise ValueError("target_capabilities must not be empty")
        return list(dict.fromkeys(v))  # 去重保序
    
    def remaining_budget(self, consumed: TaskBudget) -> TaskBudget:
        """计算剩余预算（子任务继承）"""
        return TaskBudget(
            max_steps=max(1, self.budget.max_steps - consumed.max_steps),
            max_model_calls=max(1, self.budget.max_model_calls - consumed.max_model_calls),
            max_input_tokens=max(1000, self.budget.max_input_tokens - consumed.max_input_tokens),
            max_output_tokens=max(1000, self.budget.max_output_tokens - consumed.max_output_tokens),
            max_tool_calls=max(1, self.budget.max_tool_calls - consumed.max_tool_calls),
            tool_timeout_seconds=self.budget.tool_timeout_seconds,
            max_concurrent_agents=self.budget.max_concurrent_agents,
        )
    
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.deadline_at
    
    def remaining_seconds(self) -> float:
        delta = (self.deadline_at - datetime.utcnow()).total_seconds()
        return max(0.0, delta)
```

### 3.2 ContextSnapshot — 不可变上下文快照

```python
# orchestrator/contracts/context_snapshot.py

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentReference(BaseModel):
    """文档引用 — 指向不可变快照"""
    document_id: str
    snapshot_id: str
    content_sha256: str
    version_label: str
    content_level: str  # shared / organization / bank_internal
    is_current: bool
    frozen_at: datetime


class AttachmentReference(BaseModel):
    """附件引用"""
    attachment_id: str
    version_id: str
    file_sha256: str
    parse_status: str  # complete / partial / failed / pending
    page_count: int = Field(ge=0)
    ocr_pending_fields: list[str] = Field(default_factory=list)


class FactsVersion(BaseModel):
    """事实版本 — 已确认的结构化字段"""
    facts_version_id: str
    confirmed_fields: dict  # field_id -> typed value
    unconfirmed_candidates: dict  # field_id -> [candidate]
    confirmed_at: datetime
    confirmed_by: str


class VariablesVersion(BaseModel):
    """变量版本 — 文档中的变量绑定"""
    variables_version_id: str
    bindings: dict  # variable_id -> {field_id, value, anchors}
    schema_version_id: str
    frozen_at: datetime


class AuthorizationContext(BaseModel):
    """授权上下文 — 服务端计算，不可客户端伪造"""
    access_context_id: str
    actor_user_id: str
    actor_org_id: str
    org_membership_status: str  # active / pending / suspended
    guest_context: Optional[dict] = None  # 访客时有值
    granted_capabilities: list[str]
    content_tier: str  # shared / organization / bank_internal
    authorization_version: str
    authorized_at: datetime


class ContextSnapshot(BaseModel):
    """
    不可变上下文快照。
    
    所有 Agent 针对同一快照执行，不跟随"最新"状态。
    快照在任务创建时冻结，中途不可修改。
    """
    snapshot_id: str = Field(default_factory=lambda: f"snap_{hashlib.sha256(str(datetime.utcnow()).encode()).hexdigest()[:16]}")
    
    # 文档
    document: DocumentReference
    attachments: list[AttachmentReference] = Field(default_factory=list)
    
    # 事实与变量
    facts: Optional[FactsVersion] = None
    variables: Optional[VariablesVersion] = None
    
    # 授权
    authorization: AuthorizationContext
    
    # 选区
    selection_text: Optional[str] = None
    selection_anchor: Optional[dict] = None
    
    # 适用性
    applicable_jurisdictions: list[str] = Field(default_factory=list)
    assessment_date: str  # YYYY-MM-DD
    template_version_id: Optional[str] = None
    rule_bundle_version_ids: list[str] = Field(default_factory=list)
    knowledge_release_id: Optional[str] = None
    
    # 元数据
    frozen_at: datetime = Field(default_factory=datetime.utcnow)
    content_sha256: str
    
    def verify_integrity(self, content: str) -> bool:
        """验证内容摘要与快照一致"""
        computed = hashlib.sha256(content.encode()).hexdigest()
        return computed == self.content_sha256
```

### 3.3 AgentResult — Agent 输出合同

```python
# orchestrator/contracts/agent_result.py

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


class ResultType(str, Enum):
    ANSWER = "answer"
    FINDING = "finding"
    SUGGESTION = "suggestion"
    CLARIFICATION = "clarification"
    HANDOFF = "handoff"
    ERROR = "error"


class SupportLevel(str, Enum):
    STRONG = "strong"
    QUALIFIED = "qualified"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


class EvidenceRef(BaseModel):
    """证据引用 — 所有专业结论必须可追溯"""
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:12]}")
    source_id: str
    source_version_id: str
    kind: str  # law / regulation / trade_standard / internal_policy / template / document / attachment
    publisher: str
    title: str
    locator: dict  # {page?, section?, node_id?, clause_id?}
    excerpt: str = Field(max_length=5000)
    excerpt_sha256: str
    language: str
    jurisdiction: Optional[str] = None
    valid_from: Optional[str] = None  # YYYY-MM-DD
    valid_to: Optional[str] = None
    retrieved_at: Optional[datetime] = None


class Anchor(BaseModel):
    """原文锚点 — 定位到具体位置"""
    resource_kind: str  # document / attachment
    resource_id: str
    version_id: str
    locator: dict  # {node_id, start_utf16, end_utf16} 或 {page, block_id}
    quote_sha256: str


class Claim(BaseModel):
    """结构化结论"""
    claim_id: str = Field(default_factory=lambda: f"claim_{uuid.uuid4().hex[:8]}")
    text: str
    kind: str  # fact / interpretation
    evidence_ids: list[str] = Field(min_length=0)  # fact 至少一个
    anchor_ids: list[str] = Field(default_factory=list)
    support_level: SupportLevel = SupportLevel.QUALIFIED


class CoverageEntry(BaseModel):
    """覆盖矩阵条目"""
    check_id: str
    scope_key: str
    status: str  # pass / finding / not_applicable / needs_input / unable_to_assess / failed
    method: str  # deterministic / semantic / legal
    reason_codes: list[str] = Field(default_factory=list)


class Limitation(BaseModel):
    """限制说明"""
    code: str
    message: str
    check_ids: list[str] = Field(default_factory=list)


class ProposedChange(BaseModel):
    """修改建议 — 不包含可执行代码"""
    change_id: str = Field(default_factory=lambda: f"chg_{uuid.uuid4().hex[:8]}")
    base_snapshot_id: str
    base_content_sha256: str
    anchor: Anchor
    replacement_text: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    is_substantive: bool = False  # 涉及义务/事实变更时标记


class AnswerPayload(BaseModel):
    """知识助手回答"""
    outcome: str  # answered / needs_clarification / insufficient_evidence / unable_to_assess / needs_handoff
    language: str
    support_level: SupportLevel
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    handoff_target: Optional[str] = None  # automation / standards_audit / regulatory_advice


class FindingPayload(BaseModel):
    """审计/法规发现"""
    finding_id: str = Field(default_factory=lambda: f"find_{uuid.uuid4().hex[:8]}")
    category: str  # field / variable / consistency / template / policy / legal
    severity: str  # Critical / Warning / Info
    gate_type: str  # advisory / human_review / hard_block
    target_operations: list[str] = Field(default_factory=list)
    title: str
    explanation: str
    anchors: list[Anchor] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    rule_refs: list[dict] = Field(default_factory=list)  # [{rule_id, version}]
    support_level: SupportLevel = SupportLevel.QUALIFIED
    proposed_change: Optional[ProposedChange] = None
    coverage: list[CoverageEntry] = Field(default_factory=list)


class SuggestionPayload(BaseModel):
    """自动化建议"""
    suggestion_type: str  # extract / fill / rewrite / compare / map_api
    changes: list[ProposedChange] = Field(default_factory=list)
    extractions: list[dict] = Field(default_factory=list)  # FieldCandidate
    diff_summary: Optional[dict] = None
    coverage: list[CoverageEntry] = Field(default_factory=list)


class AgentResult(BaseModel):
    """
    Agent 统一输出合同。
    
    由 Agent Worker 生成，经 ResultAggregator 聚合后发布。
    Agent 不可通过此合同直接写入文档或执行业务操作。
    """
    result_id: str = Field(default_factory=lambda: f"res_{uuid.uuid4().hex[:12]}")
    task_id: str
    run_id: str
    agent_capability: str
    result_type: ResultType
    
    # 源快照引用
    source_snapshot_id: str
    source_content_sha256: str
    
    # 类型化 payload
    payload: Union[AnswerPayload, FindingPayload, SuggestionPayload, dict]
    
    # 证据与覆盖
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    coverage: list[CoverageEntry] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    
    # 依赖记录 — 读取过的所有资源
    dependencies: list[dict] = Field(default_factory=list)  # [{resource_id, version_id, access_checked_at}]
    
    # 执行元数据
    model_version: str
    model_call_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    tool_calls: list[dict] = Field(default_factory=list)
    execution_time_ms: int = Field(ge=0)
    
    # 状态
    status: str  # succeeded / partial / failed
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def is_terminal_success(self) -> bool:
        return self.status == "succeeded" and self.result_type != ResultType.ERROR
    
    @property
    def has_findings(self) -> bool:
        if isinstance(self.payload, FindingPayload):
            return True
        if isinstance(self.payload, dict):
            return self.payload.get("findings", []) != []
        return False
```

### 3.4 ReviewReceipt — 复核凭据

```python
# orchestrator/contracts/review_receipt.py

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReviewIssue(BaseModel):
    """复核发现的问题"""
    code: str  # schema_violation / citation_missing / anchor_invalid / unsupported_claim / scope_exceeded / conflict
    claim_id: Optional[str] = None
    evidence_id: Optional[str] = None
    explanation: str = Field(max_length=1000)


class ReviewReceipt(BaseModel):
    """
    复核凭据 — 证明结果已通过质量闸门。
    
    不能由生成 Agent 自报"已通过"。
    由独立的 Reviewer 服务生成。
    """
    receipt_id: str = Field(default_factory=lambda: f"rev_{uuid.uuid4().hex[:12]}")
    result_id: str
    task_id: str
    run_id: str
    
    # 复核范围
    review_scope: str  # in_group / cross_group / final
    review_strategy_version: str
    
    # 复核决定
    decision: str  # pass / repair / abstain
    issues: list[ReviewIssue] = Field(default_factory=list)
    repaired_claim_ids: list[str] = Field(default_factory=list)
    abstain_reason: Optional[str] = None
    
    # 检查项
    schema_valid: bool
    citations_verified: bool
    anchors_verified: bool
    claims_supported: bool
    scope_respected: bool
    conflicts_checked: bool
    
    # 复核器
    reviewer_identity: str  # service account
    reviewer_version: str
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 摘要
    input_sha256: str
    result_sha256: str
    evidence_sha256: str
    
    @property
    def is_valid(self) -> bool:
        return self.decision == "pass" or (
            self.decision == "repair" and len(self.repaired_claim_ids) > 0
        )
```

## 4. 状态机设计

### 4.1 任务状态

```python
# orchestrator/state_machine/task_states.py

from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    """任务生命周期状态"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class TaskStage(str, Enum):
    """任务执行阶段"""
    QUEUED = "queued"
    RESOLVING_CONTEXT = "resolving_context"
    CLASSIFYING_INTENT = "classifying_intent"
    ROUTING = "routing"
    EXECUTING_AGENT = "executing_agent"
    AGGREGATING = "aggregating"
    REVIEWING = "reviewing"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


# 合法状态转换
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT, TaskStatus.QUEUED},
    TaskStatus.SUCCEEDED: set(),  # 终态
    TaskStatus.FAILED: set(),     # 终态
    TaskStatus.CANCELLED: set(),  # 终态
    TaskStatus.TIMED_OUT: set(),  # 终态
}

VALID_STAGE_TRANSITIONS: dict[TaskStage, set[TaskStage]] = {
    TaskStage.QUEUED: {TaskStage.RESOLVING_CONTEXT, TaskStage.CANCELLED, TaskStage.TIMED_OUT},
    TaskStage.RESOLVING_CONTEXT: {TaskStage.CLASSIFYING_INTENT, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.CLASSIFYING_INTENT: {TaskStage.ROUTING, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.ROUTING: {TaskStage.EXECUTING_AGENT, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.EXECUTING_AGENT: {TaskStage.AGGREGATING, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.AGGREGATING: {TaskStage.REVIEWING, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.REVIEWING: {TaskStage.PUBLISHING, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.PUBLISHING: {TaskStage.COMPLETED, TaskStage.FAILED, TaskStage.TIMED_OUT},
    TaskStage.COMPLETED: set(),
    TaskStage.FAILED: set(),
    TaskStage.CANCELLED: set(),
    TaskStage.TIMED_OUT: set(),
}


class TaskStateMachine:
    """
    任务状态机 — 确保状态转换合法性。
    
    使用 compare-and-set 语义，防止并发覆盖。
    """
    
    def __init__(self, current_status: TaskStatus, current_stage: TaskStage):
        self._status = current_status
        self._stage = current_stage
        self._fencing_token: int = 0
    
    @property
    def status(self) -> TaskStatus:
        return self._status
    
    @property
    def stage(self) -> TaskStage:
        return self._stage
    
    @property
    def fencing_token(self) -> int:
        return self._fencing_token
    
    def can_transition_to(self, new_status: TaskStatus) -> bool:
        return new_status in VALID_TRANSITIONS.get(self._status, set())
    
    def can_advance_stage(self, new_stage: TaskStage) -> bool:
        return new_stage in VALID_STAGE_TRANSITIONS.get(self._stage, set())
    
    def transition_to(self, new_status: TaskStatus) -> bool:
        """原子状态转换，返回是否成功"""
        if not self.can_transition_to(new_status):
            return False
        self._status = new_status
        return True
    
    def advance_stage(self, new_stage: TaskStage) -> bool:
        """推进执行阶段"""
        if not self.can_advance_stage(new_stage):
            return False
        self._stage = new_stage
        return True
    
    def increment_fencing_token(self) -> int:
        """递增 fencing token，用于防止迟到 Worker 覆盖终态"""
        self._fencing_token += 1
        return self._fencing_token
    
    def is_terminal(self) -> bool:
        return self._status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}
```

### 4.2 LangGraph 状态定义

```python
# orchestrator/graph/state.py

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from orchestrator.contracts.task_envelope import TaskEnvelope, TaskBudget
from orchestrator.contracts.context_snapshot import ContextSnapshot
from orchestrator.contracts.agent_result import AgentResult
from orchestrator.contracts.review_receipt import ReviewReceipt
from orchestrator.state_machine.task_states import TaskStatus, TaskStage


class OrchestratorState(BaseModel):
    """
    LangGraph 编排器共享状态。
    
    所有节点读写同一状态对象，状态变更通过 LangGraph 的 reducer 机制合并。
    """
    # 任务标识
    task_id: str
    run_id: str
    request_id: str
    
    # 输入
    envelope: TaskEnvelope
    context: Optional[ContextSnapshot] = None
    
    # 执行状态
    status: TaskStatus = TaskStatus.QUEUED
    stage: TaskStage = TaskStage.QUEUED
    attempt: int = 0
    fencing_token: int = 0
    
    # 意图分类结果
    classified_intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    classification_metadata: dict = Field(default_factory=dict)
    
    # 路由决策
    target_capabilities: list[str] = Field(default_factory=list)
    workflow_version: Optional[str] = None
    
    # Agent 执行结果
    agent_results: list[AgentResult] = Field(default_factory=list)
    consumed_budget: TaskBudget = Field(default_factory=TaskBudget)
    
    # 聚合结果
    aggregated_findings: list[dict] = Field(default_factory=list)
    aggregated_answers: list[dict] = Field(default_factory=list)
    aggregated_suggestions: list[dict] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    coverage_gaps: list[dict] = Field(default_factory=list)
    
    # 质量复核
    review_receipts: list[ReviewReceipt] = Field(default_factory=list)
    review_passed: Optional[bool] = None
    repair_attempts: int = 0
    
    # 最终输出
    final_result: Optional[dict] = None
    published_at: Optional[datetime] = None
    
    # 错误
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # 消息历史（用于调试和审计）
    messages: Annotated[list, add_messages] = Field(default_factory=list)
    
    # 元数据
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        arbitrary_types_allowed = True
    
    def mark_stage(self, stage: TaskStage) -> None:
        self.stage = stage
        self.updated_at = datetime.utcnow()
    
    def mark_status(self, status: TaskStatus) -> None:
        self.status = status
        self.updated_at = datetime.utcnow()
    
    def add_agent_result(self, result: AgentResult) -> None:
        self.agent_results.append(result)
        self.consumed_budget.max_model_calls += result.model_call_count
        self.consumed_budget.max_input_tokens += result.input_tokens
        self.consumed_budget.max_output_tokens += result.output_tokens
        self.consumed_budget.max_tool_calls += len(result.tool_calls)
        self.consumed_budget.max_steps += 1
        self.updated_at = datetime.utcnow()
    
    def is_budget_exhausted(self) -> bool:
        b = self.envelope.budget
        c = self.consumed_budget
        return (
            c.max_steps >= b.max_steps or
            c.max_model_calls >= b.max_model_calls or
            c.max_input_tokens >= b.max_input_tokens or
            c.max_output_tokens >= b.max_output_tokens or
            c.max_tool_calls >= b.max_tool_calls
        )
    
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.envelope.deadline_at
```

## 5. LangGraph 工作流实现

### 5.1 编排器主图

```python
# orchestrator/graph/orchestrator.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

from orchestrator.graph.state import OrchestratorState
from orchestrator.contracts.task_envelope import TaskEnvelope, AgentCapability
from orchestrator.contracts.context_snapshot import ContextSnapshot
from orchestrator.agents.intent_classifier import IntentClassifier
from orchestrator.agents.router import TaskRouter
from orchestrator.agents.result_aggregator import ResultAggregator
from orchestrator.agents.quality_reviewer import QualityReviewer
from orchestrator.agents.result_publisher import ResultPublisher
from orchestrator.adapters.context_resolver import ContextResolver
from orchestrator.persistence.job_store import JobStore

logger = logging.getLogger(__name__)


class TradeAIOrchestrator:
    """
    TradeAI 编排器 — 基于 LangGraph 的状态机工作流。
    
    职责：
    1. 接收 TaskEnvelope
    2. 冻结 ContextSnapshot
    3. 分类意图
    4. 路由到 Agent 能力组
    5. 执行 Agent（委托给 Worker）
    6. 聚合结果
    7. 触发质量复核
    8. 原子发布
    
    不负责：
    - 文档写入
    - 业务审批
    - 权限授予
    """
    
    def __init__(
        self,
        context_resolver: ContextResolver,
        intent_classifier: IntentClassifier,
        task_router: TaskRouter,
        result_aggregator: ResultAggregator,
        quality_reviewer: QualityReviewer,
        result_publisher: ResultPublisher,
        job_store: JobStore,
        checkpointer: Optional[PostgresSaver] = None,
    ):
        self.context_resolver = context_resolver
        self.intent_classifier = intent_classifier
        self.task_router = task_router
        self.result_aggregator = result_aggregator
        self.quality_reviewer = quality_reviewer
        self.result_publisher = result_publisher
        self.job_store = job_store
        self.checkpointer = checkpointer
        
        self._graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态图"""
        
        workflow = StateGraph(OrchestratorState)
        
        # 添加节点
        workflow.add_node("resolve_context", self._resolve_context)
        workflow.add_node("classify_intent", self._classify_intent)
        workflow.add_node("route_task", self._route_task)
        workflow.add_node("execute_knowledge", self._execute_knowledge)
        workflow.add_node("execute_automation", self._execute_automation)
        workflow.add_node("execute_audit", self._execute_audit)
        workflow.add_node("execute_legal", self._execute_legal)
        workflow.add_node("aggregate_results", self._aggregate_results)
        workflow.add_node("review_quality", self._review_quality)
        workflow.add_node("publish_result", self._publish_result)
        workflow.add_node("handle_error", self._handle_error)
        workflow.add_node("handle_timeout", self._handle_timeout)
        
        # 入口边
        workflow.set_entry_point("resolve_context")
        
        # resolve_context → classify_intent 或 handle_error
        workflow.add_conditional_edges(
            "resolve_context",
            self._check_context_resolved,
            {
                "continue": "classify_intent",
                "error": "handle_error",
                "timeout": "handle_timeout",
            }
        )
        
        # classify_intent → route_task 或 handle_error
        workflow.add_conditional_edges(
            "classify_intent",
            self._check_intent_classified,
            {
                "continue": "route_task",
                "clarification_needed": "publish_result",  # 直接发布澄清请求
                "error": "handle_error",
                "timeout": "handle_timeout",
            }
        )
        
        # route_task → 各 Agent 节点
        workflow.add_conditional_edges(
            "route_task",
            self._select_agent_route,
            {
                "knowledge": "execute_knowledge",
                "automation": "execute_automation",
                "audit": "execute_audit",
                "legal": "execute_legal",
                "parallel_audit_legal": "execute_audit",  # 并行执行，先启动 audit
                "error": "handle_error",
                "timeout": "handle_timeout",
            }
        )
        
        # 各 Agent → aggregate_results
        workflow.add_edge("execute_knowledge", "aggregate_results")
        workflow.add_edge("execute_automation", "aggregate_results")
        workflow.add_edge("execute_audit", "aggregate_results")
        workflow.add_edge("execute_legal", "aggregate_results")
        
        # aggregate_results → review_quality 或 handle_error
        workflow.add_conditional_edges(
            "aggregate_results",
            self._check_aggregation,
            {
                "continue": "review_quality",
                "error": "handle_error",
                "timeout": "handle_timeout",
            }
        )
        
        # review_quality → publish_result 或 handle_error
        workflow.add_conditional_edges(
            "review_quality",
            self._check_review,
            {
                "publish": "publish_result",
                "repair_needed": "aggregate_results",  # 修复后重新聚合（最多一次）
                "abstain": "publish_result",  # 弃答也发布（带限制说明）
                "error": "handle_error",
                "timeout": "handle_timeout",
            }
        )
        
        # publish_result → END
        workflow.add_edge("publish_result", END)
        
        # handle_error → END
        workflow.add_edge("handle_error", END)
        
        # handle_timeout → END
        workflow.add_edge("handle_timeout", END)
        
        # 编译
        if self.checkpointer:
            return workflow.compile(checkpointer=self.checkpointer)
        return workflow.compile()
    
    # ─── 节点实现 ───────────────────────────────────────────────
    
    async def _resolve_context(self, state: OrchestratorState) -> dict:
        """冻结不可变上下文快照"""
        state.mark_stage(state.stage.RESOLVING_CONTEXT)
        
        try:
            # 检查超时
            if state.is_expired():
                state.mark_status(state.status.TIMED_OUT)
                return {"status": TaskStatus.TIMED_OUT}
            
            # 调用 ContextResolver 冻结快照
            context = await self.context_resolver.freeze(
                envelope=state.envelope,
                access_context_id=state.envelope.access_context_id,
            )
            
            # 验证快照完整性
            if not context.document.is_current:
                logger.warning(
                    f"Document {context.document.document_id} snapshot is not current; "
                    f"proceeding with frozen version {context.document.snapshot_id}"
                )
            
            return {
                "context": context,
                "stage": TaskStage.CLASSIFYING_INTENT,
            }
            
        except PermissionError as e:
            logger.error(f"Context resolution failed: permission denied — {e}")
            return {
                "error_code": "CONTEXT_PERMISSION_DENIED",
                "error_message": "One or more required resources are not accessible.",
                "status": TaskStatus.FAILED,
            }
        except Exception as e:
            logger.error(f"Context resolution failed: {e}")
            return {
                "error_code": "CONTEXT_RESOLUTION_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _classify_intent(self, state: OrchestratorState) -> dict:
        """分类用户意图"""
        state.mark_stage(state.stage.CLASSIFYING_INTENT)
        
        try:
            if state.is_expired() or state.is_budget_exhausted():
                return self._budget_or_timeout_result(state)
            
            result = await self.intent_classifier.classify(
                user_message=state.envelope.user_message,
                context=state.context,
                selection_text=state.context.selection_text if state.context else None,
            )
            
            return {
                "classified_intent": result.intent,
                "intent_confidence": result.confidence,
                "classification_metadata": result.metadata,
                "stage": TaskStage.ROUTING,
            }
            
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return {
                "error_code": "INTENT_CLASSIFICATION_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _route_task(self, state: OrchestratorState) -> dict:
        """路由任务到目标 Agent 能力组"""
        state.mark_stage(state.stage.ROUTING)
        
        try:
            if state.is_expired() or state.is_budget_exhausted():
                return self._budget_or_timeout_result(state)
            
            routing = await self.task_router.route(
                intent=state.classified_intent,
                confidence=state.intent_confidence,
                envelope=state.envelope,
                context=state.context,
            )
            
            if routing.needs_clarification:
                return {
                    "target_capabilities": [],
                    "final_result": {
                        "outcome": "needs_clarification",
                        "questions": routing.clarification_questions,
                        "reason": routing.clarification_reason,
                    },
                    "status": TaskStatus.SUCCEEDED,
                    "stage": TaskStage.COMPLETED,
                }
            
            return {
                "target_capabilities": [c.value for c in routing.target_capabilities],
                "workflow_version": routing.workflow_version.value,
                "stage": TaskStage.EXECUTING_AGENT,
            }
            
        except Exception as e:
            logger.error(f"Task routing failed: {e}")
            return {
                "error_code": "ROUTING_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _execute_knowledge(self, state: OrchestratorState) -> dict:
        """执行知识助手 Agent"""
        from orchestrator.agents.knowledge_worker import KnowledgeWorker
        
        worker = KnowledgeWorker(
            context=state.context,
            envelope=state.envelope,
            budget=state.envelope.remaining_budget(state.consumed_budget),
        )
        
        result = await worker.execute()
        state.add_agent_result(result)
        
        return {"agent_results": state.agent_results}
    
    async def _execute_automation(self, state: OrchestratorState) -> dict:
        """执行自动化助手 Agent"""
        from orchestrator.agents.automation_worker import AutomationWorker
        
        worker = AutomationWorker(
            context=state.context,
            envelope=state.envelope,
            budget=state.envelope.remaining_budget(state.consumed_budget),
        )
        
        result = await worker.execute()
        state.add_agent_result(result)
        
        return {"agent_results": state.agent_results}
    
    async def _execute_audit(self, state: OrchestratorState) -> dict:
        """执行规范审计 Agent"""
        from orchestrator.agents.audit_worker import AuditWorker
        
        worker = AuditWorker(
            context=state.context,
            envelope=state.envelope,
            budget=state.envelope.remaining_budget(state.consumed_budget),
        )
        
        result = await worker.execute()
        state.add_agent_result(result)
        
        return {"agent_results": state.agent_results}
    
    async def _execute_legal(self, state: OrchestratorState) -> dict:
        """执行法规建议 Agent"""
        from orchestrator.agents.legal_worker import LegalWorker
        
        worker = LegalWorker(
            context=state.context,
            envelope=state.envelope,
            budget=state.envelope.remaining_budget(state.consumed_budget),
        )
        
        result = await worker.execute()
        state.add_agent_result(result)
        
        return {"agent_results": state.agent_results}
    
    async def _aggregate_results(self, state: OrchestratorState) -> dict:
        """聚合多个 Agent 的结果"""
        state.mark_stage(state.stage.AGGREGATING)
        
        try:
            if state.is_expired() or state.is_budget_exhausted():
                return self._budget_or_timeout_result(state)
            
            aggregation = await self.result_aggregator.aggregate(
                results=state.agent_results,
                context=state.context,
                target_capabilities=state.target_capabilities,
            )
            
            return {
                "aggregated_findings": aggregation.findings,
                "aggregated_answers": aggregation.answers,
                "aggregated_suggestions": aggregation.suggestions,
                "conflicts": aggregation.conflicts,
                "coverage_gaps": aggregation.coverage_gaps,
                "stage": TaskStage.REVIEWING,
            }
            
        except Exception as e:
            logger.error(f"Result aggregation failed: {e}")
            return {
                "error_code": "AGGREGATION_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _review_quality(self, state: OrchestratorState) -> dict:
        """触发质量复核"""
        state.mark_stage(state.stage.REVIEWING)
        
        try:
            if state.is_expired() or state.is_budget_exhausted():
                return self._budget_or_timeout_result(state)
            
            # 检查是否已经修复过一次
            if state.repair_attempts >= 1:
                logger.warning("Max repair attempts reached; publishing as-is with limitations")
                return {
                    "review_passed": False,
                    "stage": TaskStage.PUBLISHING,
                }
            
            review = await self.quality_reviewer.review(
                aggregated_findings=state.aggregated_findings,
                aggregated_answers=state.aggregated_answers,
                aggregated_suggestions=state.aggregated_suggestions,
                agent_results=state.agent_results,
                context=state.context,
            )
            
            state.review_receipts.extend(review.receipts)
            
            if review.decision == "pass":
                return {
                    "review_passed": True,
                    "stage": TaskStage.PUBLISHING,
                }
            elif review.decision == "repair":
                return {
                    "review_passed": False,
                    "repair_attempts": state.repair_attempts + 1,
                    "stage": TaskStage.AGGREGATING,  # 重新聚合
                }
            else:  # abstain
                return {
                    "review_passed": False,
                    "stage": TaskStage.PUBLISHING,
                }
            
        except Exception as e:
            logger.error(f"Quality review failed: {e}")
            return {
                "error_code": "REVIEW_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _publish_result(self, state: OrchestratorState) -> dict:
        """原子发布最终结果"""
        state.mark_stage(state.stage.PUBLISHING)
        
        try:
            published = await self.result_publisher.publish(
                state=state,
            )
            
            return {
                "final_result": published.result,
                "published_at": published.published_at,
                "status": TaskStatus.SUCCEEDED,
                "stage": TaskStage.COMPLETED,
            }
            
        except Exception as e:
            logger.error(f"Result publishing failed: {e}")
            return {
                "error_code": "PUBLISHING_FAILED",
                "error_message": str(e),
                "status": TaskStatus.FAILED,
            }
    
    async def _handle_error(self, state: OrchestratorState) -> dict:
        """处理错误状态"""
        state.mark_status(state.status.FAILED)
        
        await self.job_store.record_failure(
            run_id=state.run_id,
            error_code=state.error_code or "UNKNOWN_ERROR",
            error_message=state.error_message or "Unspecified error",
        )
        
        return {
            "status": TaskStatus.FAILED,
            "stage": TaskStage.FAILED,
        }
    
    async def _handle_timeout(self, state: OrchestratorState) -> dict:
        """处理超时状态"""
        state.mark_status(state.status.TIMED_OUT)
        
        await self.job_store.record_timeout(
            run_id=state.run_id,
            deadline_at=state.envelope.deadline_at,
        )
        
        return {
            "status": TaskStatus.TIMED_OUT,
            "stage": TaskStage.TIMED_OUT,
        }
    
    # ─── 条件路由 ───────────────────────────────────────────────
    
    def _check_context_resolved(self, state: OrchestratorState) -> str:
        if state.status == TaskStatus.FAILED:
            return "error"
        if state.status == TaskStatus.TIMED_OUT:
            return "timeout"
        if state.context is not None:
            return "continue"
        return "error"
    
    def _check_intent_classified(self, state: OrchestratorState) -> str:
        if state.status == TaskStatus.FAILED:
            return "error"
        if state.status == TaskStatus.TIMED_OUT:
            return "timeout"
        if state.classified_intent == "needs_clarification":
            return "clarification_needed"
        if state.classified_intent is not None:
            return "continue"
        return "error"
    
    def _select_agent_route(self, state: OrchestratorState) -> str:
        if state.status == TaskStatus.FAILED:
            return "error"
        if state.status == TaskStatus.TIMED_OUT:
            return "timeout"
        
        caps = set(state.target_capabilities)
        if caps == {AgentCapability.KNOWLEDGE.value}:
            return "knowledge"
        if caps == {AgentCapability.AUTOMATION.value}:
            return "automation"
        if caps == {AgentCapability.STANDARDS_AUDIT.value}:
            return "audit"
        if caps == {AgentCapability.RAGULATORY_ADVICE.value}:
            return "legal"
        if caps == {AgentCapability.STANDARDS_AUDIT.value, AgentCapability.REGULATORY_ADVICE.value}:
            return "parallel_audit_legal"
        
        # 默认路由到知识助手
        return "knowledge"
    
    def _check_aggregation(self, state: OrchestratorState) -> str:
        if state.status == TaskStatus.FAILED:
            return "error"
        if state.status == TaskStatus.TIMED_OUT:
            return "timeout"
        return "continue"
    
    def _check_review(self, state: OrchestratorState) -> str:
        if state.status == TaskStatus.FAILED:
            return "error"
        if state.status == TaskStatus.TIMED_OUT:
            return "timeout"
        if state.review_passed:
            return "publish"
        if state.repair_attempts < 1:
            return "repair_needed"
        return "abstain"
    
    def _budget_or_timeout_result(self, state: OrchestratorState) -> dict:
        if state.is_expired():
            return {
                "status": TaskStatus.TIMED_OUT,
                "error_code": "TASK_TIMEOUT",
                "error_message": "Task exceeded deadline.",
            }
        return {
            "status": TaskStatus.FAILED,
            "error_code": "BUDGET_EXHAUSTED",
            "error_message": "Task exceeded budget constraints.",
        }
    
    # ─── 公共方法 ───────────────────────────────────────────────
    
    async def execute(self, envelope: TaskEnvelope) -> dict:
        """
        执行编排流程。
        
        1. 创建初始状态
        2. 持久化任务记录
        3. 运行 LangGraph 工作流
        4. 返回最终结果
        """
        # 初始化状态
        initial_state = OrchestratorState(
            task_id=envelope.task_id,
            run_id=envelope.run_id,
            request_id=envelope.request_id,
            envelope=envelope,
            status=TaskStatus.QUEUED,
            stage=TaskStage.QUEUED,
        )
        
        # 持久化任务
        await self.job_store.create_run(
            run_id=envelope.run_id,
            task_id=envelope.task_id,
            envelope=envelope,
        )
        
        # 执行工作流
        try:
            final_state = await self._graph.ainvoke(initial_state)
            
            # 更新任务记录
            await self.job_store.update_run(
                run_id=envelope.run_id,
                status=final_state.status,
                stage=final_state.stage,
                result=final_state.final_result,
                error_code=final_state.error_code,
                error_message=final_state.error_message,
            )
            
            return {
                "run_id": final_state.run_id,
                "task_id": final_state.task_id,
                "status": final_state.status,
                "result": final_state.final_result,
                "error": {
                    "code": final_state.error_code,
                    "message": final_state.error_message,
                } if final_state.error_code else None,
            }
            
        except Exception as e:
            logger.error(f"Orchestrator execution failed: {e}", exc_info=True)
            
            await self.job_store.update_run(
                run_id=envelope.run_id,
                status=TaskStatus.FAILED,
                error_code="ORCHESTRATOR_FAILED",
                error_message=str(e),
            )
            
            raise
```

### 5.2 意图分类器

```python
# orchestrator/agents/intent_classifier.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from orchestrator.contracts.context_snapshot import ContextSnapshot

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """预定义意图枚举 — 分类结果必须属于此集合"""
    # 知识助手
    PRODUCT_FAQ = "product_faq"
    TRADE_RULE_EXPLANATION = "trade_rule_explanation"
    DOCUMENT_EXPLANATION = "document_explanation"
    
    # 自动化助手
    EXTRACT_FIELDS = "extract_fields"
    FILL_VARIABLES = "fill_variables"
    REWRITE_TEXT = "rewrite_text"
    COMPARE_VERSIONS = "compare_versions"
    MAP_API_TEMPLATE = "map_api_template"
    
    # 规范审计
    RUN_DETERMINISTIC_AUDIT = "run_deterministic_audit"
    RUN_SEMANTIC_AUDIT = "run_semantic_audit"
    
    # 法规建议
    CHECK_REGULATORY_COMPLIANCE = "check_regulatory_compliance"
    ANALYZE_LEGAL_APPLICABILITY = "analyze_legal_applicability"
    
    # 复合意图
    PRE_REVIEW_DOCUMENT = "pre_review_document"  # 并行审计 + 法规
    
    # 澄清
    NEEDS_CLARIFICATION = "needs_clarification"
    
    # 超出范围
    OUT_OF_SCOPE = "out_of_scope"


# 确定性路由关键词 — 不调用 LLM
DETERMINISTIC_ROUTES: dict[str, Intent] = {
    "运行规范审计": Intent.RUN_DETERMINISTIC_AUDIT,
    "run rules audit": Intent.RUN_DETERMINISTIC_AUDIT,
    "检查字段规范性": Intent.RUN_DETERMINISTIC_AUDIT,
    "比较版本": Intent.COMPARE_VERSIONS,
    "compare versions": Intent.COMPARE_VERSIONS,
    "提取字段": Intent.EXTRACT_FIELDS,
    "extract fields": Intent.EXTRACT_FIELDS,
    "填充变量": Intent.FILL_VARIABLES,
    "fill variables": Intent.FILL_VARIABLES,
    "文档预审": Intent.PRE_REVIEW_DOCUMENT,
    "pre-review document": Intent.PRE_REVIEW_DOCUMENT,
}


@dataclass
class ClassificationResult:
    intent: str
    confidence: float
    metadata: dict
    routing_path: str  # deterministic / llm


class IntentClassifier:
    """
    意图分类器。
    
    策略：
    1. 先尝试确定性关键词匹配（不调用 LLM）
    2. 模糊意图才调用 LLM 分类
    3. 分类结果必须属于预定义 Intent 枚举
    """
    
    def __init__(self, model_gateway=None):
        self.model_gateway = model_gateway
    
    async def classify(
        self,
        user_message: str,
        context: Optional[ContextSnapshot] = None,
        selection_text: Optional[str] = None,
    ) -> ClassificationResult:
        # Step 1: 确定性路由
        normalized = user_message.strip().lower()
        for keyword, intent in DETERMINISTIC_ROUTES.items():
            if keyword.lower() in normalized:
                return ClassificationResult(
                    intent=intent.value,
                    confidence=1.0,
                    metadata={"matched_keyword": keyword},
                    routing_path="deterministic",
                )
        
        # Step 2: Diff 操作不需要 LLM
        if context and self._is_diff_operation(user_message, context):
            return ClassificationResult(
                intent=Intent.COMPARE_VERSIONS.value,
                confidence=0.95,
                metadata={"reason": "diff_operation_detected"},
                routing_path="deterministic",
            )
        
        # Step 3: LLM 分类（模糊意图）
        if self.model_gateway:
            return await self._llm_classify(user_message, context, selection_text)
        
        # Step 4: 无模型时默认转知识助手
        return ClassificationResult(
            intent=Intent.PRODUCT_FAQ.value,
            confidence=0.5,
            metadata={"fallback": "no_model_available"},
            routing_path="fallback",
        )
    
    def _is_diff_operation(self, message: str, context: ContextSnapshot) -> bool:
        """检测是否为版本比较操作"""
        diff_keywords = ["diff", "difference", "compare", "比较", "差异", "区别"]
        return any(kw in message.lower() for kw in diff_keywords)
    
    async def _llm_classify(
        self,
        user_message: str,
        context: Optional[ContextSnapshot],
        selection_text: Optional[str],
    ) -> ClassificationResult:
        """调用 LLM 进行意图分类"""
        
        system_prompt = """You are an intent classifier for a trade document collaboration tool.

Classify the user's request into exactly one of these intents:
- product_faq: Questions about how to use the product
- trade_rule_explanation: Questions about trade rules (URDG, UCP, ISP, etc.)
- document_explanation: Questions about the current document content
- extract_fields: Extract structured fields from uploaded files
- fill_variables: Fill document variables with confirmed values
- rewrite_text: Polish, clarify, or replace text passages
- compare_versions: Compare two document versions
- map_api_template: Map document content to external API template
- run_deterministic_audit: Run format/field compliance checks
- run_semantic_audit: Run semantic consistency checks
- check_regulatory_compliance: Check against regulatory requirements
- analyze_legal_applicability: Analyze legal applicability by jurisdiction
- pre_review_document: Run both audit and regulatory checks in parallel
- needs_clarification: Request is ambiguous or missing critical information
- out_of_scope: Request is outside the system's capabilities

Return ONLY a JSON object: {"intent": "<intent_name>", "confidence": <0.0-1.0>, "reason": "<brief explanation>"}
"""
        
        user_prompt = f"User message: {user_message}"
        if selection_text:
            user_prompt += f"\nSelected text: {selection_text[:500]}"
        if context:
            user_prompt += f"\nDocument type: {context.document.content_level}"
            user_prompt += f"\nApplicable jurisdictions: {context.applicable_jurisdictions}"
        
        try:
            response = await self.model_gateway.generate(
                task="intent_classification",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_schema={"type": "object", "properties": {
                    "intent": {"type": "string", "enum": [i.value for i in Intent]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                }},
                max_tokens=200,
            )
            
            intent = response.get("intent", Intent.PRODUCT_FAQ.value)
            confidence = response.get("confidence", 0.5)
            reason = response.get("reason", "")
            
            # 验证意图属于枚举
            try:
                Intent(intent)
            except ValueError:
                logger.warning(f"LLM returned invalid intent: {intent}; falling back to product_faq")
                intent = Intent.PRODUCT_FAQ.value
                confidence = min(confidence, 0.3)
            
            return ClassificationResult(
                intent=intent,
                confidence=confidence,
                metadata={"reason": reason, "llm_response": response},
                routing_path="llm",
            )
            
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return ClassificationResult(
                intent=Intent.NEEDS_CLARIFICATION.value,
                confidence=0.0,
                metadata={"error": str(e)},
                routing_path="llm_error",
            )
```

### 5.3 任务路由器

```python
# orchestrator/agents/router.py

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from orchestrator.contracts.task_envelope import TaskEnvelope, AgentCapability, WorkflowVersion
from orchestrator.contracts.context_snapshot import ContextSnapshot
from orchestrator.agents.intent_classifier import Intent

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    target_capabilities: list[AgentCapability]
    workflow_version: WorkflowVersion
    needs_clarification: bool = False
    clarification_questions: list[str] = field(default_factory=list)
    clarification_reason: Optional[str] = None


# 意图 → 能力组映射
INTENT_TO_CAPABILITIES: dict[str, list[AgentCapability]] = {
    Intent.PRODUCT_FAQ.value: [AgentCapability.KNOWLEDGE],
    Intent.TRADE_RULE_EXPLANATION.value: [AgentCapability.KNOWLEDGE],
    Intent.DOCUMENT_EXPLANATION.value: [AgentCapability.KNOWLEDGE],
    Intent.EXTRACT_FIELDS.value: [AgentCapability.AUTOMATION],
    Intent.FILL_VARIABLES.value: [AgentCapability.AUTOMATION],
    Intent.REWRITE_TEXT.value: [AgentCapability.AUTOMATION],
    Intent.COMPARE_VERSIONS.value: [AgentCapability.AUTOMATION],
    Intent.MAP_API_TEMPLATE.value: [AgentCapability.AUTOMATION],
    Intent.RUN_DETERMINISTIC_AUDIT.value: [AgentCapability.STANDARDS_AUDIT],
    Intent.RUN_SEMANTIC_AUDIT.value: [AgentCapability.STANDARDS_AUDIT],
    Intent.CHECK_REGULATORY_COMPLIANCE.value: [AgentCapability.REGULATORY_ADVICE],
    Intent.ANALYZE_LEGAL_APPLICABILITY.value: [AgentCapability.REGULATORY_ADVICE],
    Intent.PRE_REVIEW_DOCUMENT.value: [AgentCapability.STANDARDS_AUDIT, AgentCapability.REGULATORY_ADVICE],
}


class TaskRouter:
    """
    任务路由器。
    
    根据意图分类结果和上下文，决定路由到哪些 Agent 能力组，
    以及使用哪种预定义工作流。
    """
    
    async def route(
        self,
        intent: str,
        confidence: float,
        envelope: TaskEnvelope,
        context: ContextSnapshot,
    ) -> RoutingDecision:
        # 低置信度 → 澄清
        if confidence < 0.6:
            return RoutingDecision(
                target_capabilities=[],
                workflow_version=WorkflowVersion.SINGLE_AGENT,
                needs_clarification=True,
                clarification_questions=[
                    "Could you clarify what you'd like to do? For example: "
                    "extract fields, run an audit, compare versions, or ask a question?"
                ],
                clarification_reason=f"Low classification confidence: {confidence:.2f}",
            )
        
        # 查找能力组
        capabilities = INTENT_TO_CAPABILITIES.get(intent, [AgentCapability.KNOWLEDGE])
        
        # 确定工作流版本
        workflow = self._select_workflow(capabilities, intent, context)
        
        # 验证能力在信封白名单内
        allowed = set(envelope.active_capabilities)
        filtered = [c for c in capabilities if c in allowed]
        
        if not filtered:
            logger.warning(
                f"No allowed capabilities for intent {intent}; "
                f"requested {capabilities} but allowed {allowed}"
            )
            return RoutingDecision(
                target_capabilities=[],
                workflow_version=WorkflowVersion.SINGLE_AGENT,
                needs_clarification=True,
                clarification_questions=[
                    "The requested capability is not available for this document."
                ],
                clarification_reason="Capability not in active_capabilities",
            )
        
        return RoutingDecision(
            target_capabilities=filtered,
            workflow_version=workflow,
        )
    
    def _select_workflow(
        self,
        capabilities: list[AgentCapability],
        intent: str,
        context: ContextSnapshot,
    ) -> WorkflowVersion:
        """选择预定义工作流"""
        
        # 多 Agent 并行
        if len(capabilities) > 1:
            return WorkflowVersion.PARALLEL_AUDIT
        
        # 串行管道（提取 → 审计）
        if intent == Intent.EXTRACT_FIELDS.value and context.attachments:
            return WorkflowVersion.SEQUENTIAL_PIPELINE
        
        # 澄清循环
        if intent == Intent.NEEDS_CLARIFICATION.value:
            return WorkflowVersion.CLARIFICATION_LOOP
        
        # 默认单 Agent
        return WorkflowVersion.SINGLE_AGENT
```

### 5.4 结果聚合器

```python
# orchestrator/agents/result_aggregator.py

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from orchestrator.contracts.agent_result import AgentResult, EvidenceRef, CoverageEntry
from orchestrator.contracts.context_snapshot import ContextSnapshot

logger = logging.getLogger(__name__)


@dataclass
class AggregationResult:
    findings: list[dict] = field(default_factory=list)
    answers: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    coverage_gaps: list[dict] = field(default_factory=list)
    combined_evidence: list[EvidenceRef] = field(default_factory=list)
    combined_coverage: list[CoverageEntry] = field(default_factory=list)


class ResultAggregator:
    """
    结果聚合器。
    
    职责：
    1. 合并多个 Agent 的结果
    2. 检测跨 Agent 冲突
    3. 计算覆盖矩阵
    4. 保留所有来源依赖（不仅最终引用）
    """
    
    async def aggregate(
        self,
        results: list[AgentResult],
        context: ContextSnapshot,
        target_capabilities: list[str],
    ) -> AggregationResult:
        agg = AggregationResult()
        
        if not results:
            agg.coverage_gaps.append({
                "code": "NO_RESULTS",
                "message": "No agent results to aggregate.",
                "expected_capabilities": target_capabilities,
            })
            return agg
        
        # 分类收集
        for result in results:
            if result.result_type == "answer":
                agg.answers.append(self._extract_answer_payload(result))
            elif result.result_type == "finding":
                agg.findings.append(self._extract_finding_payload(result))
            elif result.result_type == "suggestion":
                agg.suggestions.append(self._extract_suggestion_payload(result))
            
            # 收集证据
            agg.combined_evidence.extend(result.evidence_refs)
            agg.combined_coverage.extend(result.coverage)
        
        # 去重证据
        agg.combined_evidence = self._deduplicate_evidence(agg.combined_evidence)
        
        # 检测冲突
        agg.conflicts = self._detect_conflicts(results)
        
        # 计算覆盖缺口
        agg.coverage_gaps = self._compute_coverage_gaps(results, target_capabilities)
        
        return agg
    
    def _extract_answer_payload(self, result: AgentResult) -> dict:
        payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
        return {
            "agent_capability": result.agent_capability,
            "result_id": result.result_id,
            **payload,
        }
    
    def _extract_finding_payload(self, result: AgentResult) -> dict:
        payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
        return {
            "agent_capability": result.agent_capability,
            "result_id": result.result_id,
            **payload,
        }
    
    def _extract_suggestion_payload(self, result: AgentResult) -> dict:
        payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
        return {
            "agent_capability": result.agent_capability,
            "result_id": result.result_id,
            **payload,
        }
    
    def _deduplicate_evidence(self, evidence: list[EvidenceRef]) -> list[EvidenceRef]:
        """按 evidence_id 去重"""
        seen = set()
        unique = []
        for ev in evidence:
            if ev.evidence_id not in seen:
                seen.add(ev.evidence_id)
                unique.append(ev)
        return unique
    
    def _detect_conflicts(self, results: list[AgentResult]) -> list[dict]:
        """检测跨 Agent 结果冲突"""
        conflicts = []
        
        # 检查同一字段的矛盾结论
        field_values: dict[str, list[dict]] = {}
        for result in results:
            if result.result_type == "finding":
                payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
                for finding in payload.get("findings", []):
                    field_id = finding.get("field_id")
                    if field_id:
                        if field_id not in field_values:
                            field_values[field_id] = []
                        field_values[field_id].append({
                            "agent": result.agent_capability,
                            "value": finding.get("value"),
                            "severity": finding.get("severity"),
                        })
        
        for field_id, values in field_values.items():
            if len(values) > 1:
                unique_vals = set(str(v.get("value")) for v in values)
                if len(unique_vals) > 1:
                    conflicts.append({
                        "type": "field_value_conflict",
                        "field_id": field_id,
                        "agents": [v["agent"] for v in values],
                        "values": values,
                    })
        
        return conflicts
    
    def _compute_coverage_gaps(
        self,
        results: list[AgentResult],
        target_capabilities: list[str],
    ) -> list[dict]:
        """计算覆盖缺口"""
        gaps = []
        
        executed = set(r.agent_capability for r in results)
        expected = set(target_capabilities)
        
        missing = expected - executed
        for cap in missing:
            gaps.append({
                "code": "CAPABILITY_NOT_EXECUTED",
                "capability": cap,
                "message": f"Expected capability {cap} was not executed.",
            })
        
        # 检查每个 Agent 的 coverage
        for result in results:
            for entry in result.coverage:
                if entry.status in ("needs_input", "unable_to_assess", "failed"):
                    gaps.append({
                        "code": "CHECK_INCOMPLETE",
                        "check_id": entry.check_id,
                        "capability": result.agent_capability,
                        "status": entry.status,
                        "reason_codes": entry.reason_codes,
                    })
        
        return gaps
```

### 5.5 质量复核器

```python
# orchestrator/agents/quality_reviewer.py

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

from orchestrator.contracts.agent_result import AgentResult
from orchestrator.contracts.review_receipt import ReviewReceipt, ReviewIssue
from orchestrator.contracts.context_snapshot import ContextSnapshot

logger = logging.getLogger(__name__)


@dataclass
class ReviewDecision:
    decision: str  # pass / repair / abstain
    receipts: list[ReviewReceipt] = field(default_factory=list)
    issues: list[ReviewIssue] = field(default_factory=list)
    repaired_results: list[AgentResult] = field(default_factory=list)


class QualityReviewer:
    """
    质量复核器 — 独立于生成 Agent。
    
    两阶段复核：
    1. 组内复核：检查 Schema、引用、锚点、支持关系
    2. 跨组复核：检查事实冲突、适用范围、建议风险
    
    确定性工具结果由代码复核；
    包含模型推断的结果增加语义复核。
    """
    
    async def review(
        self,
        aggregated_findings: list[dict],
        aggregated_answers: list[dict],
        aggregated_suggestions: list[dict],
        agent_results: list[AgentResult],
        context: ContextSnapshot,
    ) -> ReviewDecision:
        all_issues: list[ReviewIssue] = []
        all_receipts: list[ReviewReceipt] = []
        
        # Phase 1: 逐 Agent 结果复核
        for result in agent_results:
            receipt = await self._review_single_result(result, context)
            all_receipts.append(receipt)
            all_issues.extend(receipt.issues)
        
        # Phase 2: 跨结果冲突复核
        cross_issues = self._review_cross_results(
            aggregated_findings, aggregated_answers, aggregated_suggestions
        )
        all_issues.extend(cross_issues)
        
        # 决定
        errors = [i for i in all_issues if i.code in ("citation_missing", "anchor_invalid", "unsupported_claim")]
        
        if errors:
            # 尝试修复（最多一次）
            repaired = await self._attempt_repair(agent_results, errors, context)
            if repaired:
                return ReviewDecision(
                    decision="repair",
                    receipts=all_receipts,
                    issues=all_issues,
                    repaired_results=repaired,
                )
            else:
                return ReviewDecision(
                    decision="abstain",
                    receipts=all_receipts,
                    issues=all_issues,
                )
        
        return ReviewDecision(
            decision="pass",
            receipts=all_receipts,
            issues=[],
        )
    
    async def _review_single_result(
        self,
        result: AgentResult,
        context: ContextSnapshot,
    ) -> ReviewReceipt:
        """复核单个 Agent 结果"""
        issues: list[ReviewIssue] = []
        
        # 1. Schema 校验
        schema_valid = self._validate_schema(result)
        if not schema_valid:
            issues.append(ReviewIssue(
                code="schema_violation",
                explanation=f"Result {result.result_id} does not conform to AgentResult schema.",
            ))
        
        # 2. 引用存在性
        citations_verified = True
        for evidence in result.evidence_refs:
            if not evidence.evidence_id or not evidence.source_id:
                citations_verified = False
                issues.append(ReviewIssue(
                    code="citation_missing",
                    evidence_id=evidence.evidence_id,
                    explanation=f"Evidence {evidence.evidence_id} missing source_id.",
                ))
        
        # 3. 锚点有效性
        anchors_verified = True
        if result.result_type == "finding":
            payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
            for finding in payload.get("findings", []):
                for anchor in finding.get("anchors", []):
                    if not anchor.get("quote_sha256"):
                        anchors_verified = False
                        issues.append(ReviewIssue(
                            code="anchor_invalid",
                            explanation=f"Anchor missing quote_sha256 for finding {finding.get('finding_id')}.",
                        ))
        
        # 4. Claim 支持关系
        claims_supported = True
        if result.result_type == "answer":
            payload = result.payload if isinstance(result.payload, dict) else result.payload.model_dump()
            for claim in payload.get("claims", []):
                if claim.get("kind") == "fact" and not claim.get("evidence_ids"):
                    claims_supported = False
                    issues.append(ReviewIssue(
                        code="unsupported_claim",
                        claim_id=claim.get("claim_id"),
                        explanation=f"Fact claim {claim.get('claim_id')} has no evidence_ids.",
                    ))
        
        # 5. 范围尊重
        scope_respected = self._check_scope_respected(result, context)
        if not scope_respected:
            issues.append(ReviewIssue(
                code="scope_exceeded",
                explanation=f"Result {result.result_id} accessed resources outside authorized scope.",
            ))
        
        # 6. 冲突检查
        conflicts_checked = True  # 跨结果冲突在 Phase 2 检查
        
        # 计算摘要
        result_json = result.model_dump_json()
        result_sha256 = hashlib.sha256(result_json.encode()).hexdigest()
        
        decision = "pass" if not issues else ("repair" if len(issues) <= 2 else "abstain")
        
        return ReviewReceipt(
            result_id=result.result_id,
            task_id=result.task_id,
            run_id=result.run_id,
            review_scope="in_group",
            review_strategy_version="v1",
            decision=decision,
            issues=issues,
            schema_valid=schema_valid,
            citations_verified=citations_verified,
            anchors_verified=anchors_verified,
            claims_supported=claims_supported,
            scope_respected=scope_respected,
            conflicts_checked=conflicts_checked,
            reviewer_identity="quality_reviewer_service",
            reviewer_version="1.0.0",
            input_sha256=hashlib.sha256(context.content_sha256.encode()).hexdigest(),
            result_sha256=result_sha256,
            evidence_sha256=hashlib.sha256(
                "".join(e.evidence_id for e in result.evidence_refs).encode()
            ).hexdigest(),
        )
    
    def _validate_schema(self, result: AgentResult) -> bool:
        """校验结果 Schema"""
        try:
            AgentResult.model_validate(result.model_dump())
            return True
        except Exception:
            return False
    
    def _check_scope_respected(self, result: AgentResult, context: ContextSnapshot) -> bool:
        """检查结果是否超出授权范围"""
        for dep in result.dependencies:
            if dep.get("resource_id") == context.document.document_id:
                if dep.get("version_id") != context.document.snapshot_id:
                    return False
        return True
    
    def _review_cross_results(
        self,
        findings: list[dict],
        answers: list[dict],
        suggestions: list[dict],
    ) -> list[ReviewIssue]:
        """跨结果冲突复核"""
        issues = []
        
        # 检查 findings 和 answers 的矛盾
        for finding in findings:
            for answer in answers:
                if self._contradicts(finding, answer):
                    issues.append(ReviewIssue(
                        code="conflict",
                        explanation=f"Finding from {finding.get('agent_capability')} contradicts answer from {answer.get('agent_capability')}.",
                    ))
        
        return issues
    
    def _contradicts(self, finding: dict, answer: dict) -> bool:
        """简单矛盾检测"""
        # 实际实现中需要更复杂的语义比较
        return False
    
    async def _attempt_repair(
        self,
        results: list[AgentResult],
        issues: list[ReviewIssue],
        context: ContextSnapshot,
    ) -> Optional[list[AgentResult]]:
        """尝试修复（最多一次）"""
        # 实际实现中调用模型修复或规则修复
        return None
```

### 5.6 结果发布器

```python
# orchestrator/agents/result_publisher.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from orchestrator.graph.state import OrchestratorState
from orchestrator.contracts.agent_result import AgentResult
from orchestrator.persistence.job_store import JobStore
from orchestrator.persistence.outbox import OutboxWriter

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    result: dict
    published_at: datetime


class ResultPublisher:
    """
    结果发布器 — 原子持久化。
    
    职责：
    1. 重新鉴权（发布前再次检查权限）
    2. 检查来源状态（是否已撤回）
    3. 原子写入结果 + 审计 + Outbox
    4. 使用 fencing token 防止迟到 Worker 覆盖
    """
    
    def __init__(
        self,
        job_store: JobStore,
        outbox: OutboxWriter,
        auth_service=None,
    ):
        self.job_store = job_store
        self.outbox = outbox
        self.auth_service = auth_service
    
    async def publish(self, state: OrchestratorState) -> PublishResult:
        # Step 1: 重新鉴权
        if self.auth_service:
            auth_valid = await self.auth_service.verify_access_context(
                access_context_id=state.envelope.access_context_id,
                resource_ids=[state.context.document.document_id] + [a.attachment_id for a in state.context.attachments],
            )
            if not auth_valid:
                raise PermissionError("Access context no longer valid at publish time.")
        
        # Step 2: 检查来源状态
        for evidence in state.aggregated_findings:
            for ev_ref in evidence.get("evidence_refs", []):
                if await self._is_source_withdrawn(ev_ref.get("source_id")):
                    logger.warning(f"Source {ev_ref.get('source_id')} has been withdrawn; excluding from publish")
                    # 实际实现中需要从结果中移除依赖已撤回来源的 Claim
        
        # Step 3: 构建最终结果
        final_result = self._build_final_result(state)
        
        # Step 4: 原子写入
        async with self.job_store.transaction() as tx:
            # 写入结果
            await self.job_store.persist_result(
                tx=tx,
                run_id=state.run_id,
                result=final_result,
                fencing_token=state.fencing_token,
            )
            
            # 写入审计事件
            await self.job_store.persist_audit_event(
                tx=tx,
                run_id=state.run_id,
                event_type="result_published",
                metadata={
                    "agent_capabilities": state.target_capabilities,
                    "result_count": len(state.agent_results),
                    "review_receipts": [r.receipt_id for r in state.review_receipts],
                },
            )
            
            # 写入 Outbox（异步通知）
            await self.outbox.enqueue(
                tx=tx,
                event_type="run_completed",
                payload={
                    "run_id": state.run_id,
                    "task_id": state.task_id,
                    "status": "succeeded",
                    "result_summary": self._summarize_result(final_result),
                },
            )
        
        return PublishResult(
            result=final_result,
            published_at=datetime.utcnow(),
        )
    
    def _build_final_result(self, state: OrchestratorState) -> dict:
        """构建最终输出"""
        result = {
            "run_id": state.run_id,
            "task_id": state.task_id,
            "schema_version": "1.0",
            "status": "completed",
            "published_at": datetime.utcnow().isoformat(),
        }
        
        # 聚合答案
        if state.aggregated_answers:
            result["answers"] = state.aggregated_answers
        
        # 聚合 findings
        if state.aggregated_findings:
            result["findings"] = state.aggregated_findings
        
        # 聚合 suggestions
        if state.aggregated_suggestions:
            result["suggestions"] = state.aggregated_suggestions
        
        # 冲突
        if state.conflicts:
            result["conflicts"] = state.conflicts
        
        # 覆盖缺口
        if state.coverage_gaps:
            result["limitations"] = state.coverage_gaps
        
        # 证据
        all_evidence = []
        for r in state.agent_results:
            all_evidence.extend([e.model_dump() for e in r.evidence_refs])
        if all_evidence:
            result["evidence"] = all_evidence
        
        # 复核凭据
        if state.review_receipts:
            result["review_receipts"] = [r.model_dump() for r in state.review_receipts]
        
        return result
    
    def _summarize_result(self, result: dict) -> dict:
        """生成结果摘要（用于通知）"""
        return {
            "answer_count": len(result.get("answers", [])),
            "finding_count": len(result.get("findings", [])),
            "suggestion_count": len(result.get("suggestions", [])),
            "has_conflicts": bool(result.get("conflicts")),
            "has_limitations": bool(result.get("limitations")),
        }
    
    async def _is_source_withdrawn(self, source_id: str) -> bool:
        """检查来源是否已撤回"""
        # 实际实现中查询知识来源表
        return False
```

## 6. 适配器层

### 6.1 ContextResolver — 上下文冻结器

```python
# orchestrator/adapters/context_resolver.py

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Optional

from orchestrator.contracts.task_envelope import TaskEnvelope
from orchestrator.contracts.context_snapshot import (
    ContextSnapshot,
    DocumentReference,
    AttachmentReference,
    AuthorizationContext,
)
from orchestrator.adapters.document_service import DocumentService
from orchestrator.adapters.attachment_service import AttachmentService
from orchestrator.adapters.auth_service import AuthService

logger = logging.getLogger(__name__)


class ContextResolver:
    """
    上下文冻结器 — 创建不可变快照。
    
    在任务创建时一次性冻结所有依赖版本，
    后续 Agent 执行均基于此快照，不跟随"最新"状态。
    """
    
    def __init__(
        self,
        document_service: DocumentService,
        attachment_service: AttachmentService,
        auth_service: AuthService,
    ):
        self.document_service = document_service
        self.attachment_service = attachment_service
        self.auth_service = auth_service
    
    async def freeze(
        self,
        envelope: TaskEnvelope,
        access_context_id: str,
    ) -> ContextSnapshot:
        """冻结不可变上下文快照"""
        
        # 1. 解析授权
        authorization = await self.auth_service.resolve(
            principal_user_id=envelope.actor_user_id,
            principal_org_id=envelope.actor_org_id,
            access_context_id=access_context_id,
            resource_refs={
                "workspace_id": envelope.workspace_id,
                "document_id": envelope.document_id,
                "snapshot_id": envelope.snapshot_id,
                "attachment_ids": envelope.attachment_ids,
            },
        )
        
        if not authorization:
            raise PermissionError(f"Cannot resolve access context {access_context_id}")
        
        # 2. 冻结文档快照
        doc_ref = await self.document_service.get_snapshot(
            document_id=envelope.document_id,
            snapshot_id=envelope.snapshot_id,
            access_context=authorization,
        )
        
        if not doc_ref:
            raise ValueError(f"Document snapshot {envelope.snapshot_id} not found")
        
        # 3. 冻结附件引用
        attachment_refs = []
        for att_id in envelope.attachment_ids:
            att_ref = await self.attachment_service.get_version(
                attachment_id=att_id,
                access_context=authorization,
            )
            if att_ref:
                attachment_refs.append(AttachmentReference(
                    attachment_id=att_ref.attachment_id,
                    version_id=att_ref.version_id,
                    file_sha256=att_ref.file_sha256,
                    parse_status=att_ref.parse_status,
                    page_count=att_ref.page_count,
                    ocr_pending_fields=att_ref.ocr_pending_fields,
                ))
        
        # 4. 计算内容摘要
        content_for_hash = doc_ref.content or ""
        content_sha256 = hashlib.sha256(content_for_hash.encode()).hexdigest()
        
        # 5. 构建快照
        snapshot = ContextSnapshot(
            document=doc_ref,
            attachments=attachment_refs,
            authorization=authorization,
            selection_text=None,  # 从 envelope.selection_anchor 解析
            applicable_jurisdictions=envelope.metadata.get("jurisdictions", []),
            assessment_date=datetime.utcnow().strftime("%Y-%m-%d"),
            template_version_id=envelope.metadata.get("template_version_id"),
            rule_bundle_version_ids=envelope.metadata.get("rule_bundle_version_ids", []),
            knowledge_release_id=envelope.metadata.get("knowledge_release_id"),
            frozen_at=datetime.utcnow(),
            content_sha256=content_sha256,
        )
        
        logger.info(
            f"Context frozen: snapshot={snapshot.snapshot_id}, "
            f"document={doc_ref.document_id}, attachments={len(attachment_refs)}"
        )
        
        return snapshot
```

### 6.2 宿主服务适配器接口

```python
# orchestrator/adapters/ports.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from orchestrator.contracts.context_snapshot import DocumentReference, AttachmentReference, AuthorizationContext


class DocumentServicePort(ABC):
    """文档服务端口 — 宿主实现"""
    
    @abstractmethod
    async def get_snapshot(
        self,
        document_id: str,
        snapshot_id: str,
        access_context: AuthorizationContext,
    ) -> Optional[DocumentReference]:
        """获取文档不可变快照"""
        ...
    
    @abstractmethod
    async def get_content(
        self,
        document_id: str,
        snapshot_id: str,
        access_context: AuthorizationContext,
    ) -> Optional[str]:
        """获取文档正文"""
        ...


class AttachmentServicePort(ABC):
    """附件服务端口 — 宿主实现"""
    
    @abstractmethod
    async def get_version(
        self,
        attachment_id: str,
        access_context: AuthorizationContext,
    ) -> Optional[AttachmentReference]:
        """获取附件版本"""
        ...
    
    @abstractmethod
    async def get_parsed_content(
        self,
        attachment_id: str,
        version_id: str,
        access_context: AuthorizationContext,
    ) -> Optional[dict]:
        """获取解析后的附件内容"""
        ...


class AuthServicePort(ABC):
    """身份认证服务端口 — 宿主实现"""
    
    @abstractmethod
    async def resolve(
        self,
        principal_user_id: str,
        principal_org_id: str,
        access_context_id: str,
        resource_refs: dict,
    ) -> Optional[AuthorizationContext]:
        """解析授权上下文"""
        ...
    
    @abstractmethod
    async def verify_access_context(
        self,
        access_context_id: str,
        resource_ids: list[str],
    ) -> bool:
        """验证授权上下文是否仍然有效"""
        ...


class ModelGatewayPort(ABC):
    """模型网关端口 — 可替换 LLM Provider"""
    
    @abstractmethod
    async def generate(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        output_schema: dict,
        max_tokens: int,
    ) -> dict:
        """调用 LLM 生成结构化输出"""
        ...


class RetrievalPort(ABC):
    """检索端口 — 混合检索（词法 + 向量）"""
    
    @abstractmethod
    async def search(
        self,
        query: str,
        access_context: AuthorizationContext,
        filters: dict,
        top_k: int = 20,
    ) -> list[dict]:
        """执行检索"""
        ...
```

## 7. 持久化层

### 7.1 数据库 Schema

```sql
-- orchestrator/persistence/migrations/001_initial.sql

-- 任务运行表
CREATE TABLE orchestrator_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    
    -- 主体
    actor_user_id TEXT NOT NULL,
    actor_org_id TEXT NOT NULL,
    access_context_id TEXT NOT NULL,
    
    -- 资源引用
    workspace_id TEXT NOT NULL,
    document_id TEXT,
    snapshot_id TEXT,
    
    -- 任务参数
    intent TEXT,
    target_capabilities TEXT[] NOT NULL DEFAULT '{}',
    workflow_version TEXT,
    user_message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    
    -- 预算
    budget JSONB NOT NULL,
    consumed_budget JSONB NOT NULL DEFAULT '{}',
    
    -- 状态
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 0,
    fencing_token INTEGER NOT NULL DEFAULT 0,
    
    -- 时间
    deadline_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    
    -- 结果
    result JSONB,
    error_code TEXT,
    error_message TEXT,
    
    -- 约束
    CONSTRAINT valid_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out')),
    CONSTRAINT valid_stage CHECK (stage IN ('queued', 'resolving_context', 'classifying_intent', 'routing', 'executing_agent', 'aggregating', 'reviewing', 'publishing', 'completed', 'failed', 'cancelled', 'timed_out')),
    CONSTRAINT unique_idempotency UNIQUE (idempotency_key, actor_user_id, actor_org_id)
);

CREATE INDEX idx_runs_status ON orchestrator_runs(status);
CREATE INDEX idx_runs_deadline ON orchestrator_runs(deadline_at);
CREATE INDEX idx_runs_actor ON orchestrator_runs(actor_user_id, actor_org_id);
CREATE INDEX idx_runs_workspace ON orchestrator_runs(workspace_id);

-- Agent 结果表
CREATE TABLE orchestrator_agent_results (
    result_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES orchestrator_runs(run_id),
    task_id TEXT NOT NULL,
    agent_capability TEXT NOT NULL,
    result_type TEXT NOT NULL,
    
    -- 源快照
    source_snapshot_id TEXT NOT NULL,
    source_content_sha256 TEXT NOT NULL,
    
    -- Payload
    payload JSONB NOT NULL,
    
    -- 证据与覆盖
    evidence_refs JSONB NOT NULL DEFAULT '[]',
    coverage JSONB NOT NULL DEFAULT '[]',
    limitations JSONB NOT NULL DEFAULT '[]',
    dependencies JSONB NOT NULL DEFAULT '[]',
    
    -- 执行元数据
    model_version TEXT,
    model_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tool_calls JSONB NOT NULL DEFAULT '[]',
    execution_time_ms INTEGER NOT NULL DEFAULT 0,
    
    -- 状态
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_results_run ON orchestrator_agent_results(run_id);

-- 复核凭据表
CREATE TABLE orchestrator_review_receipts (
    receipt_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL REFERENCES orchestrator_agent_results(result_id),
    run_id TEXT NOT NULL REFERENCES orchestrator_runs(run_id),
    
    review_scope TEXT NOT NULL,
    review_strategy_version TEXT NOT NULL,
    decision TEXT NOT NULL,
    issues JSONB NOT NULL DEFAULT '[]',
    
    -- 检查项
    schema_valid BOOLEAN NOT NULL,
    citations_verified BOOLEAN NOT NULL,
    anchors_verified BOOLEAN NOT NULL,
    claims_supported BOOLEAN NOT NULL,
    scope_respected BOOLEAN NOT NULL,
    conflicts_checked BOOLEAN NOT NULL,
    
    reviewer_identity TEXT NOT NULL,
    reviewer_version TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    input_sha256 TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL
);

CREATE INDEX idx_receipts_run ON orchestrator_review_receipts(run_id);
CREATE INDEX idx_receipts_result ON orchestrator_review_receipts(result_id);

-- 幂等记录表
CREATE TABLE orchestrator_idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    actor_org_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES orchestrator_runs(run_id),
    request_hash TEXT NOT NULL,
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

-- Outbox 事件表
CREATE TABLE orchestrator_outbox (
    event_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    CONSTRAINT valid_outbox_status CHECK (status IN ('pending', 'delivered', 'failed'))
);

CREATE INDEX idx_outbox_status ON orchestrator_outbox(status, created_at);

-- 审计事件表
CREATE TABLE orchestrator_audit_events (
    event_id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    run_id TEXT NOT NULL REFERENCES orchestrator_runs(run_id),
    event_type TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_run ON orchestrator_audit_events(run_id);
CREATE INDEX idx_audit_time ON orchestrator_audit_events(created_at);
```

### 7.2 JobStore — 任务持久化

```python
# orchestrator/persistence/job_store.py

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import asyncpg

from orchestrator.contracts.task_envelope import TaskEnvelope
from orchestrator.contracts.agent_result import AgentResult
from orchestrator.contracts.review_receipt import ReviewReceipt

logger = logging.getLogger(__name__)


class JobStore:
    """
    任务持久化存储。
    
    使用 PostgreSQL FOR UPDATE SKIP LOCKED 实现任务领取，
    确保同一任务不被多个 Worker 并发执行。
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    @asynccontextmanager
    async def transaction(self):
        """事务上下文管理器"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn
    
    async def create_run(
        self,
        run_id: str,
        task_id: str,
        envelope: TaskEnvelope,
    ) -> None:
        """创建任务运行记录"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_runs (
                    run_id, task_id, request_id, idempotency_key,
                    actor_user_id, actor_org_id, access_context_id,
                    workspace_id, document_id, snapshot_id,
                    intent, target_capabilities, workflow_version,
                    user_message, metadata, budget,
                    deadline_at, created_at, status, stage
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
                ON CONFLICT (idempotency_key, actor_user_id, actor_org_id) DO NOTHING
                """,
                run_id,
                task_id,
                envelope.request_id,
                envelope.idempotency_key,
                envelope.actor_user_id,
                envelope.actor_org_id,
                envelope.access_context_id,
                envelope.workspace_id,
                envelope.document_id,
                envelope.snapshot_id,
                envelope.intent,
                [c.value for c in envelope.target_capabilities],
                envelope.workflow_version.value,
                envelope.user_message,
                json.dumps(envelope.metadata),
                json.dumps(envelope.budget.model_dump()),
                envelope.deadline_at,
                envelope.created_at,
                "queued",
                "queued",
            )
    
    async def claim_run(self, run_id: str, worker_id: str) -> bool:
        """
        领取任务 — 使用 FOR UPDATE SKIP LOCKED。
        
        返回 True 表示成功领取，False 表示已被其他 Worker 领取或不存在。
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    UPDATE orchestrator_runs
                    SET status = 'running',
                        stage = 'resolving_context',
                        started_at = NOW(),
                        attempt = attempt + 1,
                        fencing_token = fencing_token + 1
                    WHERE run_id = $1
                      AND status = 'queued'
                    RETURNING fencing_token
                    """,
                    run_id,
                )
                return row is not None
    
    async def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        result: Optional[dict] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        fencing_token: Optional[int] = None,
    ) -> bool:
        """更新任务状态"""
        async with self.pool.acquire() as conn:
            fields = []
            values = []
            idx = 1
            
            if status:
                fields.append(f"status = ${idx}")
                values.append(status)
                idx += 1
            if stage:
                fields.append(f"stage = ${idx}")
                values.append(stage)
                idx += 1
            if result is not None:
                fields.append(f"result = ${idx}")
                values.append(json.dumps(result))
                idx += 1
            if error_code:
                fields.append(f"error_code = ${idx}")
                values.append(error_code)
                idx += 1
            if error_message:
                fields.append(f"error_message = ${idx}")
                values.append(error_message)
                idx += 1
            if fencing_token is not None:
                fields.append(f"fencing_token = ${idx}")
                values.append(fencing_token)
                idx += 1
            
            if status in ("succeeded", "failed", "cancelled", "timed_out"):
                fields.append(f"finished_at = ${idx}")
                values.append(datetime.utcnow())
                idx += 1
            
            values.append(run_id)
            
            query = f"UPDATE orchestrator_runs SET {', '.join(fields)} WHERE run_id = ${idx}"
            
            if fencing_token is not None:
                query += f" AND fencing_token < ${idx}"
                values.append(fencing_token)
            
            result = await conn.execute(query, *values)
            return result != "UPDATE 0"
    
    async def persist_result(
        self,
        tx,
        run_id: str,
        result: dict,
        fencing_token: int,
    ) -> None:
        """持久化最终结果（事务内）"""
        await tx.execute(
            """
            UPDATE orchestrator_runs
            SET result = $1,
                status = 'succeeded',
                stage = 'completed',
                finished_at = NOW(),
                fencing_token = $3
            WHERE run_id = $2
              AND fencing_token < $3
            """,
            json.dumps(result),
            run_id,
            fencing_token,
        )
    
    async def persist_audit_event(
        self,
        tx,
        run_id: str,
        event_type: str,
        metadata: dict,
    ) -> None:
        """持久化审计事件（事务内）"""
        await tx.execute(
            """
            INSERT INTO orchestrator_audit_events (run_id, event_type, metadata)
            VALUES ($1, $2, $3)
            """,
            run_id,
            event_type,
            json.dumps(metadata),
        )
    
    async def record_failure(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """记录失败"""
        await self.update_run(
            run_id=run_id,
            status="failed",
            error_code=error_code,
            error_message=error_message,
        )
    
    async def record_timeout(
        self,
        run_id: str,
        deadline_at: datetime,
    ) -> None:
        """记录超时"""
        await self.update_run(
            run_id=run_id,
            status="timed_out",
            error_code="TASK_TIMEOUT",
            error_message=f"Task exceeded deadline at {deadline_at.isoformat()}",
        )
    
    async def get_run(self, run_id: str) -> Optional[dict]:
        """获取任务运行记录"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM orchestrator_runs WHERE run_id = $1",
                run_id,
            )
            return dict(row) if row else None
    
    async def list_runs(
        self,
        actor_user_id: str,
        actor_org_id: str,
        status: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> list[dict]:
        """列出任务运行记录"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT * FROM orchestrator_runs
                WHERE actor_user_id = $1 AND actor_org_id = $2
            """
            params = [actor_user_id, actor_org_id]
            idx = 3
            
            if status:
                query += f" AND status = ${idx}"
                params.append(status)
                idx += 1
            
            if cursor:
                query += f" AND created_at < ${idx}"
                params.append(cursor)
                idx += 1
            
            query += f" ORDER BY created_at DESC LIMIT ${idx}"
            params.append(limit)
            
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]
```

### 7.3 OutboxWriter — 事件发件箱

```python
# orchestrator/persistence/outbox.py

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class OutboxWriter:
    """
    事件发件箱 — 确保结果发布与通知发送的原子性。
    
    在业务事务内写入事件，由后台 Worker 异步投递。
    投递失败可重试，同一事件不重复生成待办。
    """
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def enqueue(
        self,
        tx,
        event_type: str,
        payload: dict,
    ) -> str:
        """在事务内入队事件"""
        import uuid
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        
        await tx.execute(
            """
            INSERT INTO orchestrator_outbox (event_id, event_type, payload, status, created_at)
            VALUES ($1, $2, $3, 'pending', $4)
            """,
            event_id,
            event_type,
            json.dumps(payload),
            datetime.utcnow(),
        )
        
        return event_id
    
    async def deliver_pending(self, batch_size: int = 10) -> list[dict]:
        """投递待处理事件"""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT event_id, event_type, payload
                    FROM orchestrator_outbox
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                    """,
                    batch_size,
                )
                
                events = [dict(r) for r in rows]
                
                for event in events:
                    try:
                        await self._deliver(event)
                        await conn.execute(
                            """
                            UPDATE orchestrator_outbox
                            SET status = 'delivered', delivered_at = $1
                            WHERE event_id = $2
                            """,
                            datetime.utcnow(),
                            event["event_id"],
                        )
                    except Exception as e:
                        logger.error(f"Failed to deliver event {event['event_id']}: {e}")
                        await conn.execute(
                            """
                            UPDATE orchestrator_outbox
                            SET retry_count = retry_count + 1,
                                status = CASE WHEN retry_count + 1 >= 3 THEN 'failed' ELSE 'pending' END
                            WHERE event_id = $1
                            """,
                            event["event_id"],
                        )
                
                return events
    
    async def _deliver(self, event: dict) -> None:
        """投递单个事件（实际实现中调用通知服务）"""
        logger.info(f"Delivering event {event['event_id']}: {event['event_type']}")
        # 实际实现中：
        # - run_completed → 通知前端轮询结果
        # - finding_created → 推送到审计面板
        # - suggestion_ready → 推送到编辑器侧栏
```

## 8. FastAPI 端点

### 8.1 API 路由

```python
# orchestrator/api/routes.py

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field

from orchestrator.contracts.task_envelope import TaskEnvelope, TaskBudget, AgentCapability, WorkflowVersion, TaskPriority
from orchestrator.graph.orchestrator import TradeAIOrchestrator
from orchestrator.api.dependencies import get_orchestrator, get_current_user, get_idempotency_key

router = APIRouter(prefix="/api/v1/orchestrator", tags=["orchestrator"])


# ─── 请求/响应 Schema ───────────────────────────────────────────


class CreateTaskRequest(BaseModel):
    """创建任务请求"""
    workspace_id: str
    document_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=5)
    selection: Optional[dict] = None  # {node_id, start_offset, end_offset, selected_text}
    
    user_message: str = Field(min_length=1, max_length=10_000)
    target_capabilities: Optional[list[str]] = None  # 不指定时由意图分类决定
    metadata: dict = Field(default_factory=dict)
    
    priority: str = "normal"
    budget: Optional[dict] = None


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    run_id: str
    status: str
    stage: str
    created_at: str
    deadline_at: str
    poll_after_ms: int = 1000


class TaskStatusResponse(BaseModel):
    """任务状态查询响应"""
    task_id: str
    run_id: str
    status: str
    stage: str
    attempt: int
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    deadline_at: str
    result: Optional[dict] = None
    error: Optional[dict] = None


class CancelResponse(BaseModel):
    """取消响应"""
    run_id: str
    status: str
    cancelled_at: str


# ─── 端点 ───────────────────────────────────────────────────────


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: CreateTaskRequest,
    idempotency_key: str = Depends(get_idempotency_key),
    current_user: dict = Depends(get_current_user),
    orchestrator: TradeAIOrchestrator = Depends(get_orchestrator),
):
    """
    创建编排任务。
    
    返回 202 Accepted + Location header 指向状态查询端点。
    客户端按 poll_after_ms 轮询直到终态。
    """
    # 构建 TaskEnvelope
    envelope = TaskEnvelope(
        idempotency_key=idempotency_key,
        actor_user_id=current_user["user_id"],
        actor_org_id=current_user["org_id"],
        access_context_id=current_user["access_context_id"],
        active_capabilities=[AgentCapability(c) for c in current_user.get("capabilities", ["knowledge"])],
        workspace_id=request.workspace_id,
        document_id=request.document_id,
        snapshot_id=request.snapshot_id,
        selection_anchor=request.selection,
        attachment_ids=request.attachment_ids,
        intent="",  # 由分类器填充
        user_message=request.user_message,
        metadata=request.metadata,
        priority=TaskPriority(request.priority),
        budget=TaskBudget(**(request.budget or {})),
        deadline_at=datetime.utcnow() + timedelta(seconds=120),
        target_capabilities=[AgentCapability(c) for c in request.target_capabilities] if request.target_capabilities else [],
        workflow_version=WorkflowVersion.SINGLE_AGENT,
    )
    
    # 执行编排
    try:
        result = await orchestrator.execute(envelope)
        
        return TaskResponse(
            task_id=result["task_id"],
            run_id=result["run_id"],
            status=result["status"],
            stage="queued",
            created_at=envelope.created_at.isoformat(),
            deadline_at=envelope.deadline_at.isoformat(),
            poll_after_ms=1000,
        )
        
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")


@router.get("/tasks/{run_id}", response_model=TaskStatusResponse)
async def get_task_status(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    orchestrator: TradeAIOrchestrator = Depends(get_orchestrator),
):
    """
    查询任务状态。
    
    活跃任务返回进度；终态任务返回结果或错误。
    每次调用重新鉴权。
    """
    run = await orchestrator.job_store.get_run(run_id)
    
    if not run:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if run["actor_user_id"] != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="Task not found")  # 不透露存在性
    
    response = TaskStatusResponse(
        task_id=run["task_id"],
        run_id=run["run_id"],
        status=run["status"],
        stage=run["stage"],
        attempt=run["attempt"],
        created_at=run["created_at"].isoformat() if isinstance(run["created_at"], datetime) else run["created_at"],
        deadline_at=run["deadline_at"].isoformat() if isinstance(run["deadline_at"], datetime) else run["deadline_at"],
    )
    
    if run["started_at"]:
        response.started_at = run["started_at"].isoformat() if isinstance(run["started_at"], datetime) else run["started_at"]
    if run["finished_at"]:
        response.finished_at = run["finished_at"].isoformat() if isinstance(run["finished_at"], datetime) else run["finished_at"]
    
    if run["status"] == "succeeded" and run["result"]:
        response.result = run["result"]
    elif run["status"] in ("failed", "timed_out"):
        response.error = {
            "code": run.get("error_code", "UNKNOWN"),
            "message": run.get("error_message", "Unknown error"),
        }
    
    return response


@router.post("/tasks/{run_id}/cancel", response_model=CancelResponse)
async def cancel_task(
    run_id: str,
    current_user: dict = Depends(get_current_user),
    orchestrator: TradeAIOrchestrator = Depends(get_orchestrator),
):
    """
    取消任务。
    
    已终态的任务返回当前终态；未终态的任务尝试取消。
    取消不影响已保存的文档内容。
    """
    run = await orchestrator.job_store.get_run(run_id)
    
    if not run:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if run["actor_user_id"] != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if run["status"] in ("succeeded", "failed", "cancelled", "timed_out"):
        return CancelResponse(
            run_id=run_id,
            status=run["status"],
            cancelled_at=run.get("finished_at", datetime.utcnow()).isoformat() if isinstance(run.get("finished_at"), datetime) else datetime.utcnow().isoformat(),
        )
    
    # 尝试取消
    updated = await orchestrator.job_store.update_run(
        run_id=run_id,
        status="cancelled",
        stage="cancelled",
    )
    
    if not updated:
        # 可能已被 Worker 完成
        run = await orchestrator.job_store.get_run(run_id)
        return CancelResponse(
            run_id=run_id,
            status=run["status"],
            cancelled_at=run.get("finished_at", datetime.utcnow()).isoformat() if isinstance(run.get("finished_at"), datetime) else datetime.utcnow().isoformat(),
        )
    
    return CancelResponse(
        run_id=run_id,
        status="cancelled",
        cancelled_at=datetime.utcnow().isoformat(),
    )


@router.get("/tasks", response_model=list[TaskStatusResponse])
async def list_tasks(
    status_filter: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    orchestrator: TradeAIOrchestrator = Depends(get_orchestrator),
):
    """
    列出当前用户的任务。
    
    仅返回请求人有权查看的任务；不透露他人任务数量。
    """
    runs = await orchestrator.job_store.list_runs(
        actor_user_id=current_user["user_id"],
        actor_org_id=current_user["org_id"],
        status=status_filter,
        limit=min(limit, 100),
        cursor=cursor,
    )
    
    return [
        TaskStatusResponse(
            task_id=run["task_id"],
            run_id=run["run_id"],
            status=run["status"],
            stage=run["stage"],
            attempt=run["attempt"],
            created_at=run["created_at"].isoformat() if isinstance(run["created_at"], datetime) else run["created_at"],
            deadline_at=run["deadline_at"].isoformat() if isinstance(run["deadline_at"], datetime) else run["deadline_at"],
            started_at=run["started_at"].isoformat() if run.get("started_at") and isinstance(run["started_at"], datetime) else run.get("started_at"),
            finished_at=run["finished_at"].isoformat() if run.get("finished_at") and isinstance(run["finished_at"], datetime) else run.get("finished_at"),
            result=run.get("result"),
            error={"code": run.get("error_code"), "message": run.get("error_message")} if run.get("error_code") else None,
        )
        for run in runs
    ]
```

### 8.2 依赖注入

```python
# orchestrator/api/dependencies.py

from __future__ import annotations

import hashlib
import json
from typing import Optional

from fastapi import Header, HTTPException, Request

from orchestrator.graph.orchestrator import TradeAIOrchestrator
from orchestrator.adapters.context_resolver import ContextResolver
from orchestrator.adapters.document_service import DocumentService
from orchestrator.adapters.attachment_service import AttachmentService
from orchestrator.adapters.auth_service import AuthService
from orchestrator.agents.intent_classifier import IntentClassifier
from orchestrator.agents.router import TaskRouter
from orchestrator.agents.result_aggregator import ResultAggregator
from orchestrator.agents.quality_reviewer import QualityReviewer
from orchestrator.agents.result_publisher import ResultPublisher
from orchestrator.persistence.job_store import JobStore
from orchestrator.persistence.outbox import OutboxWriter


# 全局单例（实际实现中用 FastAPI Depends 注入）
_orchestrator: Optional[TradeAIOrchestrator] = None


def get_orchestrator() -> TradeAIOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        # 初始化适配器（实际实现中从配置读取）
        raise RuntimeError("Orchestrator not initialized; call init_orchestrator() first")
    return _orchestrator


async def init_orchestrator(pool, model_gateway=None):
    """初始化编排器（应用启动时调用）"""
    global _orchestrator
    
    doc_service = DocumentService()
    att_service = AttachmentService()
    auth_service = AuthService()
    
    context_resolver = ContextResolver(doc_service, att_service, auth_service)
    intent_classifier = IntentClassifier(model_gateway)
    task_router = TaskRouter()
    result_aggregator = ResultAggregator()
    quality_reviewer = QualityReviewer()
    
    job_store = JobStore(pool)
    outbox = OutboxWriter(pool)
    result_publisher = ResultPublisher(job_store, outbox, auth_service)
    
    _orchestrator = TradeAIOrchestrator(
        context_resolver=context_resolver,
        intent_classifier=intent_classifier,
        task_router=task_router,
        result_aggregator=result_aggregator,
        quality_reviewer=quality_reviewer,
        result_publisher=result_publisher,
        job_store=job_store,
    )
    
    return _orchestrator


async def get_current_user(
    authorization: Optional[str] = Header(None),
    cookie: Optional[str] = Header(None),
) -> dict:
    """
    解析当前用户。
    
    实际实现中调用宿主身份服务验证 token/session，
    返回 {user_id, org_id, access_context_id, capabilities}。
    """
    if not authorization and not cookie:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # 模拟实现
    return {
        "user_id": "user_demo_01",
        "org_id": "org_demo_01",
        "access_context_id": "ac_demo_01",
        "capabilities": ["knowledge", "automation", "standards_audit", "regulatory_advice"],
    }


async def get_idempotency_key(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> str:
    """
    解析幂等键。
    
    POST 创建类接口必须提供 Idempotency-Key header。
    键长 8-128 字符，作用域为主体 + HTTP 方法 + 路径。
    """
    if not idempotency_key:
        # 从请求体生成
        body = await request.body()
        try:
            body_json = json.loads(body)
            normalized = json.dumps(body_json, sort_keys=True, separators=(",", ":"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            normalized = body.hex()
        
        hash_input = f"{normalized}:{request.method}:{request.url.path}"
        idempotency_key = hashlib.sha256(hash_input.encode()).hexdigest()[:32]
    
    if not (8 <= len(idempotency_key) <= 128):
        raise HTTPException(status_code=422, detail="Idempotency-Key must be 8-128 characters")
    
    return idempotency_key
```

## 9. 测试策略

### 9.1 单元测试

```python
# tests/unit/test_state_machine.py

import pytest
from orchestrator.state_machine.task_states import (
    TaskStateMachine, TaskStatus, TaskStage
)


class TestTaskStateMachine:
    
    def test_valid_transition_queued_to_running(self):
        sm = TaskStateMachine(TaskStatus.QUEUED, TaskStage.QUEUED)
        assert sm.can_transition_to(TaskStatus.RUNNING)
        assert sm.transition_to(TaskStatus.RUNNING)
        assert sm.status == TaskStatus.RUNNING
    
    def test_invalid_transition_succeeded_to_running(self):
        sm = TaskStateMachine(TaskStatus.SUCCEEDED, TaskStage.COMPLETED)
        assert not sm.can_transition_to(TaskStatus.RUNNING)
        assert not sm.transition_to(TaskStatus.RUNNING)
        assert sm.status == TaskStatus.SUCCEEDED  # 未改变
    
    def test_terminal_state_no_transitions(self):
        for terminal in [TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT]:
            sm = TaskStateMachine(terminal, TaskStage.COMPLETED)
            for target in TaskStatus:
                assert not sm.can_transition_to(target)
    
    def test_fencing_token_increment(self):
        sm = TaskStateMachine(TaskStatus.QUEUED, TaskStage.QUEUED)
        assert sm.fencing_token == 0
        token1 = sm.increment_fencing_token()
        assert token1 == 1
        token2 = sm.increment_fencing_token()
        assert token2 == 2
    
    def test_stage_advance(self):
        sm = TaskStateMachine(TaskStatus.QUEUED, TaskStage.QUEUED)
        assert sm.can_advance_stage(TaskStage.RESOLVING_CONTEXT)
        assert sm.advance_stage(TaskStage.RESOLVING_CONTEXT)
        assert sm.stage == TaskStage.RESOLVING_CONTEXT
    
    def test_invalid_stage_advance(self):
        sm = TaskStateMachine(TaskStatus.QUEUED, TaskStage.QUEUED)
        assert not sm.can_advance_stage(TaskStage.EXECUTING_AGENT)  # 跳过中间阶段
```

### 9.2 集成测试

```python
# tests/integration/test_orchestrator_flow.py

import pytest
import asyncio
from datetime import datetime, timedelta

from orchestrator.graph.orchestrator import TradeAIOrchestrator
from orchestrator.contracts.task_envelope import TaskEnvelope, AgentCapability, WorkflowVersion, TaskBudget, TaskPriority
from tests.factories import make_envelope, make_context_snapshot


@pytest.mark.asyncio
class TestOrchestratorFlow:
    
    async def test_knowledge_faq_happy_path(self, orchestrator):
        """知识助手 FAQ 正常路径"""
        envelope = make_envelope(
            user_message="How do I submit a document version?",
            target_capabilities=[AgentCapability.KNOWLEDGE],
        )
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "succeeded"
        assert result["result"]["answers"][0]["outcome"] == "answered"
        assert result["result"]["answers"][0]["support_level"] in ("strong", "qualified")
    
    async def test_audit_deterministic_check(self, orchestrator):
        """规范审计确定性检查"""
        envelope = make_envelope(
            user_message="Run rules audit",
            target_capabilities=[AgentCapability.STANDARDS_AUDIT],
            metadata={"template_version_id": "tpl_demo_01"},
        )
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "succeeded"
        assert "findings" in result["result"]
        assert all(f["gate_type"] in ("advisory", "human_review", "hard_block") for f in result["result"]["findings"])
    
    async def test_parallel_audit_and_legal(self, orchestrator):
        """并行审计 + 法规检查"""
        envelope = make_envelope(
            user_message="Pre-review this document",
            target_capabilities=[AgentCapability.STANDARDS_AUDIT, AgentCapability.REGULATORY_ADVICE],
            workflow_version=WorkflowVersion.PARALLEL_AUDIT,
        )
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "succeeded"
        capabilities = set(r["agent_capability"] for r in result["result"].get("agent_results", []))
        assert AgentCapability.STANDARDS_AUDIT.value in capabilities or AgentCapability.REGULATORY_ADVICE.value in capabilities
    
    async def test_idempotent_replay(self, orchestrator):
        """幂等重放不重复创建"""
        envelope = make_envelope(idempotency_key="idem_test_001")
        
        result1 = await orchestrator.execute(envelope)
        result2 = await orchestrator.execute(envelope)  # 同一幂等键
        
        assert result1["run_id"] == result2["run_id"]
        assert result1["status"] == result2["status"]
    
    async def test_timeout_handling(self, orchestrator):
        """超时处理"""
        envelope = make_envelope(
            deadline_at=datetime.utcnow() - timedelta(seconds=1),  # 已过期
        )
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "timed_out"
        assert result["error"]["code"] == "TASK_TIMEOUT"
    
    async def test_permission_denied_on_publish(self, orchestrator):
        """发布时权限失效"""
        envelope = make_envelope()
        
        # 模拟权限在发布前被撤销
        orchestrator.auth_service.revoke_access(envelope.access_context_id)
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "failed"
        assert result["error"]["code"] == "CONTEXT_PERMISSION_DENIED"
    
    async def test_budget_exhausted(self, orchestrator):
        """预算耗尽"""
        envelope = make_envelope(
            budget=TaskBudget(max_steps=1, max_model_calls=1),
        )
        
        result = await orchestrator.execute(envelope)
        
        # 第一步就用完预算
        assert result["status"] in ("failed", "timed_out")
        assert "BUDGET" in result.get("error", {}).get("code", "")
    
    async def test_review_repair_once(self, orchestrator):
        """复核修复最多一次"""
        envelope = make_envelope()
        
        # 模拟第一次复核发现可修复问题
        orchestrator.quality_reviewer._attempt_repair = lambda *args: True
        
        result = await orchestrator.execute(envelope)
        
        assert result["status"] == "succeeded"
        assert orchestrator.quality_reviewer.repair_count <= 1
```

### 9.3 端到端测试

```python
# tests/e2e/test_full_workflow.py

import pytest
from httpx import AsyncClient

from main import app


@pytest.mark.asyncio
class TestFullWorkflow:
    
    async def test_create_task_and_poll_until_complete(self):
        """创建任务 → 轮询 → 获取结果"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 创建任务
            response = await client.post(
                "/api/v1/orchestrator/tasks",
                json={
                    "workspace_id": "ws_demo_01",
                    "document_id": "doc_demo_01",
                    "snapshot_id": "snap_demo_v3",
                    "user_message": "What is URDG 758?",
                    "priority": "normal",
                },
                headers={
                    "Authorization": "Bearer test_token",
                    "Idempotency-Key": "idem_e2e_001",
                },
            )
            
            assert response.status_code == 202
            task = response.json()
            run_id = task["run_id"]
            
            # 轮询直到终态
            max_polls = 30
            for _ in range(max_polls):
                status_resp = await client.get(
                    f"/api/v1/orchestrator/tasks/{run_id}",
                    headers={"Authorization": "Bearer test_token"},
                )
                assert status_resp.status_code == 200
                status_data = status_resp.json()
                
                if status_data["status"] in ("succeeded", "failed", "cancelled", "timed_out"):
                    break
                
                await asyncio.sleep(1)
            
            assert status_data["status"] == "succeeded"
            assert "result" in status_data
            assert status_data["result"]["answers"][0]["outcome"] == "answered"
    
    async def test_cancel_running_task(self):
        """取消运行中的任务"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 创建一个耗时任务
            response = await client.post(
                "/api/v1/orchestrator/tasks",
                json={
                    "workspace_id": "ws_demo_01",
                    "user_message": "Analyze all regulatory requirements for this document",
                    "target_capabilities": ["standards_audit", "regulatory_advice"],
                },
                headers={"Authorization": "Bearer test_token"},
            )
            
            run_id = response.json()["run_id"]
            
            # 取消
            cancel_resp = await client.post(
                f"/api/v1/orchestrator/tasks/{run_id}/cancel",
                headers={"Authorization": "Bearer test_token"},
            )
            
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "cancelled"
    
    async def test_unauthorized_access_returns_404(self):
        """未授权访问返回 404（不透露存在性）"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/orchestrator/tasks/nonexistent_run",
                headers={"Authorization": "Bearer other_user_token"},
            )
            
            assert response.status_code == 404
```

## 10. 部署与运维

### 10.1 启动配置

```python
# orchestrator/main.py

import asyncio
import logging
import os

import asyncpg
from fastapi import FastAPI
from contextlib import asynccontextmanager

from orchestrator.api.routes import router
from orchestrator.api.dependencies import init_orchestrator
from orchestrator.adapters.model_gateway import ModelGateway

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost/openspec")
    pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
    
    model_gateway = ModelGateway(
        provider=os.getenv("MODEL_PROVIDER", "mock"),
        api_key=os.getenv("MODEL_API_KEY"),
    )
    
    orchestrator = await init_orchestrator(pool, model_gateway)
    app.state.orchestrator = orchestrator
    app.state.pool = pool
    
    # 启动后台任务
    outbox_worker = asyncio.create_task(run_outbox_worker(pool))
    timeout_reaper = asyncio.create_task(run_timeout_reaper(pool))
    
    logger.info("Orchestrator started")
    
    yield
    
    # 关闭时清理
    outbox_worker.cancel()
    timeout_reaper.cancel()
    await pool.close()
    logger.info("Orchestrator stopped")


async def run_outbox_worker(pool):
    """Outbox 事件投递 Worker"""
    from orchestrator.persistence.outbox import OutboxWriter
    writer = OutboxWriter(pool)
    
    while True:
        try:
            await writer.deliver_pending(batch_size=10)
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Outbox worker error: {e}")
            await asyncio.sleep(5)


async def run_timeout_reaper(pool):
    """超时任务收割者"""
    while True:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE orchestrator_runs
                    SET status = 'timed_out',
                        stage = 'timed_out',
                        finished_at = NOW(),
                        error_code = 'TASK_TIMEOUT',
                        error_message = 'Task exceeded deadline'
                    WHERE status IN ('queued', 'running')
                      AND deadline_at < NOW()
                    """
                )
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Timeout reaper error: {e}")
            await asyncio.sleep(30)


app = FastAPI(
    title="TradeAI Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### 10.2 Docker 部署

```dockerfile
# Dockerfile

FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY orchestrator/ ./orchestrator/
COPY bin/ ./bin/

EXPOSE 8000

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml

version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: orchestrator
      POSTGRES_USER: orchestrator
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./orchestrator/persistence/migrations:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
  
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  
  orchestrator:
    build: .
    environment:
      DATABASE_URL: postgresql://orchestrator:${DB_PASSWORD}@postgres/orchestrator
      REDIS_URL: redis://redis:6379
      MODEL_PROVIDER: ${MODEL_PROVIDER}
      MODEL_API_KEY: ${MODEL_API_KEY}
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  postgres_data:
```

## 11. 验收标准

| 验证点 | 验收证据 |
|--------|---------|
| 路由正确性 | FAQ 只启动知识助手；确定性 Diff 不调用模型；模糊请求返回澄清 |
| 权限隔离 | 外部用户无法读取内部来源；入队后撤权不发布结果 |
| 幂等性 | 同一幂等键重试只生成一个结果；不同请求同键返回 409 |
| 超时处理 | 超过 deadline 的任务自动标记 timed_out；迟到 Worker 结果不覆盖 |
| 预算控制 | 子任务不超出父任务预算；模型调用次数/Token 可追踪 |
| 质量复核 | 伪造引用不发布；无证据 Claim 被拦截；冲突被标记 |
| 原子发布 | 结果 + 审计 + Outbox 同事务写入；失败可重试 |
| 可观测性 | 每个 run 可追溯至输入、证据、模型版本、人工动作 |

## 12. 后续工作

1. **Agent Worker 实现** — KnowledgeWorker, AutomationWorker, AuditWorker, LegalWorker
2. **并行执行** — 使用 asyncio.gather 同时运行多个 Agent
3. **LangGraph 持久化** — 集成 PostgresSaver 实现断点续传
4. **模型网关** — 实现 ModelGatewayPort 的具体 Provider（OpenAI, Anthropic, etc.）
5. **宿主集成** — 实现 DocumentServicePort, AttachmentServicePort, AuthServicePort
6. **前端集成** — 编辑器侧栏轮询任务状态、展示结果
7. **性能测试** — 100 并发用户下的 P95 延迟
8. **安全审计** — 权限隔离测试、注入测试

---

**文档状态**: v0.1 待评审
**下一步**: 团队评审 → 冻结规格 → 开始编码实现
