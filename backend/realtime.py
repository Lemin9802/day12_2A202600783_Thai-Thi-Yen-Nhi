from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx


REALTIME_TERMS = [
    "mới nhất",
    "gần đây",
    "hôm nay",
    "hiện nay",
    "vừa",
    "realtime",
    "thời sự",
    "tin mới",
    "năm 2026",
    "2026",
]

OFFICIAL_OR_TRUSTED_DOMAINS = [
    "chinhphu.vn",
    "baochinhphu.vn",
    "mps.gov.vn",
    "moh.gov.vn",
    "moj.gov.vn",
    "quochoi.vn",
    "vanban.chinhphu.vn",
    "vbpl.vn",
    "nhandan.vn",
    "vnanet.vn",
    "vietnamplus.vn",
]


def extract_urls(text: str) -> list[str]:
    pattern = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
    return [m.group(0).rstrip(".,;!?") for m in pattern.finditer(text or "")]


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_official_or_allowed_url(url: str) -> bool:
    host = _domain(url)
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_OR_TRUSTED_DOMAINS)


def wants_realtime(message: str) -> bool:
    lowered = (message or "").lower()
    return any(term in lowered for term in REALTIME_TERMS)


def realtime_enabled() -> bool:
    return os.getenv("MAITHUYLAW_REALTIME_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def realtime_unavailable_answer(language: str = "vi") -> str:
    if language == "en":
        return (
            "I’m sorry, I can’t complete a real-time source check at the moment due to a temporary technical issue. "
            "Please try again later, or paste an official source link here so I can review and summarize it."
        )

    return (
        "Xin lỗi, hiện mình chưa thể tra cứu thông tin mới nhất do sự cố kỹ thuật tạm thời. "
        "Bạn có thể thử lại sau, hoặc gửi trực tiếp đường dẫn từ nguồn chính thống để mình kiểm tra và tóm tắt."
    )


def realtime_research_intro(language: str = "vi") -> str:
    if language == "en":
        return (
            "To answer this accurately, I will prioritize official and verified sources, "
            "and avoid unverified, sensational, or low-credibility information."
        )

    return (
        "Để trả lời chính xác, mình sẽ ưu tiên tra cứu từ văn bản/cổng thông tin nhà nước, "
        "báo chính thống và các nguồn đã được kiểm chứng; tránh dựa vào tin giật gân hoặc nguồn chưa xác thực."
    )


def search_realtime(query: str, language: str = "vi") -> list[dict]:
    """Search recent official/trusted sources when a realtime search key is configured.

    This function intentionally returns a clean list of user-facing source objects.
    It does not expose provider/configuration details to the end user.
    """
    if not realtime_enabled():
        return []

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    max_results = int(os.getenv("MAITHUYLAW_REALTIME_MAX_RESULTS", "5") or "5")
    domain_query = " OR ".join([f"site:{domain}" for domain in OFFICIAL_OR_TRUSTED_DOMAINS[:8]])
    search_query = f"({query}) ({domain_query})"

    payload = {
        "api_key": api_key,
        "query": search_query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        response = httpx.post("https://api.tavily.com/search", json=payload, timeout=25)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []

    cleaned = []
    for item in data.get("results", []) or []:
        url = item.get("url") or ""
        if not is_official_or_allowed_url(url):
            continue

        cleaned.append(
            {
                "title": item.get("title") or url,
                "url": url,
                "content": item.get("content") or "",
                "source_type": "realtime",
            }
        )

    return cleaned[:max_results]
