from __future__ import annotations

import re


DOMAIN_KEYWORDS = [
    "ma túy", "ma tuý", "matuy", "mai thúy", "mai thuy",
    "chất ma túy", "tiền chất", "cai nghiện", "sau cai",
    "tàng trữ", "vận chuyển", "mua bán", "sử dụng trái phép",
    "phòng chống ma túy", "phòng, chống ma túy",
    "người nghiện", "người sử dụng trái phép chất ma túy",
    "thuốc lá điện tử", "bóng cười", "n2o",
    "bộ luật hình sự", "luật phòng chống ma túy",
]

DANGEROUS_PATTERNS = [
    r"lách luật",
    r"né\s+(?:tội|trách nhiệm|công an|kiểm tra|xử lý)",
    r"trốn\s+(?:tội|truy tố|trách nhiệm|công an)",
    r"qua mặt",
    r"che giấu",
    r"phi tang",
    r"vận chuyển.*(?:không bị bắt|an toàn|trót lọt)",
    r"mua.*(?:ở đâu|chỗ nào)",
    r"cách\s+(?:sản xuất|điều chế|pha chế|trồng|mua bán|vận chuyển)",
    r"test.*ma túy.*(?:qua|âm tính|né)",
]


def is_in_domain(text: str) -> bool:
    q = str(text).lower()
    return any(k in q for k in DOMAIN_KEYWORDS)


def detect_safety_issue(text: str) -> str | None:
    q = str(text).lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, q):
            return "Câu hỏi có dấu hiệu yêu cầu lách luật, né tránh xử lý, che giấu hành vi hoặc hỗ trợ hành vi liên quan đến ma túy."
    return None


# --- MaiThuyLaw English domain wrapper ---
_MAITHUYLAW_ORIGINAL_IS_IN_DOMAIN = is_in_domain

_MAITHUYLAW_EN_DOMAIN_TERMS = {
    "drug",
    "drugs",
    "drug news",
    "drug law",
    "drug policy",
    "drug prevention",
    "drug control",
    "drug-related",
    "narcotic",
    "narcotics",
    "substance abuse",
    "addiction",
    "addict",
    "rehabilitation",
    "compulsory rehabilitation",
    "detoxification",
    "harm reduction",
    "methamphetamine",
    "heroin",
    "cannabis",
    "vietnam drug",
    "vietnamese drug",
}


def is_in_domain(text: str) -> bool:
    lowered = (text or "").lower()
    if any(term in lowered for term in _MAITHUYLAW_EN_DOMAIN_TERMS):
        return True
    return _MAITHUYLAW_ORIGINAL_IS_IN_DOMAIN(text)
