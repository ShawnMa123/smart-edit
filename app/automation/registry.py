"""Server-side automation registry: templates → variables → downstream dispatch.

Why this exists: the workbench's template store is browser-local (`localStorage`) and its downstream
send is simulated. For "identify variables in a user template and call another system" we need one
durable, org-scoped registry plus a controlled outbound call:

- templates and their confirmed variables live in the host database (shared across browsers/users);
- variable *suggestions* come from a deterministic pass and optionally Doubao, but a suggestion is
  never saved automatically: the user confirms it, and every suggestion carries a verbatim quote;
- dispatch renders a payload from confirmed values and performs one HTTP call to an allow-listed
  connector. Secrets are read from the server environment by name, never stored or echoed.

The deterministic pass is what makes the feature usable without a model (and testable): placeholders
(`{{label}}`), blank fills (`____`) and `Label: value` lines whose value looks like an amount, date,
currency or identifier.
"""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.automation.openapi import (
    MAX_SPEC_BYTES,
    OpenApiSpec,
    SpecError,
    SpecOperation,
    build_body,
    operation_from_fields,
    parse_spec,
    suggest_mapping,
)
from app.automation.registry_schemas import (
    BodyIssue,
    DispatchPreview,
    FieldDefinition,
    BoundValue,
    ConnectorCreate,
    ConnectorSpecView,
    ConnectorUpdate,
    ConnectorView,
    DispatchReceipt,
    DispatchRequest,
    MappingUpdate,
    MappingView,
    PreparedPayload,
    PrepareRequest,
    SpecBuildRequest,
    SpecBuildResult,
    SpecFieldView,
    SpecOperationView,
    SpecParseResult,
    SuggestionView,
    TemplateApplyRequest,
    TemplateApplyResult,
    TemplateCreate,
    TemplateDuplicate,
    TemplateUpdate,
    TemplateVariable,
    TemplateVariablesUpdate,
    TemplateView,
    TemplateWriteBackRequest,
    TemplateWriteBackResult,
)
from app.documents.errors import HostError, HostNotFound
from app.documents.schemas import DocumentCreate, DraftSave
from app.documents.store import HostStore, new_id, now_iso
from app.shared.ports import Principal

MAX_TEMPLATE_VARIABLES = 40
MAX_TEXT_CHARS = 200_000
MAX_RESPONSE_EXCERPT = 2000
DEFAULT_ALLOWED_ENV = "SMART_EDIT_AUTOMATION_ALLOWED_HOSTS"
ALLOW_HTTP_ENV = "SMART_EDIT_AUTOMATION_ALLOW_HTTP"


@functools.lru_cache(maxsize=64)
def _parse_cached(spec_json: str) -> OpenApiSpec:
    """Parsing is pure over the stored text, so cache by document (specs are read on every render)."""
    return parse_spec(json.loads(spec_json))


def _fields_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("fields_json")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _render_text_node(
    text: str, variables: list[TemplateVariable], values: dict[str, str], applied: set[str]
) -> str:
    """Replace placeholders and `Label:` values inside one text node; record what actually matched.

    Matching is what counts, not changing: a value identical to the one already in the draft still means
    the label exists, so it must not be reported as "not found in the draft".
    """
    rendered = text
    for variable in variables:
        value = (values.get(variable.key) or "").strip()
        if not value:
            continue
        matched = False
        for label in {variable.label, variable.key, variable.label.replace(" ", "_")}:
            if not label:
                continue
            escaped = re.escape(label)
            rendered, hits_a = re.subn(
                r"\{\{\s*" + escaped + r"\s*\}\}", lambda _m, v=value: v, rendered, flags=re.I
            )
            rendered, hits_b = re.subn(
                r"\[\[\s*" + escaped + r"\s*\]\]", lambda _m, v=value: v, rendered, flags=re.I
            )
            matched = matched or bool(hits_a or hits_b)
        line = re.compile(
            r"^([ \t]*" + re.escape(variable.label) + r"[ \t]*[:：][ \t]*).*$", re.I | re.M
        )
        rendered, hits_line = line.subn(lambda match, v=value: match.group(1) + v, rendered)
        if matched or hits_line:
            applied.add(variable.key)
    return rendered


def _spec_of(row: dict[str, Any]) -> tuple[OpenApiSpec | None, str | None]:
    raw = row.get("spec_json")
    if not raw:
        return None, None
    try:
        return _parse_cached(raw), None
    except (SpecError, ValueError) as error:  # a stored spec that no longer parses is inert
        return None, str(error)

SYSTEM_PROMPT = """You receive a document template (a guarantee, contract or letter). Identify the
fields that change from transaction to transaction: party names, amounts, currencies, dates,
identifiers, addresses, percentages, quantities.

Answer with JSON only:
{"variables": [{
  "label": "guarantee_amount",
  "value_type": "string | amount | date | currency | integer | boolean",
  "required": true,
  "quote": "verbatim text from the template that shows the field",
  "why": "why it varies per transaction"
}]}

Rules:
- `quote` must be copied verbatim from the template text. Never paraphrase it.
- Do not invent fields that are not represented in the template.
- Prefer snake_case machine labels; at most 30 variables.
- If a field looks fixed for this template (e.g. a governing-law clause), do not list it.
"""

_PLACEHOLDER = re.compile(r"\{\{\s*([^{}\n]{1,60})\s*\}\}|\[\[\s*([^\[\]\n]{1,60})\s*\]\]")
_BLANK = re.compile(r"(?:_{3,}|…{3,}|\.{4,})")
_LABELLED_LINE = re.compile(r"^[ \t]*([^:：\n]{1,40})[ \t]*[:：][ \t]*(.+?)[ \t]*$", re.M)
_AMOUNT = re.compile(
    r"(?i)(?:\b(?:USD|EUR|GBP|CNY|RMB|HKD|JPY|SGD|AUD|CHF)\b\s*[\d][\d,，.]*|"
    r"\d[\d,，.]*\s*(?:元|美元|欧元))"
)
_DATE = re.compile(
    r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|20\d{2}\s*年\s*\d{1,2}\s*月"
)
_CURRENCY = re.compile(r"(?i)\b(?:USD|EUR|GBP|CNY|RMB|HKD|JPY|SGD|AUD|CHF)\b|美元|欧元|人民币|港元|日元")
_IDENTIFIER = re.compile(r"\b[A-Z]{1,6}[-/]?\d{3,}[-A-Z0-9]*\b|\b\d{6,}\b")
_INTEGER = re.compile(r"^\d{1,9}$")

_AMOUNT_WORDS = ("amount", "sum", "value", "金额")
_CURRENCY_WORDS = ("currency", "ccy", "币种", "货币")
_DATE_WORDS = ("date", "expiry", "expiration", "valid", "validity", "日期", "失效", "到期", "开立", "签发")
_COUNT_WORDS = ("count", "quantity", "qty", "number of", "数量")
_REQUIRED_LABELS = {
    "applicant",
    "applicant name",
    "beneficiary",
    "beneficiary name",
    "amount",
    "guarantee amount",
    "currency",
    "issue date",
    "expiry date",
    "expiry",
    "guarantee number",
    "contract value",
    "seller",
    "buyer",
    "申请人",
    "受益人",
    "金额",
    "保函金额",
    "币种",
    "开立日期",
    "失效日期",
    "保函编号",
    "合同金额",
    "卖方",
    "买方",
}
_PROSE_HINTS = ("。", "，", "；", " shall ", " must ", " will ", " hereby ")


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug:
        return fallback
    if slug[0].isdigit():
        slug = f"v_{slug}"
    return slug[:64]


_STEM_TOKENS = ("name", "date", "no", "number", "ref", "reference", "code", "value", "id")


def _stem(key: str) -> str:
    """`applicant_name` → `applicant`: the noun a model and a regex may spell differently."""
    parts = [part for part in key.split("_") if part]
    while len(parts) > 1 and parts[-1] in _STEM_TOKENS:
        parts.pop()
    while len(parts) > 1 and parts[0] in _STEM_TOKENS:
        parts.pop(0)
    return "_".join(parts)


def _mentions(haystack: str, words: tuple[str, ...]) -> bool:
    """Whole-word match for ASCII hints (`country` must not match `count`), substring for CJK."""
    for word in words:
        if word.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", haystack):
                return True
        elif word in haystack:
            return True
    return False


def _infer_type(label: str, sample: str | None) -> str:
    haystack = f"{label} {sample or ''}".lower()
    if _mentions(haystack, _CURRENCY_WORDS):
        return "currency"
    if _mentions(haystack, _AMOUNT_WORDS):
        return "amount"
    if _mentions(haystack, _DATE_WORDS):
        return "date"
    if _mentions(haystack, _COUNT_WORDS):
        return "integer"
    if sample:
        if _AMOUNT.search(sample):
            return "amount"
        if _DATE.search(sample):
            return "date"
        if _CURRENCY.fullmatch(sample.strip()):
            return "currency"
        if _INTEGER.fullmatch(sample.strip()):
            return "integer"
    return "string"


def _required(label: str) -> bool:
    return label.strip().lower() in _REQUIRED_LABELS


def _flexible(quote: str, text: str) -> re.Match[str] | None:
    parts = (quote or "").split()
    if not parts:
        return None
    return re.search(r"\s+".join(re.escape(part) for part in parts), text, re.IGNORECASE)


def _looks_like_value(label: str, value: str) -> bool:
    if not value or len(value) > 160:
        return False
    lowered = value.lower()
    if any(hint in lowered for hint in _PROSE_HINTS) and len(value.split()) > 6:
        return False
    if _AMOUNT.search(value) or _DATE.search(value) or _IDENTIFIER.search(value):
        return True
    if _CURRENCY.fullmatch(value.strip()) or _INTEGER.fullmatch(value.strip()):
        return True
    # Short proper nouns ("Alpha Tech Pte Ltd", "上海远洋贸易有限公司") are plausible values.
    return len(value.split()) <= 6 and len(value) <= 80 and not label.strip().isdigit()


def detect_variables(text: str, *, limit: int = MAX_TEMPLATE_VARIABLES) -> list[TemplateVariable]:
    """Deterministic candidate variables: placeholders, blanks and `Label: value` lines."""
    body = text or ""
    found: list[TemplateVariable] = []
    seen: set[str] = set()

    for index, match in enumerate(_PLACEHOLDER.finditer(body), start=1):
        label = (match.group(1) or match.group(2) or "").strip()
        key = _slug(label, f"field_{index}")
        if key in seen:
            continue
        seen.add(key)
        found.append(
            TemplateVariable(
                key=key,
                label=label or key.replace("_", " "),
                value_type=_infer_type(label or key, None),
                required=_required(label or key),
                quote=match.group(0),
                start=match.start(),
                end=match.end(),
                source="deterministic",
            )
        )
        if len(found) >= limit:
            return found

    blank_index = 0
    for match in _BLANK.finditer(body):
        blank_index += 1
        key = f"field_{blank_index}"
        if key in seen:
            continue
        seen.add(key)
        found.append(
            TemplateVariable(
                key=key,
                label=f"field {blank_index}",
                value_type="string",
                required=False,
                quote=match.group(0),
                start=match.start(),
                end=match.end(),
                source="deterministic",
            )
        )
        if len(found) >= limit:
            return found

    for match in _LABELLED_LINE.finditer(body):
        label = match.group(1).strip().lstrip("#-* ").strip()
        value = match.group(2).strip()
        if len(label) < 2 or label.isdigit() or not _looks_like_value(label, value):
            continue
        if _PLACEHOLDER.search(value) or _BLANK.search(value):
            # `Supplier: {{supplier_name}}` — the placeholder pass already captured this field.
            continue
        key = _slug(label, f"field_{len(found) + 1}")
        if key in seen:
            continue
        seen.add(key)
        found.append(
            TemplateVariable(
                key=key,
                label=label,
                value_type=_infer_type(label, value),
                required=_required(label),
                quote=match.group(0).strip(),
                start=match.start(),
                end=match.end(),
                sample_value=value,
                source="deterministic",
            )
        )
        if len(found) >= limit:
            break
    return found


class AutomationRegistry:
    """Templates, confirmed variables, connectors and dispatches for one workspace."""

    def __init__(
        self,
        store: HostStore,
        *,
        documents: Any = None,
        gateway: Any = None,
        approved: bool = False,
        model_label: str | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.store = store
        self.documents = documents
        self.gateway = gateway
        self.approved = bool(approved)
        self.model_label = model_label
        self.timeout = float(timeout)

    # --- access -----------------------------------------------------------------------------
    @staticmethod
    def _require(principal: Principal, capability: str) -> None:
        if not principal.has(capability):
            raise HostError(403, "capability_denied", f"the principal lacks {capability}")

    @staticmethod
    def _workspace(principal: Principal) -> str:
        workspace = (principal.workspace_id or "").strip()
        if not workspace:
            raise HostError(403, "workspace_required", "the principal has no active workspace")
        return workspace

    def _llm_available(self) -> bool:
        return self.approved and callable(getattr(self.gateway, "compose_json", None))

    # --- templates --------------------------------------------------------------------------
    @staticmethod
    def _view(row: dict[str, Any]) -> TemplateView:
        variables = [
            TemplateVariable.model_validate(item)
            for item in json.loads(row.get("variables_json") or "[]")
        ]
        return TemplateView(
            template_id=row["template_id"],
            name=row["name"],
            version=row["version"],
            source_kind=row["source_kind"],
            source_note=row.get("source_note"),
            document_id=row.get("document_id"),
            text_chars=len(row.get("text") or ""),
            variables=variables,
            variables_source=row.get("variables_source"),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_templates(self, principal: Principal) -> list[TemplateView]:
        self._require(principal, "read")
        rows = self.store.all(
            "SELECT * FROM automation_templates WHERE workspace_id = ? ORDER BY created_at DESC",
            (self._workspace(principal),),
        )
        return [self._view(row) for row in rows]

    def _template_row(self, principal: Principal, template_id: str) -> dict[str, Any]:
        row = self.store.one(
            "SELECT * FROM automation_templates WHERE template_id = ? AND workspace_id = ?",
            (template_id, self._workspace(principal)),
        )
        if row is None:
            raise HostNotFound("automation template not found")
        return row

    def get_template(self, principal: Principal, template_id: str) -> TemplateView:
        self._require(principal, "read")
        return self._view(self._template_row(principal, template_id))

    def _next_version(self, workspace: str, name: str) -> str:
        latest = self.store.one(
            "SELECT version FROM automation_templates WHERE workspace_id = ? AND name = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (workspace, name),
        )
        if latest is None:
            return "1.0.0"
        parts = str(latest["version"]).split(".")
        try:
            patch = int(parts[-1]) + 1
        except (TypeError, ValueError):
            patch = 1
        base = ".".join(parts[:-1]) or "1.0"
        return f"{base}.{patch}"

    def create_template(self, principal: Principal, request: TemplateCreate) -> TemplateView:
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        text = request.text.strip()
        if not text:
            raise HostError(400, "empty_template", "the template has no text")
        if len(text) > MAX_TEXT_CHARS:
            raise HostError(
                400, "template_too_large", f"the template exceeds {MAX_TEXT_CHARS} characters"
            )
        version = self._next_version(workspace, request.name.strip())
        template_id = new_id("tpl")
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_templates (template_id, workspace_id, name, version, "
                "source_kind, source_note, text, content_json, variables_json, variables_source, "
                "document_id, created_by, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    template_id,
                    workspace,
                    request.name.strip(),
                    version,
                    request.source_kind,
                    request.source_note,
                    text,
                    json.dumps(request.content, ensure_ascii=False) if request.content else None,
                    "[]",
                    None,
                    request.document_id,
                    principal.user_id,
                    stamp,
                    stamp,
                ),
            )
        return self.get_template(principal, template_id)

    def _llm_variables(
        self, text: str, *, locale: str = "en"
    ) -> tuple[list[TemplateVariable], list[str]]:
        raw = self.gateway.compose_json(
            SYSTEM_PROMPT,
            {"template_text": text[:12000], "locale": locale},
            timeout=self.timeout,
        )
        items = raw.get("variables") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            raise ValueError("no variables list")
        out: list[TemplateVariable] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(items[:30], start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:80]
            if not label:
                continue
            key = _slug(label, f"field_{index}")
            if key in seen:
                continue
            seen.add(key)
            value_type = str(item.get("value_type") or "string").strip().lower()
            if value_type not in ("string", "amount", "date", "currency", "integer", "boolean"):
                value_type = "string"
            quote = str(item.get("quote") or "").strip()[:500]
            match = _flexible(quote, text) if quote else None
            if quote and match is None:
                warnings.append(f"quote_not_found:{label}")
            out.append(
                TemplateVariable(
                    key=key,
                    label=label,
                    value_type=value_type,  # type: ignore[arg-type]
                    required=bool(item.get("required")),
                    quote=quote if match else None,
                    start=match.start() if match else None,
                    end=match.end() if match else None,
                    source="llm",
                )
            )
        return out, warnings

    @staticmethod
    def _merge(
        deterministic: list[TemplateVariable], llm: list[TemplateVariable]
    ) -> list[TemplateVariable]:
        """One field per fact: the model may refine a field, never re-name the same one.

        Deterministic evidence wins (it was read off the template, not guessed). A model variable is
        folded into an existing one when it shares the key, shares the key stem (`applicant_name`
        vs `applicant`), or points at the same span of text (`guarantee_amount` quoting the
        `Amount:` line). Anything else is a genuine addition.
        """
        merged = [item.model_copy() for item in deterministic]
        by_key = {item.key: item for item in merged}
        by_stem = {_stem(item.key): item for item in merged}
        spans = [
            (item.start, item.end, item)
            for item in merged
            if item.start is not None and item.end is not None
        ]

        def absorb(existing: TemplateVariable, item: TemplateVariable) -> None:
            if existing.value_type == "string" and item.value_type != "string":
                existing.value_type = item.value_type  # type: ignore[assignment]
            if item.required and not existing.required:
                existing.required = True

        for item in llm:
            existing = by_key.get(item.key) or by_stem.get(_stem(item.key))
            if existing is not None:
                absorb(existing, item)
                continue
            if item.start is not None and item.end is not None:
                overlapping = next(
                    (cand for start, end, cand in spans if item.start < end and start < item.end),
                    None,
                )
                if overlapping is not None:
                    absorb(overlapping, item)
                    continue
            merged.append(item)
            by_key[item.key] = item
            by_stem.setdefault(_stem(item.key), item)
            if item.start is not None and item.end is not None:
                spans.append((item.start, item.end, item))
        return merged[:MAX_TEMPLATE_VARIABLES]

    def suggest_variables(
        self, principal: Principal, template_id: str, *, use_llm: bool = True
    ) -> SuggestionView:
        """Deterministic candidates + optional Doubao pass. Never persists; the user confirms."""
        self._require(principal, "read")
        row = self._template_row(principal, template_id)
        base = detect_variables(row["text"])
        warnings: list[str] = []
        llm: list[TemplateVariable] = []
        if use_llm:
            if not self._llm_available():
                warnings.append("llm_unavailable")
            else:
                try:
                    llm, llm_warnings = self._llm_variables(row["text"])
                    warnings.extend(llm_warnings)
                except Exception as exc:  # noqa: BLE001 - suggestion failure must not 500
                    warnings.append(f"llm_error:{type(exc).__name__}")
        merged = self._merge(base, llm)
        if llm and base:
            suggested_by = "merged"
        elif llm:
            suggested_by = "llm"
        else:
            suggested_by = "deterministic"
        return SuggestionView(
            template_id=template_id,
            variables=merged,
            suggested_by=suggested_by,  # type: ignore[arg-type]
            model=self.model_label if llm else None,
            warnings=list(dict.fromkeys(warnings))[:10],
        )

    def save_variables(
        self, principal: Principal, template_id: str, update: TemplateVariablesUpdate
    ) -> TemplateView:
        """Persist the confirmed set. Suggestions are never saved without this call."""
        self._require(principal, "apply")
        row = self._template_row(principal, template_id)
        keys = [item.key for item in update.variables]
        if len(set(keys)) != len(keys):
            raise HostError(400, "duplicate_variable_key", "variable keys must be unique")
        payload = [item.model_dump() for item in update.variables]
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_templates SET variables_json = ?, variables_source = ?, "
                "updated_at = ? WHERE template_id = ?",
                (json.dumps(payload, ensure_ascii=False), "manual", now_iso(), row["template_id"]),
            )
        return self.get_template(principal, template_id)

    # --- template lifecycle (rename / duplicate / delete) -------------------------------------
    def rename_template(
        self, principal: Principal, template_id: str, update: TemplateUpdate
    ) -> TemplateView:
        """Rename one stored version. History keeps the name it was dispatched under."""
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        row = self._template_row(principal, template_id)
        name = update.name.strip()
        if not name:
            raise HostError(400, "invalid_name", "the template name cannot be empty")
        clash = self.store.one(
            "SELECT template_id FROM automation_templates WHERE workspace_id = ? AND name = ? "
            "AND version = ? AND template_id <> ?",
            (workspace, name, row["version"], template_id),
        )
        if clash is not None:
            raise HostError(409, "name_taken", f"`{name}` version {row['version']} already exists")
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_templates SET name = ?, updated_at = ? WHERE template_id = ?",
                (name, now_iso(), template_id),
            )
        return self.get_template(principal, template_id)

    def duplicate_template(
        self, principal: Principal, template_id: str, request: TemplateDuplicate
    ) -> TemplateView:
        """Copy a template (text + confirmed variables) under a new name."""
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        row = self._template_row(principal, template_id)
        name = (request.name or f"{row['name']} (copy)").strip()[:120] or "Untitled template"
        version = self._next_version(workspace, name)
        new_template_id = new_id("tpl")
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_templates (template_id, workspace_id, name, version, "
                "source_kind, source_note, text, content_json, variables_json, variables_source, "
                "document_id, created_by, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_template_id,
                    workspace,
                    name,
                    version,
                    "preset",
                    f"copied from {row['name']} v{row['version']}",
                    row["text"],
                    row.get("content_json"),
                    row.get("variables_json") or "[]",
                    row.get("variables_source"),
                    None,
                    principal.user_id,
                    stamp,
                    stamp,
                ),
            )
        return self.get_template(principal, new_template_id)

    def delete_template(self, principal: Principal, template_id: str) -> None:
        """Hard delete one template version. Dispatch receipts keep their own snapshot."""
        self._require(principal, "apply")
        self._template_row(principal, template_id)
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM automation_templates WHERE template_id = ?", (template_id,))

    # --- apply (template → new document) ------------------------------------------------------
    @staticmethod
    def _render_template(
        text: str, variables: list[TemplateVariable], values: dict[str, str]
    ) -> tuple[str, dict[str, str]]:
        """Fill `{{label}}` / `[[label]]` / `Label: value`; only matched fields count as filled."""
        applied: set[str] = set()
        rendered = _render_text_node(text, variables, values, applied)
        return rendered, {key: values[key] for key in sorted(applied)}

    def apply_template(
        self, principal: Principal, template_id: str, request: TemplateApplyRequest
    ) -> TemplateApplyResult:
        """Render the template into a NEW document — the other direction of the automation."""
        self._require(principal, "apply")
        if self.documents is None:
            raise HostError(409, "document_host_unavailable", "this server cannot create documents")
        row = self._template_row(principal, template_id)
        template = self._view(row)
        values = {key: str(value) for key, value in request.values.items()}
        rendered, filled = self._render_template(row["text"], template.variables, values)
        missing = [
            item.key for item in template.variables if item.required and item.key not in filled
        ]
        title = (request.title or template.name)[:200]
        created = self.documents.create_document(
            principal, DocumentCreate(title=title, text=rendered), new_id("reqauto")
        )
        return TemplateApplyResult(
            document_id=str(created.get("document_id")),
            draft_id=created.get("draft_id"),
            title=str(created.get("title") or title),
            text_chars=len(rendered),
            filled=filled,
            missing=missing,
        )

    @staticmethod
    def _render_content(
        node: Any, variables: list[TemplateVariable], values: dict[str, str], applied: set[str]
    ) -> Any:
        """Replace placeholders and `Label:` values inside the rich document, keeping the structure.

        Only text nodes change; marks, headings, tables and unknown nodes survive untouched.
        """
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for key, value in node.items():
                if key == "text" and isinstance(value, str):
                    result[key] = _render_text_node(value, variables, values, applied)
                else:
                    result[key] = AutomationRegistry._render_content(
                        value, variables, values, applied
                    )
            return result
        if isinstance(node, list):
            return [
                AutomationRegistry._render_content(item, variables, values, applied)
                for item in node
            ]
        return node

    def write_back(
        self, principal: Principal, template_id: str, request: TemplateWriteBackRequest
    ) -> TemplateWriteBackResult:
        """Apply the values to the current draft under the caller's lock and revision."""
        self._require(principal, "read")
        if self.documents is None:
            raise HostError(409, "document_host_unavailable", "this server cannot edit drafts")
        template = self._view(self._template_row(principal, template_id))
        current = self.documents.view(principal, request.document_id, request.draft_id)
        values = {key: str(value) for key, value in request.values.items()}
        applied: set[str] = set()
        rendered = self._render_content(current["content"], template.variables, values, applied)
        if not applied:
            return TemplateWriteBackResult(
                document_id=str(current["document_id"]),
                draft_id=str(current["draft_id"]),
                revision=int(current["revision"]),
                applied={},
                skipped=sorted(key for key, value in values.items() if value.strip()),
            )
        saved = self.documents.save_draft(
            principal,
            request.document_id,
            request.draft_id,
            request.expected_revision,
            DraftSave(
                content=rendered,
                lock_id=request.lock_id,
                fencing_token=request.fencing_token,
            ),
            new_id("reqwb"),
        )
        return TemplateWriteBackResult(
            document_id=str(saved["document_id"]),
            draft_id=str(saved["draft_id"]),
            revision=int(saved["revision"]),
            applied={key: values[key] for key in sorted(applied)},
            skipped=sorted(key for key, value in values.items() if value.strip() and key not in applied),
        )

    # --- stateless spec helpers (sandbox preview) ------------------------------------------------
    @staticmethod
    def _view_operation(operation: SpecOperation) -> SpecOperationView:
        return SpecOperationView(
            id=operation.id,
            method=operation.method,
            path=operation.path,
            operation_id=operation.operation_id,
            summary=operation.summary,
            content_type=operation.content_type,
            available=operation.available,
            fields=[
                SpecFieldView(
                    path=item.path,
                    type=item.type,
                    required=item.required,
                    enum=item.enum,
                    unsupported=item.unsupported,
                )
                for item in operation.fields
            ],
            warnings=list(operation.warnings),
        )

    def parse_contract(self, principal: Principal, document: dict[str, Any]) -> SpecParseResult:
        """Parse an OpenAPI document with the same code the registry uses (no connector needed)."""
        self._require(principal, "read")
        encoded = json.dumps(document, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_SPEC_BYTES:
            raise HostError(
                413, "spec_too_large", f"the OpenAPI document exceeds {MAX_SPEC_BYTES} bytes"
            )
        try:
            spec = parse_spec(document)
        except SpecError as error:
            raise HostError(400, "invalid_spec", str(error)) from error
        return SpecParseResult(
            title=spec.title,
            version=spec.version,
            operations=[self._view_operation(item) for item in spec.operations],
        )

    def build_contract_body(self, principal: Principal, request: SpecBuildRequest) -> SpecBuildResult:
        """Assemble a request body for a spec + mapping, without persisting anything."""
        self._require(principal, "read")
        parsed = self.parse_contract(principal, request.spec)
        operation = next((item for item in parsed.operations if item.id == request.operation), None)
        if operation is None:
            raise HostError(400, "operation_not_found", f"`{request.operation}` is not in the spec")
        spec = parse_spec(request.spec)
        raw = spec.operation(request.operation)
        assert raw is not None
        built = build_body(raw, request.mapping, request.values)
        return SpecBuildResult(
            operation=operation.id,
            body=built.body,
            mapping=built.mapping,
            issues=[BodyIssue(**item) for item in built.issues],
            missing=built.missing,
            invalid=built.invalid,
            ready=built.ready,
        )

    # --- prepare (template + draft → values) ------------------------------------------------
    def _document_text(self, principal: Principal, document_id: str) -> str:
        if self.documents is None:
            raise HostError(409, "document_host_unavailable", "this server cannot read drafts")
        view = self.documents.document_view(principal, document_id)
        return str(view.get("text") or "")

    @staticmethod
    def _value_in_text(variable: TemplateVariable, text: str) -> tuple[str | None, str | None]:
        """Find `label: value` in the draft. Only the label is matched; values are never invented."""
        label = variable.label.strip()
        candidates = [label]
        if "_" in label:
            candidates.append(label.replace("_", " "))
        if " " in label:
            candidates.append(label.replace(" ", "_"))
        # Placeholder labels are often snake_case nouns (`applicant_name`), while the draft uses the
        # short label (`Applicant:`). Longest tokens first so "amount" wins over "guarantee" noise.
        tokens = sorted(
            (token for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", label) if len(token) >= 4),
            key=len,
            reverse=True,
        )
        candidates.extend(tokens)
        for candidate in dict.fromkeys(item for item in candidates if item):
            pattern = re.compile(rf"{re.escape(candidate)}\s*[:：]\s*([^\n]{{1,200}})", re.I)
            match = pattern.search(text)
            if match:
                return match.group(1).strip(), match.group(0).strip()
        return None, None

    def prepare(
        self, principal: Principal, template_id: str, request: PrepareRequest
    ) -> PreparedPayload:
        """Bind confirmed variables to a draft. Missing values are reported, not guessed."""
        self._require(principal, "read")
        row = self._template_row(principal, template_id)
        template = self._view(row)
        if request.document_id:
            text = self._document_text(principal, request.document_id)
        elif request.text is not None:
            text = request.text
        else:
            raise HostError(400, "no_input", "provide document_id or text")
        values: dict[str, BoundValue] = {}
        for variable in template.variables:
            value, quote = self._value_in_text(variable, text)
            values[variable.key] = BoundValue(
                value=value, quote=quote, source="document" if value else "missing"
            )
        missing = [
            variable.key
            for variable in template.variables
            if variable.required and not values.get(variable.key, BoundValue()).value
        ]
        payload = {
            "template": {
                "template_id": template.template_id,
                "name": template.name,
                "version": template.version,
            },
            "values": {key: item.value for key, item in values.items() if item.value is not None},
            "document_id": request.document_id,
            "source": "smart-edit",
        }
        request_body, body_mapping, body_issues, unmapped, content_type = self._spec_body(
            principal, template.template_id, request.connector_id, template.variables, values
        )
        return PreparedPayload(
            template_id=template.template_id,
            template_name=template.name,
            template_version=template.version,
            document_id=request.document_id,
            values=values,
            payload=payload,
            missing_required=missing,
            connector_id=request.connector_id,
            content_type=content_type,
            request_body=request_body,
            body_mapping=body_mapping,
            body_issues=body_issues,
            unmapped_required=unmapped,
        )

    def _pair_mapping(
        self, workspace: str, template_id: str, connector_id: str
    ) -> dict[str, str] | None:
        """The stored mapping for one (template, connector) pair; `None` = never configured."""
        row = self.store.one(
            "SELECT body_map_json FROM automation_mappings WHERE template_id = ? "
            "AND connector_id = ? AND workspace_id = ?",
            (template_id, connector_id, workspace),
        )
        if row is None:
            return None
        try:
            parsed = json.loads(row.get("body_map_json") or "{}")
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def mapping(self, principal: Principal, template_id: str, connector_id: str) -> MappingView:
        """Read the pair mapping (configured=False → the panel should use suggestions)."""
        self._require(principal, "read")
        self._template_row(principal, template_id)  # 404 when the template is gone
        stored = self._pair_mapping(self._workspace(principal), template_id, connector_id)
        return MappingView(
            template_id=template_id,
            connector_id=connector_id,
            body_map=stored or {},
            configured=stored is not None,
        )

    def _spec_body(
        self,
        principal: Principal,
        template_id: str,
        connector_id: str | None,
        variables: list[TemplateVariable],
        values: dict[str, BoundValue],
    ) -> tuple[dict[str, Any] | None, dict[str, str], list[BodyIssue], list[str], str | None]:
        """The downstream's own request body for these values, or `None` when it has no contract."""
        if not connector_id:
            return None, {}, [], [], None
        target = self._contract_target(principal, connector_id)
        if target is None:
            return None, {}, [], [], None
        row, operation = target
        allowed = {item.path for item in operation.fields if not item.unsupported}
        pair = self._pair_mapping(self._workspace(principal), template_id, connector_id)
        if pair is not None:
            # Configured for this pair (possibly deliberately empty): send exactly that.
            mapping = {path: key for path, key in pair.items() if path in allowed}
        elif int(row.get("body_map_configured") or 0):
            # Legacy connector-wide mapping from before pair mappings existed.
            stored = json.loads(row.get("body_map_json") or "{}")
            mapping = {path: key for path, key in stored.items() if path in allowed}
        else:
            # Never configured: propose by label so the panel opens with a usable body.
            mapping = suggest_mapping(operation, [(item.key, item.label) for item in variables])
        built = build_body(operation, mapping, {key: item.value for key, item in values.items()})
        issues = [BodyIssue(**item) for item in built.issues]
        return built.body, built.mapping, issues, built.missing, operation.content_type

    def _contract_target(
        self, principal: Principal, connector_id: str
    ) -> tuple[dict[str, Any], SpecOperation] | None:
        """The operation a connector dispatches against: an OpenAPI one or the hand-written fields."""
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ?",
            (connector_id, self._workspace(principal)),
        )
        if row is None:
            raise HostNotFound("automation connector not found")
        spec, _ = _spec_of(row)
        if spec is not None:
            operation = spec.operation(row.get("operation"))
            return (row, operation) if operation is not None else None
        hand_fields = _fields_of(row)
        if hand_fields:
            return row, operation_from_fields(
                hand_fields, method=row["method"], path=row["path"]
            )
        return None

    # --- connectors -------------------------------------------------------------------------
    @staticmethod
    def _connector_view(row: dict[str, Any]) -> ConnectorView:
        secret_env = row.get("secret_env")
        spec, spec_error = _spec_of(row)
        hand_fields = _fields_of(row)
        schema_kind = "openapi" if spec is not None else "fields" if hand_fields else "flat"
        operation: SpecOperation | None = None
        if spec is not None:
            operation = spec.operation(row.get("operation"))
            if row.get("operation") and operation is None:
                spec_error = f"operation `{row.get('operation')}` is not in the attached spec"
        elif hand_fields:
            operation = operation_from_fields(
                hand_fields, method=row["method"], path=row["path"]
            )
        fields = (
            [
                SpecFieldView(
                    path=item.path,
                    type=item.type,
                    required=item.required,
                    enum=item.enum,
                    unsupported=item.unsupported,
                )
                for item in operation.fields
            ]
            if operation is not None
            else []
        )
        return ConnectorView(
            connector_id=row["connector_id"],
            name=row["name"],
            base_url=row["base_url"],
            path=row["path"],
            method=row["method"],
            auth_kind=row["auth_kind"],
            auth_header=row.get("auth_header"),
            secret_env=secret_env,
            secret_configured=bool(secret_env and os.environ.get(secret_env)),
            timeout_seconds=int(row["timeout_seconds"]),
            extra_headers=json.loads(row.get("extra_headers_json") or "{}"),
            created_at=row["created_at"],
            disabled_at=row.get("disabled_at"),
            spec_title=spec.title if spec is not None else None,
            spec_version=spec.version if spec is not None else None,
            operation=operation.id if operation is not None else None,
            operation_method=operation.method if operation is not None else None,
            operation_path=operation.path if operation is not None else None,
            content_type=operation.content_type if operation is not None else None,
            request_fields=fields,
            body_map=json.loads(row.get("body_map_json") or "{}"),
            spec_warnings=list(operation.warnings) if operation is not None else [],
            spec_error=spec_error,
            schema_kind=schema_kind,  # type: ignore[arg-type]
            fields=[FieldDefinition(**item) for item in hand_fields] if hand_fields else [],
        )

    def list_connectors(self, principal: Principal) -> list[ConnectorView]:
        self._require(principal, "read")
        rows = self.store.all(
            "SELECT * FROM automation_connectors WHERE workspace_id = ? AND disabled_at IS NULL "
            # Oldest first: the first registered system stays the panel's default target, so adding a
            # new connector cannot silently re-point the next send.
            "ORDER BY created_at ASC, connector_id ASC",
            (self._workspace(principal),),
        )
        return [self._connector_view(row) for row in rows]

    @staticmethod
    def _validate_transport(
        *, base_url: str, auth_kind: str, auth_header: str | None, secret_env: str | None
    ) -> None:
        parsed = urlparse(base_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HostError(400, "invalid_base_url", "base_url must be an http(s) URL with a host")
        if parsed.username or parsed.password:
            raise HostError(
                400,
                "credentials_in_url",
                "put credentials in an environment variable, not in the URL",
            )
        if auth_kind == "bearer" and not secret_env:
            raise HostError(400, "secret_env_required", "bearer auth needs secret_env")
        if auth_kind == "header" and not (auth_header and secret_env):
            raise HostError(400, "secret_env_required", "header auth needs auth_header and secret_env")
        if auth_header and not re.fullmatch(r"[A-Za-z0-9-]{1,80}", auth_header):
            raise HostError(400, "invalid_auth_header", "auth_header must be a simple header name")

    @staticmethod
    def _validated_spec(
        request: ConnectorCreate, path: str
    ) -> tuple[str | None, str | None, str | None, dict[str, str] | None, str, str]:
        """Validate the declared contract.

        Returns `(spec_json, fields_json, operation_id, body_map, method, path)`. An OpenAPI document
        owns the method and path; hand-written fields keep the connector's own method and path.
        """
        if request.spec is not None and request.fields:
            raise HostError(
                400,
                "schema_conflict",
                "attach either an OpenAPI document or hand-written fields, not both",
            )

        if request.spec is None and not request.fields:
            if request.operation or request.body_map:
                raise HostError(
                    400,
                    "spec_required",
                    "attach an OpenAPI document or fields before choosing an operation",
                )
            return None, None, None, None, request.method, path

        if request.spec is None:
            hand_fields = [item.model_dump() for item in request.fields or []]
            seen: set[str] = set()
            for item in hand_fields:
                item_path = str(item["path"]).strip()
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", item_path):
                    raise HostError(
                        400,
                        "invalid_field_path",
                        f"`{item_path}` must be dotted names like `beneficiary.name`",
                    )
                if item_path in seen:
                    raise HostError(400, "duplicate_field_path", f"`{item_path}` is declared twice")
                seen.add(item_path)
                item["path"] = item_path
            operation = operation_from_fields(hand_fields, method=request.method, path=path)
            allowed = {item.path for item in operation.fields}
            unknown = sorted(set(request.body_map) - allowed)
            if unknown:
                raise HostError(
                    400,
                    "unknown_field_path",
                    f"not in {operation.id}: {', '.join(unknown[:5])}",
                )
            return (
                None,
                json.dumps(hand_fields, ensure_ascii=False),
                operation.id,
                dict(request.body_map) if request.body_map else None,
                request.method,
                path,
            )

        encoded = json.dumps(request.spec, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_SPEC_BYTES:
            raise HostError(
                413, "spec_too_large", f"the OpenAPI document exceeds {MAX_SPEC_BYTES} bytes"
            )
        try:
            spec = parse_spec(request.spec)
        except SpecError as error:
            raise HostError(400, "invalid_spec", str(error)) from error

        operation = spec.operation(request.operation) if request.operation else None
        if request.operation and operation is None:
            raise HostError(400, "operation_not_found", f"`{request.operation}` is not in the spec")
        operation = operation or spec.default_operation()
        if operation is None:
            raise HostError(
                400, "operation_not_found", "the spec has no operation with a JSON request body"
            )
        if not operation.available:
            raise HostError(
                400,
                "operation_unusable",
                f"{operation.id} has no application/json request body with scalar fields",
            )

        allowed = {item.path for item in operation.fields if not item.unsupported}
        unknown = sorted(set(request.body_map) - allowed)
        if unknown:
            raise HostError(
                400,
                "unknown_field_path",
                f"not in {operation.id}: {', '.join(unknown[:5])}",
            )

        # The spec wins for method and path; an explicit non-default path is still honoured.
        spec_path = operation.path
        final_path = spec_path if path in ("/", "") else path
        return (
            encoded,
            None,
            operation.id,
            dict(request.body_map) if request.body_map else None,
            operation.method,
            final_path,
        )

    def set_mapping(
        self, principal: Principal, connector_id: str, update: MappingUpdate
    ) -> ConnectorView:
        """Persist which template variable fills which field of the downstream's request body.

        With `template_id`, the mapping belongs to that (template, connector) pair — one connector can
        therefore serve several templates without their mappings overwriting each other.
        """
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ?",
            (connector_id, workspace),
        )
        if row is None:
            raise HostNotFound("automation connector not found")
        spec, _ = _spec_of(row)
        operation = spec.operation(row.get("operation")) if spec else None
        if operation is None and _fields_of(row):
            operation = operation_from_fields(
                _fields_of(row), method=row["method"], path=row["path"]
            )
        if operation is None:
            raise HostError(
                409, "spec_required", "this connector has no OpenAPI document or fields attached"
            )
        allowed = {item.path for item in operation.fields if not item.unsupported}
        unknown = sorted(set(update.body_map) - allowed)
        if unknown:
            raise HostError(400, "unknown_field_path", f"not in {operation.id}: {', '.join(unknown[:5])}")
        if update.template_id:
            self._template_row(principal, update.template_id)  # 404 when the template is gone
            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT INTO automation_mappings (template_id, connector_id, workspace_id, "
                    "body_map_json, updated_at) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(template_id, connector_id) DO UPDATE SET "
                    "body_map_json = excluded.body_map_json, updated_at = excluded.updated_at",
                    (
                        update.template_id,
                        connector_id,
                        workspace,
                        json.dumps(update.body_map, ensure_ascii=False),
                        now_iso(),
                    ),
                )
        else:
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE automation_connectors SET body_map_json = ?, body_map_configured = 1, "
                    "updated_at = ? WHERE connector_id = ?",
                    (json.dumps(update.body_map, ensure_ascii=False), now_iso(), connector_id),
                )
        refreshed = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ?", (connector_id,)
        )
        assert refreshed is not None
        return self._connector_view(refreshed)

    def create_connector(self, principal: Principal, request: ConnectorCreate) -> ConnectorView:
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        self._validate_transport(
            base_url=request.base_url,
            auth_kind=request.auth_kind,
            auth_header=request.auth_header,
            secret_env=request.secret_env,
        )
        path = request.path if request.path.startswith("/") else f"/{request.path}"
        spec_json, fields_json, operation_id, body_map, method, path = self._validated_spec(
            request, path
        )
        connector_id = new_id("con")
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_connectors (connector_id, workspace_id, name, base_url, "
                "method, path, auth_kind, auth_header, secret_env, timeout_seconds, "
                "extra_headers_json, spec_json, fields_json, operation, body_map_json, "
                "body_map_configured, created_by, created_at, updated_at, disabled_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    connector_id,
                    workspace,
                    request.name.strip(),
                    request.base_url.strip().rstrip("/"),
                    method,
                    path,
                    request.auth_kind,
                    request.auth_header,
                    request.secret_env,
                    request.timeout_seconds,
                    json.dumps(request.extra_headers, ensure_ascii=False),
                    spec_json,
                    fields_json,
                    operation_id,
                    json.dumps(body_map, ensure_ascii=False) if body_map is not None else "{}",
                    1 if body_map is not None else 0,
                    principal.user_id,
                    stamp,
                    stamp,
                    None,
                ),
            )
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ?", (connector_id,)
        )
        assert row is not None
        return self._connector_view(row)

    def update_connector(
        self, principal: Principal, connector_id: str, patch: ConnectorUpdate
    ) -> ConnectorView:
        """Change an existing target in place. Replacing the spec (or its operation) resets the mapping,
        because the old field paths belong to the old contract."""
        self._require(principal, "apply")
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ? "
            "AND disabled_at IS NULL",
            (connector_id, self._workspace(principal)),
        )
        if row is None:
            raise HostNotFound("automation connector not found")

        base_url = (patch.base_url or row["base_url"]).strip().rstrip("/")
        auth_kind = patch.auth_kind or row["auth_kind"]
        auth_header = patch.auth_header if patch.auth_header is not None else row.get("auth_header")
        secret_env = patch.secret_env if patch.secret_env is not None else row.get("secret_env")
        self._validate_transport(
            base_url=base_url,
            auth_kind=auth_kind,
            auth_header=auth_header,
            secret_env=secret_env,
        )

        existing_spec = json.loads(row["spec_json"]) if row.get("spec_json") else None
        spec_doc = patch.spec if patch.spec is not None else existing_spec
        spec_changed = (
            patch.spec is not None
            or patch.fields is not None
            or (patch.operation is not None and patch.operation != row.get("operation"))
        )
        request = ConnectorCreate(
            name=(patch.name or row["name"]).strip(),
            base_url=base_url,
            path=patch.path or row["path"],
            method=patch.method or "POST",
            auth_kind=auth_kind,  # type: ignore[arg-type]
            auth_header=auth_header,
            secret_env=secret_env,
            timeout_seconds=patch.timeout_seconds or int(row["timeout_seconds"]),
            extra_headers=(
                patch.extra_headers
                if patch.extra_headers is not None
                else json.loads(row.get("extra_headers_json") or "{}")
            ),
            spec=spec_doc,
            fields=patch.fields,
            # A replaced contract invalidates the old operation id, so fall back to its default.
            operation=patch.operation or (None if spec_changed else row.get("operation")),
            body_map={} if spec_changed else json.loads(row.get("body_map_json") or "{}"),
        )
        spec_json, fields_json, operation_id, body_map, method, path = self._validated_spec(
            request, "/" if spec_changed else request.path
        )
        configured = 0 if spec_changed else int(row.get("body_map_configured") or 0)
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_connectors SET name = ?, base_url = ?, method = ?, path = ?, "
                "auth_kind = ?, auth_header = ?, secret_env = ?, timeout_seconds = ?, "
                "extra_headers_json = ?, spec_json = ?, fields_json = ?, operation = ?, "
                "body_map_json = ?, body_map_configured = ?, updated_at = ? "
                "WHERE connector_id = ?",
                (
                    request.name,
                    base_url,
                    method,
                    path,
                    auth_kind,
                    auth_header,
                    secret_env,
                    request.timeout_seconds,
                    json.dumps(request.extra_headers, ensure_ascii=False),
                    spec_json,
                    fields_json,
                    operation_id,
                    json.dumps(body_map or {}, ensure_ascii=False),
                    configured,
                    now_iso(),
                    connector_id,
                ),
            )
        refreshed = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ?", (connector_id,)
        )
        assert refreshed is not None
        return self._connector_view(refreshed)

    def disable_connector(self, principal: Principal, connector_id: str) -> ConnectorView:
        """Soft delete: the row and its receipts stay for audit; dispatch can no longer use it."""
        self._require(principal, "apply")
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ? "
            "AND disabled_at IS NULL",
            (connector_id, self._workspace(principal)),
        )
        if row is None:
            raise HostNotFound("automation connector not found")
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE automation_connectors SET disabled_at = ?, updated_at = ? "
                "WHERE connector_id = ?",
                (stamp, stamp, connector_id),
            )
        row["disabled_at"] = stamp
        return self._connector_view(row)

    def connector_spec(self, principal: Principal, connector_id: str) -> ConnectorSpecView:
        """The stored OpenAPI document, so the editor can re-load it without a round trip to disk."""
        self._require(principal, "read")
        row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ?",
            (connector_id, self._workspace(principal)),
        )
        if row is None:
            raise HostNotFound("automation connector not found")
        spec = json.loads(row["spec_json"]) if row.get("spec_json") else {}
        return ConnectorSpecView(
            connector_id=connector_id, operation=row.get("operation"), spec=spec
        )

    # --- dispatch ---------------------------------------------------------------------------
    @staticmethod
    def _allowed_hosts() -> set[str]:
        raw = os.environ.get(DEFAULT_ALLOWED_ENV) or ""
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    def _target(self, connector: ConnectorView) -> tuple[str, dict[str, str], str | None]:
        """Resolve the URL and headers, or return a refusal code (never a silent call)."""
        base = connector.base_url.rstrip("/")
        path = connector.path if connector.path.startswith("/") else f"/{connector.path}"
        url = f"{base}{path}"
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return url, {}, "invalid_target"
        if host not in self._allowed_hosts():
            return url, {}, "host_not_allowed"
        allow_http = os.environ.get(ALLOW_HTTP_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if parsed.scheme != "https" and not allow_http:
            return url, {}, "tls_required"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        headers.update(connector.extra_headers)
        if connector.auth_kind in ("bearer", "header"):
            secret = os.environ.get(connector.secret_env or "", "")
            if not secret:
                return url, headers, "secret_missing"
            if connector.auth_kind == "bearer":
                headers["Authorization"] = f"Bearer {secret}"
            else:
                headers[connector.auth_header or "X-Api-Key"] = secret
        return url, headers, None

    @staticmethod
    def _receipt(row: dict[str, Any]) -> DispatchReceipt:
        return DispatchReceipt(
            dispatch_id=row["dispatch_id"],
            template_id=row.get("template_id"),
            connector_id=row["connector_id"],
            document_id=row.get("document_id"),
            status=row["status"],  # type: ignore[arg-type]
            status_code=row.get("status_code"),
            latency_ms=row.get("latency_ms"),
            request=json.loads(row.get("request_json") or "{}"),
            response_excerpt=row.get("response_json"),
            error_code=row.get("error_code"),
            created_at=row["created_at"],
        )

    def _record(
        self,
        *,
        dispatch_id: str,
        workspace: str,
        template_id: str | None,
        connector_id: str,
        document_id: str | None,
        status: str,
        status_code: int | None,
        latency_ms: int | None,
        request_payload: dict[str, Any],
        response_excerpt: str | None,
        error_code: str | None,
        idempotency_key: str | None,
        actor: str,
    ) -> DispatchReceipt:
        stamp = now_iso()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO automation_dispatches (dispatch_id, workspace_id, template_id, "
                "connector_id, document_id, status, status_code, latency_ms, request_json, "
                "response_json, error_code, idempotency_key, created_by, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    dispatch_id,
                    workspace,
                    template_id,
                    connector_id,
                    document_id,
                    status,
                    status_code,
                    latency_ms,
                    json.dumps(request_payload, ensure_ascii=False),
                    response_excerpt,
                    error_code,
                    idempotency_key,
                    actor,
                    stamp,
                ),
            )
        row = self.store.one(
            "SELECT * FROM automation_dispatches WHERE dispatch_id = ?", (dispatch_id,)
        )
        assert row is not None
        return self._receipt(row)

    def preview(self, principal: Principal, request: DispatchRequest) -> DispatchPreview:
        """Resolve URL / headers / body for a dispatch **without** calling out or recording anything."""
        self._require(principal, "read")
        workspace = self._workspace(principal)
        connector_row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ? "
            "AND disabled_at IS NULL",
            (request.connector_id, workspace),
        )
        if connector_row is None:
            raise HostNotFound("automation connector not found")
        connector = self._connector_view(connector_row)
        prepared = self.prepare(
            principal,
            request.template_id,
            PrepareRequest(
                document_id=request.document_id,
                text=None if request.document_id else "",
                connector_id=request.connector_id,
            ),
        )
        values = {key: item.value for key, item in prepared.values.items() if item.value}
        values.update({key: str(value) for key, value in request.values.items()})

        operation_id: str | None = None
        content_type: str | None = None
        issues = list(prepared.body_issues)
        body: dict[str, Any] = {}
        target = self._contract_target(principal, request.connector_id)
        if target is not None:
            _, operation = target
            built = build_body(operation, prepared.body_mapping, values)
            operation_id = operation.id
            content_type = operation.content_type
            issues = [BodyIssue(**item) for item in built.issues]
            body = built.body
        else:
            body = dict(prepared.payload)
            body["values"] = values

        url, headers, refusal = self._target(connector)
        # Keep header names, mask the values: a preview must not leak a secret into a screenshot.
        masked = {name: ("***" if name.lower() not in ("content-type",) else value)
                  for name, value in headers.items()}
        return DispatchPreview(
            url=url,
            method=connector.method,
            headers=masked,
            body=body,
            content_type=content_type,
            operation=operation_id,
            schema_kind=connector.schema_kind,  # type: ignore[arg-type]
            issues=issues,
            refusal=refusal,
        )

    def dispatch(self, principal: Principal, request: DispatchRequest) -> DispatchReceipt:
        """One outbound HTTP call to an allow-listed connector, recorded before and after."""
        self._require(principal, "apply")
        workspace = self._workspace(principal)
        if request.idempotency_key:
            existing = self.store.one(
                "SELECT * FROM automation_dispatches WHERE workspace_id = ? AND idempotency_key = ?",
                (workspace, request.idempotency_key),
            )
            if existing is not None:
                return self._receipt(existing)
        connector_row = self.store.one(
            "SELECT * FROM automation_connectors WHERE connector_id = ? AND workspace_id = ? "
            "AND disabled_at IS NULL",
            (request.connector_id, workspace),
        )
        if connector_row is None:
            raise HostNotFound("automation connector not found")
        connector = self._connector_view(connector_row)
        prepared = self.prepare(
            principal,
            request.template_id,
            PrepareRequest(
                document_id=request.document_id,
                text=None if request.document_id else "",
                connector_id=request.connector_id,
            ),
        )
        values = {key: item.value for key, item in prepared.values.items() if item.value}
        values.update({key: str(value) for key, value in request.values.items()})
        dispatch_id = new_id("dsp")
        stamp = {
            "dispatch_id": dispatch_id,
            "requested_by": principal.user_id,
            "requested_at": now_iso(),
        }

        # The downstream's own schema decides the body when a spec is attached (else the legacy flat
        # payload, so connectors registered before specs existed keep working).
        request_json: dict[str, Any]
        payload: dict[str, Any]
        body_issues: list[dict[str, str]] = []
        if prepared.request_body is not None:
            target = self._contract_target(principal, request.connector_id)
            assert target is not None
            _, operation = target
            built = build_body(operation, prepared.body_mapping, values)
            payload = {
                "body": built.body,
                "body_mapping": built.mapping,
                "operation": operation.id,
                "content_type": operation.content_type,
                "template": prepared.payload.get("template"),
                "document_id": request.document_id,
                "source": "smart-edit",
                "dispatch": stamp,
            }
            request_json = built.body
            body_issues = built.issues
        else:
            payload = dict(prepared.payload)
            payload["values"] = values
            payload["dispatch"] = stamp
            request_json = dict(payload)

        # Record where the call went and exactly what would be sent (no secret): the receipt must be
        # enough to audit or replay a call. `sent_body` is a copy so it never changes the outbound body.
        url, headers, refusal = self._target(connector)
        payload["target"] = {
            "url": url,
            "method": connector.method,
            "schema_kind": connector.schema_kind,
        }
        payload["sent_body"] = copy.deepcopy(request_json)

        if body_issues:
            receipt = self._record(
                dispatch_id=dispatch_id,
                workspace=workspace,
                template_id=request.template_id,
                connector_id=connector.connector_id,
                document_id=request.document_id,
                status="refused",
                status_code=None,
                latency_ms=None,
                request_payload=payload,
                response_excerpt=None,
                error_code="missing_required_body",
                idempotency_key=request.idempotency_key,
                actor=principal.user_id,
            )
            raise HostError(
                409,
                "missing_required_body",
                "the request body does not satisfy the downstream spec",
                {
                    "dispatch_id": receipt.dispatch_id,
                    "fields": [item["path"] for item in body_issues],
                    "issues": body_issues,
                },
            )

        if refusal is not None:
            receipt = self._record(
                dispatch_id=dispatch_id,
                workspace=workspace,
                template_id=request.template_id,
                connector_id=connector.connector_id,
                document_id=request.document_id,
                status="refused",
                status_code=None,
                latency_ms=None,
                request_payload=payload,
                response_excerpt=None,
                error_code=refusal,
                idempotency_key=request.idempotency_key,
                actor=principal.user_id,
            )
            status = 403 if refusal in ("host_not_allowed", "tls_required") else 409
            if refusal == "invalid_target":
                status = 400
            raise HostError(
                status,
                refusal,
                f"dispatch refused: {refusal}",
                {"dispatch_id": receipt.dispatch_id, "connector_id": connector.connector_id},
            )
        started = time.monotonic()
        try:
            response = httpx.request(
                connector.method,
                url,
                json=request_json,
                headers=headers,
                timeout=connector.timeout_seconds,
            )
        except httpx.TimeoutException:
            return self._record(
                dispatch_id=dispatch_id,
                workspace=workspace,
                template_id=request.template_id,
                connector_id=connector.connector_id,
                document_id=request.document_id,
                status="failed",
                status_code=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                request_payload=payload,
                response_excerpt=None,
                error_code="timeout",
                idempotency_key=request.idempotency_key,
                actor=principal.user_id,
            )
        except httpx.HTTPError as exc:
            return self._record(
                dispatch_id=dispatch_id,
                workspace=workspace,
                template_id=request.template_id,
                connector_id=connector.connector_id,
                document_id=request.document_id,
                status="failed",
                status_code=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                request_payload=payload,
                response_excerpt=None,
                error_code=f"transport_error:{type(exc).__name__}",
                idempotency_key=request.idempotency_key,
                actor=principal.user_id,
            )
        ok = 200 <= response.status_code < 300
        return self._record(
            dispatch_id=dispatch_id,
            workspace=workspace,
            template_id=request.template_id,
            connector_id=connector.connector_id,
            document_id=request.document_id,
            status="succeeded" if ok else "failed",
            status_code=response.status_code,
            latency_ms=int((time.monotonic() - started) * 1000),
            request_payload=payload,
            response_excerpt=(response.text or "")[:MAX_RESPONSE_EXCERPT],
            error_code=None if ok else f"http_{response.status_code}",
            idempotency_key=request.idempotency_key,
            actor=principal.user_id,
        )

    def list_dispatches(self, principal: Principal, *, limit: int = 50) -> list[DispatchReceipt]:
        self._require(principal, "read")
        rows = self.store.all(
            "SELECT * FROM automation_dispatches WHERE workspace_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (self._workspace(principal), max(1, min(int(limit), 200))),
        )
        return [self._receipt(row) for row in rows]


__all__ = [
    "ALLOW_HTTP_ENV",
    "AutomationRegistry",
    "DEFAULT_ALLOWED_ENV",
    "SYSTEM_PROMPT",
    "detect_variables",
]