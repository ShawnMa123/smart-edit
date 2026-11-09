"""Entity extraction for citation checking.

Agent 4's `citation_support` imports `extract_entities`; keep the signature stable.

The function returns the matched source text (whitespace-collapsed), not a normalised value, so a
caller can ask the honest question "does this exact fact appear in the cited chunk?".  Conservative
by design: a missed entity only means one fewer check, never a fabricated one.
"""

from __future__ import annotations

import re

# Currency amounts: "USD 500,000.00", "USD 500K", "500000 美元", "SGD 1.2m".
_AMOUNT = re.compile(
    r"(?<![A-Za-z])(?:USD|EUR|CNY|RMB|GBP|JPY|SGD|HKD|AUD|CHF|CAD)\s?"
    r"\d[\d,]*(?:\.\d+)?\s?(?:[KMBkmb](?![A-Za-z])|万|亿)?"
    r"|(?<![\d,])\d[\d,]*(?:\.\d+)?\s?(?:美元|欧元|元|日元|英镑|新元|港元|澳元|人民币)"
)

# Dates: ISO, D/M/Y or M/D/Y, and the Chinese calendar form.
_DATE = re.compile(
    r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)"
    r"|(?<!\d)\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?!\d)"
    r"|(?<!\d)\d{4}\s?年\s?\d{1,2}\s?月\s?\d{1,2}\s?日"
)

# Two-letter ISO codes only when they are standalone tokens. The list is intentionally short:
# matching arbitrary two-letter words would turn every English sentence into a jurisdiction.
_COUNTRY_CODE = re.compile(
    r"(?<![A-Za-z])(?:CN|SG|US|JP|AU|GB|HK|DE|FR|KR|IN|MY|TH|VN|ID|PH|NZ|CA|AE|SA|RU|BR|NL|IT|ES|CH)(?![A-Za-z])"
)
_COUNTRY_NAME = re.compile(
    r"中国|中华人民共和国|新加坡|美国|日本|澳大利亚|英国|香港|德国|法国|韩国|印度|马来西亚|泰国|越南|"
    r"印度尼西亚|菲律宾|新西兰|加拿大|阿联酋|沙特阿拉伯|俄罗斯|巴西|荷兰|意大利|西班牙|瑞士"
)

# Rule / standard identifiers.
_STANDARD = re.compile(
    r"\b(?:URDG\s?758|UCP\s?600|ISP\s?98|Incoterms\s?20(?:10|20)|CISG|GATT\s?1994|"
    r"TBT|SPS|TFA|EAR|OFAC|WTO)\b",
    re.IGNORECASE,
)

# Article / section references.
_ARTICLE = re.compile(
    r"第\s*\d+\s*条|§\s*\d+|Article\s+\d+[A-Za-z]?|Section\s+\d+[A-Za-z]?(?:\.\d+)*|"
    r"第\s*\d+\s*款|第\s*\d+\s*项",
    re.IGNORECASE,
)

_PATTERNS = (_AMOUNT, _DATE, _COUNTRY_CODE, _COUNTRY_NAME, _STANDARD, _ARTICLE)


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_entities(text: str) -> list[str]:
    """Return amount / date / country / standard / article mentions, in source order, deduplicated."""
    if not text:
        return []
    found: list[tuple[int, str]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            value = _collapse_ws(match.group(0))
            if value:
                found.append((match.start(), value))
    found.sort(key=lambda item: item[0])
    out: list[str] = []
    seen: set[str] = set()
    for _, value in found:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out
