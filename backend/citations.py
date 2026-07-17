"""Claim-level citation validation for legal answers."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

CITATION_RE = re.compile(r"\[([0-9][0-9,\s]*)\]")
HIGH_STAKES_RE = re.compile(
    r"\b(?:điều|khoản|điểm|nghị định|thông tư|pháp lệnh|luật|phạt|mức phạt|"
    r"trách nhiệm hình sự|hình phạt|tù|article|clause|decree|circular|penalty|"
    r"imprisonment|fine)\b|\b\d+[\d.,]*\s*(?:triệu|đồng|tháng tù|năm tù|%)\b|"
    r"\b\d{1,4}/\d{4}/[A-ZĐ-]+\b",
    re.I,
)
LEGAL_AUTHORITY_RE = re.compile(
    r"\b(?:điều|khoản|điểm|phạt|mức phạt|trách nhiệm hình sự|hình phạt|tù|"
    r"article|clause|penalty|imprisonment|fine)\b|\b\d+[\d.,]*\s*(?:triệu|đồng|tháng tù|năm tù)\b",
    re.I,
)
INSUFFICIENT_MARKERS = (
    "chưa thấy căn cứ",
    "chưa đủ căn cứ",
    "không đủ căn cứ",
    "do not yet see",
    "insufficient basis",
)
STOPWORDS = {
    "và", "là", "của", "có", "cho", "trong", "với", "được", "theo", "một", "các", "này", "đó",
    "the", "and", "for", "with", "from", "this", "that", "are", "was", "were", "has", "have",
}


@dataclass
class CitationVerification:
    valid: bool
    coverage: float
    substantive_claims: int
    cited_claims: int
    invalid_citations: list[int] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    legal_claims_without_legal_source: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _normalize(value))
        if len(token) >= 3 and token not in STOPWORDS
    }


def _source_blob(source: dict) -> str:
    meta = source.get("metadata") or {}
    return " ".join([
        str(source.get("content") or source.get("text") or source.get("preview") or ""),
        str(source.get("name") or source.get("title") or ""),
        " ".join(str(value) for value in meta.values()),
    ])


def _source_type(source: dict) -> str:
    meta = source.get("metadata") or {}
    return str(meta.get("source_type") or meta.get("type") or source.get("source_type") or "attachment").lower()


def _claims(answer: str) -> list[str]:
    cleaned = re.sub(r"(?m)^#{1,6}\s+.*$", "", str(answer or ""))
    pieces: list[str] = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[-*•]\s+", line):
            pieces.append(line)
        else:
            pieces.extend(re.split(r"(?<=[.!?…])\s+(?!\[[0-9])", line))
    claims: list[str] = []
    for piece in pieces:
        claim = re.sub(r"^[-*•\d.)\s]+", "", piece).strip()
        plain = CITATION_RE.sub("", claim).strip()
        if len(plain) < 25:
            continue
        if any(marker in _normalize(plain) for marker in INSUFFICIENT_MARKERS):
            continue
        if plain.lower().startswith(("lưu ý", "note", "nguồn tham khảo")):
            continue
        claims.append(claim)
    return claims


def _citation_ids(claim: str) -> list[int]:
    ids: list[int] = []
    for match in CITATION_RE.finditer(claim):
        ids.extend(int(value) for value in re.findall(r"\d+", match.group(1)))
    return sorted(set(ids))


def _supported_by(claim: str, source: dict) -> bool:
    claim_tokens = _tokens(CITATION_RE.sub("", claim))
    if not claim_tokens:
        return True
    source_tokens = _tokens(_source_blob(source))
    overlap = len(claim_tokens & source_tokens) / max(len(claim_tokens), 1)
    claim_without_citations = CITATION_RE.sub("", claim)
    numbers = set(re.findall(r"\d+[\d.,]*", claim_without_citations))
    source_numbers = set(re.findall(r"\d+[\d.,]*", _source_blob(source)))
    numbers_supported = not numbers or numbers.issubset(source_numbers)
    return overlap >= 0.10 and numbers_supported


def verify_citations(
    answer: str,
    dataset_results: list[dict],
    attachments: list[dict],
    *,
    intent: str = "legal_lookup",
) -> CitationVerification:
    """Validate source IDs, coverage, lexical support, and legal-source use."""
    sources = list(dataset_results) + list(attachments)
    normalized_answer = _normalize(answer)
    if intent == "identity":
        return CitationVerification(True, 1.0, 0, 0)
    if not sources and any(marker in normalized_answer for marker in INSUFFICIENT_MARKERS):
        return CitationVerification(True, 1.0, 0, 0)

    claims = _claims(answer)
    if not claims:
        valid = bool(any(marker in normalized_answer for marker in INSUFFICIENT_MARKERS))
        return CitationVerification(valid, 1.0 if valid else 0.0, 0, 0)

    invalid: set[int] = set()
    unsupported: list[str] = []
    wrong_legal_source: list[str] = []
    cited_claims = 0

    for claim in claims:
        citation_ids = _citation_ids(claim)
        if citation_ids:
            cited_claims += 1
        valid_ids = []
        for citation_id in citation_ids:
            if citation_id < 1 or citation_id > len(sources):
                invalid.add(citation_id)
            else:
                valid_ids.append(citation_id)
        high_stakes = bool(HIGH_STAKES_RE.search(CITATION_RE.sub("", claim)))
        if high_stakes and not valid_ids:
            unsupported.append(claim[:240])
            continue
        if valid_ids:
            cited_sources = [sources[index - 1] for index in valid_ids]
            if not any(_supported_by(claim, source) for source in cited_sources):
                unsupported.append(claim[:240])
            if LEGAL_AUTHORITY_RE.search(CITATION_RE.sub("", claim)) and not any(_source_type(source) == "legal" for source in cited_sources):
                wrong_legal_source.append(claim[:240])

    coverage = cited_claims / max(len(claims), 1)
    valid = (
        not invalid
        and not unsupported
        and not wrong_legal_source
        and (coverage >= 0.5 or all(not HIGH_STAKES_RE.search(claim) for claim in claims))
    )
    return CitationVerification(
        valid=valid,
        coverage=round(coverage, 4),
        substantive_claims=len(claims),
        cited_claims=cited_claims,
        invalid_citations=sorted(invalid),
        unsupported_claims=unsupported,
        legal_claims_without_legal_source=wrong_legal_source,
    )
