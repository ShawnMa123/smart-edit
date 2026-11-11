"""Deterministic query construction for both input modes.

The spec allows a model here; the POC uses a deterministic builder so a retrieval query can be
replayed and explained. `build_query` is pure: it reads `state` and returns `(queries, filters)`.

Filters are applied by the service **before** recall. The node only passes them through.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from app.regulatory.entities import extract_entities

Mode = Literal["enriched", "raw"]

_FALLBACK_QUERY = "保函 法规 适用规则"

_COUNTRY_CODES = {
    "中国": "CN",
    "中华人民共和国": "CN",
    "新加坡": "SG",
    "美国": "US",
    "日本": "JP",
    "澳大利亚": "AU",
    "英国": "GB",
    "香港": "HK",
    "德国": "DE",
    "法国": "FR",
    "韩国": "KR",
    "印度": "IN",
    "马来西亚": "MY",
    "泰国": "TH",
    "越南": "VN",
    "印度尼西亚": "ID",
    "菲律宾": "PH",
    "新西兰": "NZ",
    "加拿大": "CA",
    "阿联酋": "AE",
    "沙特阿拉伯": "SA",
    "俄罗斯": "RU",
    "巴西": "BR",
    "荷兰": "NL",
    "意大利": "IT",
    "西班牙": "ES",
    "瑞士": "CH",
}

_BUSINESS_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("guarantee", ("保函", "guarantee", "urdg", "isp98", "见索即付", "独立保函")),
    ("customs", ("海关", "关税", "customs", "tariff", "完税", "原产地")),
    ("banking", ("银行", "banking", "ucp", "信用证", "letter of credit")),
    ("trade", ("进出口", "贸易", "import", "export", "cisg", "wto", "incoterms")),
)

_DATE_KEYS = (
    "transaction_date",
    "issue_date",
    "effective_date",
    "application_date",
    "open_date",
    "expiry_date",
    "trade_date",
)
_AMOUNT_KEYS = ("guarantee_amount", "amount", "lc_amount", "total_amount")
_COUNTRY_KEYS = ("applicant_country", "beneficiary_country", "origin_country", "country")

# Body-only inference is conservative: two-letter words such as IN/IT/ES are common English tokens
# and must not silently filter the corpus. Field values are authoritative and still accept any code.
_BODY_COUNTRY_CODES = {
    "CN",
    "SG",
    "US",
    "JP",
    "AU",
    "GB",
    "HK",
    "DE",
    "FR",
    "KR",
    "CA",
    "AE",
    "NZ",
    "NL",
}

_RAW_KEYWORDS = (
    "保函",
    "guarantee",
    "urdg",
    "ucp",
    "isp",
    "金额",
    "币种",
    "期限",
    "展期",
    "通知",
    "国别",
    "日期",
    "海关",
    "关税",
    "customs",
    "tariff",
)


def _field(fields: dict, key: str) -> str | None:
    raw = fields.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _text(state: dict) -> str:
    return "\n".join(str(doc.get("full_text") or "") for doc in state.get("docs") or [])


def infer_business_type(state: dict) -> str | None:
    """Return a deterministic business type from normalised state or document text."""
    explicit = state.get("business_type")
    if explicit:
        return str(explicit)
    fields = state.get("fields") or {}
    from_fields = _field(fields, "business_type") or _field(fields, "document_type")
    if from_fields:
        return from_fields
    text = _text(state).casefold()
    if not text:
        return None
    scores: list[tuple[int, str]] = []
    for name, keywords in _BUSINESS_TYPES:
        score = sum(text.count(keyword.casefold()) for keyword in keywords)
        if score:
            scores.append((score, name))
    if not scores:
        return None
    scores.sort(key=lambda item: (-item[0], item[1]))
    return scores[0][1]


def _country_codes(state: dict) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        if not value:
            return
        code = value.strip().upper()
        if re.fullmatch(r"[A-Z]{2}", code):
            candidate = code
        else:
            candidate = _COUNTRY_CODES.get(value.strip(), "")
        if candidate and candidate not in seen:
            seen.add(candidate)
            codes.append(candidate)

    fields = state.get("fields") or {}
    for key in _COUNTRY_KEYS:
        add(_field(fields, key))

    # Body-derived facts are only a fallback: the field table is the authoritative source.
    for entity in extract_entities(_text(state)):
        if entity in _COUNTRY_CODES:
            add(entity)
        elif re.fullmatch(r"[A-Z]{2}", entity) and entity in _BODY_COUNTRY_CODES:
            add(entity)
    return codes


def transaction_date(state: dict) -> str | None:
    """ISO transaction date from fields, else the first ISO date in the body; never a guess."""
    fields = state.get("fields") or {}
    for key in _DATE_KEYS:
        value = _field(fields, key)
        if value and _iso_date(value):
            return value
    match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", _text(state))
    if match and _iso_date(match.group(1)):
        return match.group(1)
    return None


def _iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _amount(state: dict) -> str | None:
    fields = state.get("fields") or {}
    for key in _AMOUNT_KEYS:
        value = _field(fields, key)
        if value:
            return value
    return None


def _clean(queries: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for query in queries:
        value = re.sub(r"\s+", " ", query).strip()
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value[:300])
    return out


def _raw_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    out: list[str] = []
    for part in parts:
        value = part.strip()
        if not value:
            continue
        lowered = value.casefold()
        if any(keyword.casefold() in lowered for keyword in _RAW_KEYWORDS):
            out.append(value[:240])
    return out


def build_query(state: dict, mode: Mode) -> tuple[list[str], dict]:
    """Build 3-5 queries and the pre-recall filters for `mode`."""
    fields = state.get("fields") or {}
    business_type = infer_business_type(state)
    countries = _country_codes(state)
    amount = _amount(state)
    as_of = transaction_date(state)

    country_text = " ".join(countries)
    type_text = business_type or "保函"

    if mode == "enriched":
        queries = [
            f"{type_text} {country_text} 法规 适用规则",
            f"{type_text} 金额 {amount} 生效 版本" if amount else f"{type_text} 独立保函 审单 表面相符",
            f"{type_text} 展期 通知 期限",
            f"{type_text} 单据 条款 条件",
        ]
        titles = [
            str(doc.get("filename") or "").strip()
            for doc in state.get("docs") or []
            if str(doc.get("filename") or "").strip()
        ]
        if titles:
            queries.append(f"{type_text} {titles[0]}")
    else:
        queries = _raw_sentences(_text(state))
        queries.extend(
            [
                f"{type_text} 法规 适用规则",
                f"{type_text} 金额 {amount}" if amount else f"{type_text} 条件 期限 单据",
                f"{type_text} 国别 {country_text} 规则" if country_text else f"{type_text} 通知 审单",
            ]
        )

    queries = _clean(queries)
    if not queries:
        queries = [_FALLBACK_QUERY]
    # The service contract asks for 3-5; fill deterministically rather than sending a thin query.
    filler = [
        f"{type_text} 法规 适用规则",
        f"{type_text} 条件 期限 单据",
        f"{type_text} 审单 通知",
    ]
    for query in filler:
        if len(queries) >= 3:
            break
        if query not in queries:
            queries.append(query)
    queries = queries[:5]

    filters = {
        "applies_to": [business_type] if business_type else [],
        "jurisdictions": countries,
        "as_of": as_of,
    }
    return queries, filters
