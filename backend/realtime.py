from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import httpx

REALTIME_TERMS = ["mới nhất", "gần đây", "hôm nay", "hiện nay", "vừa", "realtime", "thời sự", "tin mới"]
OFFICIAL_OR_TRUSTED_DOMAINS = ["chinhphu.vn", "baochinhphu.vn", "mps.gov.vn", "moh.gov.vn", "moj.gov.vn", "quochoi.vn", "vanban.chinhphu.vn", "vbpl.vn", "nhandan.vn", "vnanet.vn", "vietnamplus.vn"]


def extract_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(".,;!?") for m in re.finditer(r"https?://[^\s)]+", text or "", re.I)]


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
        return "I cannot complete a current-source check yet. You can provide an official link for review, or try again later."
    return "Mình chưa thể kiểm tra nguồn mới nhất lúc này. Bạn có thể gửi link chính thống để đối chiếu hoặc thử lại sau."


def realtime_research_intro(language: str = "vi") -> str:
    if language == "en":
        return "I will prioritize official and verified sources."
    return "Mình sẽ ưu tiên văn bản và cổng thông tin chính thống đã được kiểm chứng."


def search_realtime(query: str, language: str = "vi") -> list[dict]:
    if not realtime_enabled():
        return []
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    max_results = int(os.getenv("MAITHUYLAW_REALTIME_MAX_RESULTS", "5") or "5")
    domain_query = " OR ".join([f"site:{domain}" for domain in OFFICIAL_OR_TRUSTED_DOMAINS[:8]])
    payload = {"api_key": api_key, "query": f"({query}) ({domain_query})", "search_depth": "advanced", "max_results": max_results, "include_answer": False, "include_raw_content": False}
    try:
        response = httpx.post("https://api.tavily.com/search", json=payload, timeout=25)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    cleaned = []
    for item in data.get("results", []) or []:
        url = item.get("url") or ""
        if is_official_or_allowed_url(url):
            cleaned.append({"title": item.get("title") or url, "url": url, "content": item.get("content") or "", "source_type": "realtime"})
    return cleaned[:max_results]
