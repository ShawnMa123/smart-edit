"""Contracts for the server-side automation registry: templates → variables → dispatch.

`/automation/templates*` and `/automation/dispatches*` use these; the browser workbench keeps its
local snapshot store, and this registry is the shared, durable path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.automation.schemas import Strict

VariableType = Literal["string", "amount", "date", "currency", "integer", "boolean"]
VariableSource = Literal["deterministic", "llm", "manual"]
TemplateSourceKind = Literal["preset", "imported", "edited"]
ConnectorAuth = Literal["none", "bearer", "header"]
DispatchStatus = Literal["succeeded", "failed", "refused"]


class TemplateVariable(Strict):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    value_type: VariableType = "string"
    required: bool = False
    # Evidence in the template: a verbatim quote plus its code-point range (never invented).
    quote: str | None = Field(default=None, max_length=500)
    start: int | None = None
    end: int | None = None
    sample_value: str | None = Field(default=None, max_length=200)
    source: VariableSource = "manual"


class TemplateCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=200_000)
    content: dict[str, Any] | None = None
    source_kind: TemplateSourceKind = "imported"
    source_note: str | None = Field(default=None, max_length=200)
    document_id: str | None = Field(default=None, max_length=128)
    # NULL = organisation-level; `dept_admin` can only create/read its own department's rows.
    department_id: str | None = Field(default=None, max_length=128)


class TemplateVariablesUpdate(Strict):
    variables: list[TemplateVariable] = Field(default_factory=list, max_length=40)


class TemplateUpdate(Strict):
    """Rename a stored template (the version stays; the next save continues from the new name)."""

    name: str = Field(min_length=1, max_length=120)


class TemplateDuplicate(Strict):
    name: str | None = Field(default=None, max_length=120)


class TemplateApplyRequest(Strict):
    """Render the template into a NEW document, filling the confirmed variables."""

    title: str | None = Field(default=None, max_length=200)
    values: dict[str, str] = Field(default_factory=dict)


class TemplateApplyResult(Strict):
    document_id: str
    draft_id: str | None = None
    title: str
    text_chars: int
    filled: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)


class TemplateBindRequest(Strict):
    """Bind an existing document to a template (the `template_name` key automatic rules match)."""

    template_id: str = Field(min_length=1, max_length=128)


class DocumentTemplateView(Strict):
    document_id: str
    template_id: str | None = None
    template_name: str | None = None


class TemplateWriteBackRequest(Strict):
    """Write the confirmed values into the CURRENT draft (needs the editor's lock + revision)."""

    document_id: str = Field(min_length=1, max_length=128)
    draft_id: str = Field(min_length=1, max_length=128)
    lock_id: str = Field(min_length=1, max_length=128)
    fencing_token: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    values: dict[str, str] = Field(default_factory=dict)


class TemplateWriteBackResult(Strict):
    document_id: str
    draft_id: str
    revision: int
    applied: dict[str, str] = Field(default_factory=dict)
    # Variables with a value that the draft never mentions (the label is missing there).
    skipped: list[str] = Field(default_factory=list)


class TemplateView(Strict):
    template_id: str
    name: str
    version: str
    source_kind: str
    source_note: str | None = None
    document_id: str | None = None
    text_chars: int
    variables: list[TemplateVariable] = Field(default_factory=list)
    variables_source: str | None = None
    created_by: str
    created_at: str
    updated_at: str
    department_id: str | None = None


class SuggestionView(Strict):
    template_id: str
    variables: list[TemplateVariable] = Field(default_factory=list)
    suggested_by: Literal["deterministic", "llm", "merged"]
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PrepareRequest(Strict):
    document_id: str | None = Field(default=None, max_length=128)
    text: str | None = Field(default=None, max_length=200_000)
    # When the target system has an OpenAPI spec, its request body is built here for preview.
    connector_id: str | None = Field(default=None, max_length=128)


class BoundValue(Strict):
    value: str | None = None
    quote: str | None = None
    source: Literal["document", "missing"] = "missing"


class BodyIssue(Strict):
    path: str
    reason: Literal["missing", "invalid", "unsupported"]
    message: str


class PreparedPayload(Strict):
    template_id: str
    template_name: str
    template_version: str
    document_id: str | None = None
    values: dict[str, BoundValue] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_required: list[str] = Field(default_factory=list)
    # Spec-driven request body (present only when a connector with an OpenAPI spec is selected).
    connector_id: str | None = None
    content_type: str | None = None
    request_body: dict[str, Any] | None = None
    body_mapping: dict[str, str] = Field(default_factory=dict)
    body_issues: list[BodyIssue] = Field(default_factory=list)
    unmapped_required: list[str] = Field(default_factory=list)


class SpecFieldView(Strict):
    path: str
    type: str
    required: bool = False
    enum: list[str] = Field(default_factory=list)
    unsupported: str | None = None


class SpecOperationView(Strict):
    id: str
    method: str
    path: str
    operation_id: str | None = None
    summary: str | None = None
    content_type: str | None = None
    available: bool = False
    fields: list[SpecFieldView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SpecParseRequest(Strict):
    spec: dict[str, Any]


class SpecParseResult(Strict):
    title: str
    version: str
    operations: list[SpecOperationView] = Field(default_factory=list)


class SpecBuildRequest(Strict):
    """Stateless body assembly for the sandbox preview (no connector, nothing persisted)."""

    spec: dict[str, Any]
    operation: str = Field(min_length=1, max_length=200)
    mapping: dict[str, str] = Field(default_factory=dict)
    values: dict[str, str] = Field(default_factory=dict)


class SpecBuildResult(Strict):
    operation: str
    body: dict[str, Any] = Field(default_factory=dict)
    mapping: dict[str, str] = Field(default_factory=dict)
    issues: list[BodyIssue] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    invalid: list[str] = Field(default_factory=list)
    ready: bool = False


class FieldDefinition(Strict):
    """A hand-written request field, for downstreams that publish no OpenAPI document."""

    path: str = Field(min_length=1, max_length=120)
    type: Literal["string", "number", "integer", "boolean"] = "string"
    required: bool = False


class DispatchPreview(Strict):
    """What dispatch *would* do — no HTTP call, no receipt."""

    url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
    content_type: str | None = None
    operation: str | None = None
    schema_kind: Literal["openapi", "fields", "flat"] = "flat"
    issues: list[BodyIssue] = Field(default_factory=list)
    refusal: str | None = None


class ConnectorCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    path: str = Field(default="/", max_length=300)
    method: Literal["POST", "PUT", "PATCH"] = "POST"
    auth_kind: ConnectorAuth = "none"
    auth_header: str | None = Field(default=None, max_length=80)
    # The NAME of an environment variable; the value never enters the database or a response.
    secret_env: str | None = Field(default=None, max_length=120)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    # Optional OpenAPI 3.x JSON document + the operation whose request body the dispatch must match.
    spec: dict[str, Any] | None = None
    operation: str | None = Field(default=None, max_length=200)
    body_map: dict[str, str] = Field(default_factory=dict)
    # Downstreams without an OpenAPI document: hand-written request fields (mutually exclusive).
    fields: list[FieldDefinition] | None = Field(default=None, max_length=40)
    # NULL = organisation-level; `dept_admin` can only create/read its own department's rows.
    department_id: str | None = Field(default=None, max_length=128)


class MappingUpdate(Strict):
    """`{OpenAPI field path: template variable key}` for one connector (and optionally one template)."""

    body_map: dict[str, str] = Field(default_factory=dict)
    # When set, the mapping is stored for this (template, connector) pair instead of the connector.
    template_id: str | None = Field(default=None, max_length=128)


class MappingView(Strict):
    template_id: str
    connector_id: str
    body_map: dict[str, str] = Field(default_factory=dict)
    # False = never configured for this pair (the server falls back to suggestions).
    configured: bool = False


class ConnectorUpdate(Strict):
    """Partial update: only the fields present are changed; the spec may be replaced wholesale."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    path: str | None = Field(default=None, max_length=300)
    method: Literal["POST", "PUT", "PATCH"] | None = None
    auth_kind: ConnectorAuth | None = None
    auth_header: str | None = Field(default=None, max_length=80)
    secret_env: str | None = Field(default=None, max_length=120)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    extra_headers: dict[str, str] | None = None
    spec: dict[str, Any] | None = None
    operation: str | None = Field(default=None, max_length=200)
    fields: list[FieldDefinition] | None = Field(default=None, max_length=40)


class ConnectorSpecView(Strict):
    """The stored document itself, fetched on demand so list responses stay small."""

    connector_id: str
    operation: str | None = None
    spec: dict[str, Any] = Field(default_factory=dict)


class ConnectorView(Strict):
    connector_id: str
    name: str
    base_url: str
    path: str
    method: str
    auth_kind: str
    auth_header: str | None = None
    secret_env: str | None = None
    secret_configured: bool = False
    timeout_seconds: int
    extra_headers: dict[str, str] = Field(default_factory=dict)
    created_at: str
    disabled_at: str | None = None
    # OpenAPI contract, when one is attached.
    spec_title: str | None = None
    spec_version: str | None = None
    operation: str | None = None
    operation_method: str | None = None
    operation_path: str | None = None
    content_type: str | None = None
    request_fields: list[SpecFieldView] = Field(default_factory=list)
    body_map: dict[str, str] = Field(default_factory=dict)
    spec_warnings: list[str] = Field(default_factory=list)
    spec_error: str | None = None
    department_id: str | None = None
    # "openapi" (attached document) · "fields" (hand-written) · "flat" (no contract)
    schema_kind: Literal["openapi", "fields", "flat"] = "flat"
    fields: list[FieldDefinition] = Field(default_factory=list)


class DispatchRequest(Strict):
    template_id: str = Field(min_length=1, max_length=128)
    connector_id: str = Field(min_length=1, max_length=128)
    document_id: str | None = Field(default=None, max_length=128)
    # Automatic jobs pass the approved submission snapshot instead of a live draft.
    text: str | None = Field(default=None, max_length=200_000)
    values: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=120)


class DispatchReceipt(Strict):
    dispatch_id: str
    template_id: str | None = None
    connector_id: str
    document_id: str | None = None
    status: DispatchStatus
    status_code: int | None = None
    latency_ms: int | None = None
    request: dict[str, Any] = Field(default_factory=dict)
    response_excerpt: str | None = None
    error_code: str | None = None
    created_at: str
    # Automatic-dispatch linkage (empty for a manual send).
    job_id: str | None = None
    rule_id: str | None = None
    trigger: str | None = None
    submission_id: str | None = None


class DispatchPage(Strict):
    items: list[DispatchReceipt] = Field(default_factory=list)


class TemplatePage(Strict):
    items: list[TemplateView] = Field(default_factory=list)


class ConnectorPage(Strict):
    items: list[ConnectorView] = Field(default_factory=list)


__all__ = [
    "BodyIssue",
    "BoundValue",
    "ConnectorAuth",
    "ConnectorCreate",
    "ConnectorPage",
    "ConnectorSpecView",
    "ConnectorUpdate",
    "ConnectorView",
    "DispatchPage",
    "DispatchReceipt",
    "DispatchRequest",
    "DispatchPreview",
    "DispatchStatus",
    "FieldDefinition",
    "MappingUpdate",
    "MappingView",
    "PreparedPayload",
    "PrepareRequest",
    "SpecBuildRequest",
    "SpecBuildResult",
    "SpecFieldView",
    "SpecOperationView",
    "SpecParseRequest",
    "SpecParseResult",
    "SuggestionView",
    "TemplateApplyRequest",
    "TemplateApplyResult",
    "TemplateCreate",
    "TemplateDuplicate",
    "TemplatePage",
    "TemplateUpdate",
    "TemplateVariable",
    "TemplateVariablesUpdate",
    "TemplateView",
    "TemplateWriteBackRequest",
    "TemplateWriteBackResult",
    "VariableSource",
    "VariableType",
]