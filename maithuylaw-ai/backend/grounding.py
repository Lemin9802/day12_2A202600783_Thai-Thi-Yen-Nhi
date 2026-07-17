from __future__ import annotations

import re
from urllib.parse import urlsplit

OFFICIAL_DOMAINS = {
    "vbpl.vn", "vanban.chinhphu.vn", "congbao.chinhphu.vn", "chinhphu.vn", "baochinhphu.vn",
    "bocongan.gov.vn", "moj.gov.vn", "quochoi.vn", "toaan.gov.vn", "tapchitoaan.vn", "tiengchuong.chinhphu.vn",
}


def official_hostname(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    host = (urlsplit(raw).hostname or raw).lower().rstrip(".")
    return host if any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS) else None


def build_source_registry(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata") or {}
        title = item.get("title") or meta.get("title") or meta.get("source") or meta.get("doc_id") or "Nguồn tham khảo"
        url = item.get("canonical_url") or item.get("url") or meta.get("canonical_url") or meta.get("url") or meta.get("source_url")
        doc_id = item.get("doc_id") or meta.get("doc_id") or meta.get("source_id")
        key = str(doc_id or url or title)
        if key in seen:
            continue
        seen.add(key)
        source_type = str(item.get("source_type") or meta.get("source_type") or meta.get("type") or "").lower()
        snippet = str(item.get("snippet") or item.get("content") or meta.get("excerpt") or "").strip()
        result.append({
            "source_id": str(len(result) + 1),
            "title": str(title),
            "source_type": source_type,
            "source_type_label": "Văn bản pháp luật" if source_type == "legal" else "Tin chính thống" if source_type == "news" else "Chính sách" if source_type == "policy" else "Nguồn đính kèm" if source_type == "attachment" else "Nguồn tham khảo",
            "publisher": item.get("publisher") or meta.get("publisher"),
            "official_domain": official_hostname(url) or official_hostname(item.get("official_domain") or meta.get("official_domain")),
            "url": url,
            "canonical_url": url,
            "doc_id": doc_id,
            "snippet": re.sub(r"\s+", " ", snippet)[:320] or None,
        })
    return [{k: v for k, v in source.items() if v not in (None, "")} for source in result]


def evidence_for(intent: str, sources: list[dict]) -> tuple[str, float]:
    legal = [s for s in sources if s.get("source_type") == "legal" and s.get("official_domain")]
    official = [s for s in sources if s.get("official_domain")]
    if intent == "identity":
        return "Căn cứ rõ", 1.0
    if intent == "penalty_question":
        return ("Căn cứ rõ", 0.84) if legal else ("Chưa đủ căn cứ", 0.25)
    if legal:
        return "Căn cứ rõ", 0.82
    if official:
        return "Cần kiểm tra thêm", 0.58
    return "Chưa đủ căn cứ", 0.25


def validate_citations(answer: str, sources: list[dict]) -> str:
    count = len(sources)
    text = re.sub(r"\[(?:S|A)(\d+)\]", lambda m: f"[{m.group(1)}]", answer, flags=re.I)
    def replace(match):
        values = sorted({int(v) for v in re.findall(r"\d+", match.group(1)) if 1 <= int(v) <= count})
        return "[" + ",".join(map(str, values)) + "]" if values else ""
    return re.sub(r"\[([\d,\s]+)\]", replace, text)
