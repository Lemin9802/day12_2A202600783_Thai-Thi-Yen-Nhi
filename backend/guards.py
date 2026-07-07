from __future__ import annotations

import re


DOMAIN_KEYWORDS = [
    # Vietnamese with diacritics
    "ma túy", "ma tuý", "matuy", "mai thúy", "mai thuy",
    "chất ma túy", "tiền chất", "cai nghiện", "sau cai",
    "tàng trữ", "vận chuyển", "mua bán", "sử dụng trái phép",
    "phòng chống ma túy", "phòng, chống ma túy",
    "người nghiện", "người sử dụng trái phép chất ma túy",
    "thuốc lá điện tử", "bóng cười", "n2o",
    "bộ luật hình sự", "luật phòng chống ma túy",
    # Vietnamese without diacritics (no-diacritic input support)
    "ma tuy", "chat ma tuy", "tien chat", "cai nghien", "sau cai",
    "tang tru", "van chuyen", "mua ban", "su dung trai phep",
    "phong chong ma tuy", "nguoi nghien",
    "thuoc la dien tu", "bong cuoi",
    "bo luat hinh su", "luat phong chong ma tuy",
]

DANGEROUS_PATTERNS = [
    # Vietnamese with diacritics
    r"lách luật",
    r"né\s+(?:tội|trách nhiệm|công an|kiểm tra|xử lý)",
    r"trốn\s+(?:tội|truy tố|trách nhiệm|công an)",
    r"qua mặt",
    r"che giấu",
    r"phi tang",
    r"vận chuyển.*(?:không bị bắt|an toàn|trót lọt)",
    r"mua.*(?:ở đâu|chỗ nào|như thế nào|không bị phát hiện)",
    r"cách\s+(?:sản xuất|điều chế|pha chế|trồng|mua bán|vận chuyển|sử dụng|dùng)",
    r"(?:làm sao|làm thế nào|cách)\s+(?:để\s+)?(?:mua|bán|tàng trữ|giấu|vận chuyển|sử dụng|dùng)\s+ma túy",
    r"test.*ma túy.*(?:qua|âm tính|né)",
    r"xét nghiệm.*(?:qua|âm tính|không bị phát hiện|né|tránh)",
    r"giấu\s+(?:ma túy|tang vật|bằng chứng)",
    r"tiêu hủy.*(?:bằng chứng|tang vật|ma túy)",
    r"(?:bán|buôn).*ma túy.*(?:an toàn|không bị|cách|làm sao)",
    # Vietnamese without diacritics
    r"lach luat",
    r"ne\s+(?:toi|trach nhiem|cong an|kiem tra|xu ly)",
    r"tron\s+(?:toi|truy to|trach nhiem|cong an)",
    r"qua mat",
    r"che giau",
    r"phi tang",
    r"cach\s+(?:san xuat|dieu che|pha che|trong|mua ban|van chuyen|su dung|dung)",
    r"cach\s+giau\s+ma\s+tuy",
    r"cach\s+mua\s+ma\s+tuy",
    r"cach\s+van\s+chuyen\s+ma\s+tuy",
    r"cach\s+su\s+dung\s+ma\s+tuy",
    r"(?:lam sao|lam the nao|cach)\s+(?:de\s+)?(?:mua|ban|tang tru|giau|van chuyen|su dung|dung)\s+ma\s*tuy",
    r"qua\s+mat\s+xet\s+nghiem",
    r"cach\s+qua\s+mat\s+xet\s+nghiem",
    r"lam\s+sao\s+de\s+mua\s+ma\s+tuy",
    r"lam\s+sao\s+de\s+giau\s+ma\s+tuy",
    r"giau\s+(?:ma\s*tuy|tang\s*vat|bang\s*chung)",
    r"tieu\s+huy.*(?:bang\s*chung|tang\s*vat|ma\s*tuy)",
]

REFUSAL_MESSAGE = (
    "Mình không thể hỗ trợ theo hướng hướng dẫn thực hiện hoặc che giấu hành vi vi phạm pháp luật. "
    "Tuy nhiên, mình có thể giúp bạn tìm hiểu quy định liên quan, hậu quả pháp lý, "
    "hoặc các bước an toàn để liên hệ luật sư/cơ quan có thẩm quyền."
)


def is_in_domain(text: str) -> bool:
    q = str(text).lower()
    if any(k in q for k in DOMAIN_KEYWORDS):
        return True
    return _is_in_domain_en(q)


def _is_in_domain_en(lowered: str) -> bool:
    en_terms = {
        "drug", "drugs", "drug news", "drug law", "drug policy",
        "drug prevention", "drug control", "drug-related",
        "narcotic", "narcotics", "substance abuse",
        "addiction", "addict", "rehabilitation",
        "compulsory rehabilitation", "detoxification",
        "harm reduction", "methamphetamine", "heroin",
        "cannabis", "vietnam drug", "vietnamese drug",
    }
    return any(term in lowered for term in en_terms)


def detect_safety_issue(text: str) -> str | None:
    q = str(text).lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, q):
            return (
                "Câu hỏi có dấu hiệu yêu cầu lách luật, né tránh xử lý, "
                "che giấu hành vi hoặc hỗ trợ hành vi liên quan đến ma túy."
            )
    return None
