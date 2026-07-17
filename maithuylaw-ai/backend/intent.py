from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

IDENTITY_ANSWER_VI = (
    "MaiThuyLaw là tên dự án ghép từ “Mai Thúy” và “Law”. “Mai Thúy” là cách nói lái/đọc trại vui "
    "của “ma túy” trong tiếng Việt, còn “Law” là luật. Tên này thể hiện ý tưởng của dự án: một trợ lý AI "
    "hỗ trợ tra cứu, giải thích thông tin pháp luật, chính sách và nguồn tin chính thống liên quan đến ma túy tại Việt Nam."
)
IDENTITY_ANSWER_EN = (
    "MaiThuyLaw combines “Mai Thúy” and “Law”. “Mai Thúy” is Vietnamese wordplay for “ma túy” (drugs), "
    "and “Law” refers to legal information. The project is an AI assistant for Vietnamese drug-related law, policy, and official sources."
)

@dataclass(frozen=True)
class IntentResult:
    intent: str
    query_rewrite: str
    required_sources: tuple[str, ...]
    needs_controlled_search: bool = False


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def is_identity_question(text: str) -> bool:
    q = normalize_text(text).replace(" ", "")
    return "maithuylaw" in q and any(term in normalize_text(text) for term in ("la gi", "nghia la gi", "vi sao ten", "tai sao ten", "y nghia"))


def has_legal_document_identifier(text: str) -> bool:
    q = normalize_text(text)
    patterns = (
        r"\b\d{1,4}/\d{4}/(?:nd-cp|nđ-cp|tt-[a-z]+|qh\d+|ubtvqh\d+|qd-[a-z]+)\b",
        r"\b(?:nghi dinh|thong tu|luat|phap lenh|quyet dinh)\s+so\s+\d+",
        r"\b(?:dieu|khoan|diem)\s+\d+\b",
    )
    return any(re.search(pattern, q, re.I) for pattern in patterns)


def route_intent(text: str) -> IntentResult:
    q = normalize_text(text)
    if is_identity_question(text):
        return IntentResult("identity", text, ())
    if has_legal_document_identifier(text):
        return IntentResult("legal_lookup", text, ("legal",))
    if any(term in q for term in ("moi nhat", "gan day", "tin moi", "chinh sach moi", "cap nhat")):
        return IntentResult("policy_news", text, ("policy", "news"), needs_controlled_search=True)
    if any(term in q for term in ("bi phat", "xu phat", "xu ly the nao", "trach nhiem hinh su", "hinh phat", "muc phat")):
        return IntentResult("penalty_question", text, ("legal",))
    if any(term in q for term in ("thu tuc", "ho so", "quy trinh", "tham quyen", "cai nghien bat buoc")):
        return IntentResult("procedure", text, ("legal", "policy"))
    if any(term in q for term in ("khac gi", "khac nhau", "so sanh")):
        return IntentResult("comparison", text, ("legal",))
    if any(term in q for term in ("gia dinh", "nguoi than", "ho tro", "giup do")):
        return IntentResult("family_support", text, ("policy", "legal"))
    if any(term in q for term in ("la gi", "dinh nghia", "the nao la")):
        return IntentResult("definition", text, ("legal", "policy"))
    return IntentResult("legal_lookup", text, ("legal", "policy", "news"))
