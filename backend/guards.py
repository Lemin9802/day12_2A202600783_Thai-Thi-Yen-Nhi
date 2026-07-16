from __future__ import annotations

import re
from backend.intent import has_legal_document_identifier, is_identity_question, normalize_text

DOMAIN_TERMS = (
    "ma tuy", "chat ma tuy", "tien chat", "cai nghien", "sau cai", "tang tru", "van chuyen",
    "mua ban", "su dung trai phep", "phong chong ma tuy", "nguoi nghien", "bo luat hinh su",
    "luat phong chong ma tuy", "narcotic", "drug law", "drug policy", "drug prevention", "addiction",
    "rehabilitation", "methamphetamine", "heroin", "cannabis",
)
LEGAL_FRAMING = (
    "bi xu ly", "bi phat", "xu phat", "phap luat quy dinh", "trach nhiem", "cau thanh toi",
    "hinh phat", "muc phat", "khac nhau", "hau qua phap ly", "co hop phap", "legal consequence",
    "what is the penalty", "punishable", "under the law",
)
OPERATIONAL_PATTERNS = (
    r"\b(?:cach|lam sao|lam the nao)\s+(?:de\s+)?(?:mua|ban|giau|van chuyen|san xuat|dieu che|su dung|dung)\b",
    r"\b(?:ne|tron|qua mat|lach)\s+(?:cong an|canh sat|kiem tra|xet nghiem|phap luat|trach nhiem)\b",
    r"\b(?:che giau|phi tang|tieu huy)\s+(?:ma tuy|tang vat|bang chung)\b",
    r"\b(?:van chuyen|buon|ban)\b.{0,40}\b(?:an toan|trot lot|khong bi bat|khong bi phat hien)\b",
    r"\b(?:how|ways?)\s+(?:can i|to)\s+(?:buy|sell|hide|conceal|transport|smuggle|make|manufacture|use)\b.{0,50}\b(?:drug|drugs|narcotic|evidence)\b",
    r"\b(?:hide|conceal|destroy)\b.{0,30}\b(?:drug|drugs|evidence|contraband)\b",
    r"\b(?:evade|avoid|bypass|beat|fool)\b.{0,35}\b(?:police|detection|inspection|drug test|testing|law enforcement)\b",
    r"\b(?:pass|beat)\b.{0,20}\bdrug test\b",
)

REFUSAL_MESSAGE = (
    "Mình không thể hỗ trợ theo hướng hướng dẫn thực hiện hoặc che giấu hành vi vi phạm pháp luật. "
    "Tuy nhiên, mình có thể giúp bạn tìm hiểu quy định liên quan, hậu quả pháp lý hoặc các bước an toàn để liên hệ luật sư/cơ quan có thẩm quyền."
)


def is_in_domain(text: str) -> bool:
    q = normalize_text(text)
    return is_identity_question(text) or has_legal_document_identifier(text) or any(term in q for term in DOMAIN_TERMS)


def is_legal_education_question(text: str) -> bool:
    q = normalize_text(text)
    return any(term in q for term in LEGAL_FRAMING)


def detect_safety_issue(text: str) -> str | None:
    q = normalize_text(text)
    if is_legal_education_question(text):
        return None
    if any(re.search(pattern, q, re.I) for pattern in OPERATIONAL_PATTERNS):
        return "Câu hỏi yêu cầu hướng dẫn thực hiện, che giấu hoặc né tránh việc phát hiện hành vi liên quan đến ma túy."
    return None


def output_safety_check(answer: str, source_count: int) -> tuple[bool, str | None]:
    q = normalize_text(answer)
    if any(re.search(pattern, q, re.I) for pattern in OPERATIONAL_PATTERNS):
        return False, "Câu trả lời có nội dung hướng dẫn không an toàn."
    internal = ("dataset", "backend", "metadata", "provider", "fallback", "key context", "build production", "crawler/local")
    if any(term in q for term in internal):
        return False, "Câu trả lời chứa thông tin kỹ thuật nội bộ."
    if source_count == 0 and re.search(r"\b(?:dieu|khoan)\s+\d+|\bphat\s+tu\b|\bphat\s+tien\b", q):
        return False, "Kết luận pháp lý cụ thể chưa có nguồn hỗ trợ."
    return True, None
