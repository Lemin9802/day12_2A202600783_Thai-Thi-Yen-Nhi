from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from fastapi import UploadFile

from backend.dataset import retrieve
from backend.guards import detect_safety_issue, is_in_domain

MAX_FILE_BYTES = 2_000_000
MAX_LINK_BYTES = 1_500_000
MAX_TEXT_CHARS = 12_000
MAX_REDIRECTS = 3
ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".pdf", ".docx"}
ALLOWED_SOURCE_DOMAINS = {
    "vbpl.vn",
    "vanban.chinhphu.vn",
    "congbao.chinhphu.vn",
    "baochinhphu.vn",
    "chinhphu.vn",
    "bocongan.gov.vn",
    "moj.gov.vn",
    "quochoi.vn",
    "toaan.gov.vn",
    "tapchitoaan.vn",
    "tiengchuong.chinhphu.vn",
}
ALLOWED_LINK_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/json",
    "text/csv",
    "application/pdf",
)


def clean_text(text: str) -> str:
    value = str(text or "").replace("\x00", " ")
    value = re.sub(r"[\u200b-\u200f\ufeff]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _read_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception:
        return ""


def _read_docx(data: bytes) -> str:
    try:
        from docx import Document

        doc = Document(BytesIO(data))
        return "\n".join(paragraph.text for paragraph in doc.paragraphs)
    except Exception:
        return ""


def _read_plain(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


async def extract_upload_text(file: UploadFile) -> dict:
    filename = Path(file.filename or "uploaded_file").name
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {
            "ok": False,
            "status_code": 415,
            "filename": filename,
            "size_bytes": 0,
            "error": f"Định dạng {ext or '(không rõ)'} chưa được hỗ trợ. Hỗ trợ: txt, md, json, csv, pdf, docx.",
            "text": "",
        }

    data = await file.read(MAX_FILE_BYTES + 1)
    size = len(data)
    if size > MAX_FILE_BYTES:
        return {
            "ok": False,
            "status_code": 413,
            "filename": filename,
            "size_bytes": size,
            "error": "File quá lớn. Giới hạn hiện tại là 2MB.",
            "text": "",
        }

    text = _read_pdf(data) if ext == ".pdf" else _read_docx(data) if ext == ".docx" else _read_plain(data)
    text = clean_text(text)[:MAX_TEXT_CHARS]
    if not text:
        return {
            "ok": False,
            "status_code": 422,
            "filename": filename,
            "size_bytes": size,
            "error": "Không trích xuất được nội dung text từ file.",
            "text": "",
        }
    return {
        "ok": True,
        "status_code": 200,
        "filename": filename,
        "size_bytes": size,
        "error": None,
        "text": text,
    }


def _hostname_allowed(hostname: str) -> bool:
    host = hostname.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in ALLOWED_SOURCE_DOMAINS)


def _resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Không phân giải được tên miền nguồn.") from exc
    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise ValueError("Tên miền nguồn không có địa chỉ hợp lệ.")
    for value in addresses:
        ip = ipaddress.ip_address(value)
        if not ip.is_global:
            raise ValueError("Địa chỉ mạng nội bộ hoặc không công khai không được phép.")
    return addresses


def validate_source_url(url: str) -> dict:
    raw = str(url or "").strip()
    if len(raw) > 2048:
        raise ValueError("URL quá dài.")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("Chỉ hỗ trợ link HTTPS từ nguồn chính thống.")
    if parsed.username or parsed.password:
        raise ValueError("URL chứa thông tin đăng nhập không được phép.")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or not _hostname_allowed(hostname):
        raise ValueError("Tên miền chưa nằm trong danh sách nguồn chính thống được phép.")
    port = parsed.port or 443
    if port != 443:
        raise ValueError("Chỉ hỗ trợ cổng HTTPS tiêu chuẩn.")
    addresses = _resolve_public_addresses(hostname, port)
    normalized = urlunsplit(("https", hostname, parsed.path or "/", parsed.query, ""))
    return {"url": normalized, "hostname": hostname, "addresses": addresses}


def extract_html_text(html: str) -> str:
    raw = html_lib.unescape(str(html or ""))
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav", "aside"]):
            tag.decompose()
        title = ""
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = clean_text(og.get("content", ""))
        if not title and soup.find("h1"):
            title = clean_text(soup.find("h1").get_text(" ", strip=True))
        paragraphs: list[str] = []
        seen: set[str] = set()
        for node in soup.find_all(["p", "h1", "h2", "h3", "li"]):
            value = clean_text(node.get_text(" ", strip=True))
            lowered = value.lower()
            if len(value) < 45 or lowered in seen:
                continue
            if any(term in lowered for term in ("english 中文", "góp ý hiến kế", "doanh nghiệp kiến quốc")):
                continue
            seen.add(lowered)
            paragraphs.append(value)
            if len(" ".join(paragraphs)) >= MAX_TEXT_CHARS:
                break
        text = "\n".join(([title] if title else []) + paragraphs)
        if not text:
            text = (soup.body or soup).get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>|<[^>]+>", " ", raw)
    text = re.sub(r"https?://\S+", " ", html_lib.unescape(text))
    return clean_text(text)[:MAX_TEXT_CHARS]


async def fetch_link_text(url: str) -> dict:
    try:
        import httpx

        current = validate_source_url(url)["url"]
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=4.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for redirect_count in range(MAX_REDIRECTS + 1):
                validate_source_url(current)
                async with client.stream(
                    "GET",
                    current,
                    headers={"User-Agent": "MaiThuyLawAI/1.0 official-source-checker", "Accept": "text/html,text/plain,application/pdf;q=0.8"},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location", "")
                        if not location or redirect_count >= MAX_REDIRECTS:
                            raise ValueError("Link chuyển hướng không hợp lệ hoặc vượt quá giới hạn.")
                        current = validate_source_url(urljoin(current, location))["url"]
                        continue
                    if response.status_code >= 400:
                        return {"ok": False, "url": current, "error": f"Không đọc được link. HTTP {response.status_code}", "text": "", "content_type": ""}
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if not any(content_type.startswith(item) for item in ALLOWED_LINK_CONTENT_TYPES):
                        return {"ok": False, "url": current, "error": "Định dạng nội dung của link chưa được hỗ trợ.", "text": "", "content_type": content_type}
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_LINK_BYTES:
                            return {"ok": False, "url": current, "error": "Nội dung link vượt quá giới hạn 1.5MB.", "text": "", "content_type": content_type}
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if content_type == "application/pdf":
                        text = clean_text(_read_pdf(data))[:MAX_TEXT_CHARS]
                    else:
                        raw = _read_plain(data)
                        text = extract_html_text(raw) if content_type.startswith("text/html") else clean_text(raw)[:MAX_TEXT_CHARS]
                    if not text:
                        return {"ok": False, "url": current, "error": "Không trích xuất được text từ link.", "text": "", "content_type": content_type}
                    return {"ok": True, "url": current, "error": None, "text": text, "content_type": content_type}
        return {"ok": False, "url": url, "error": "Không đọc được link.", "text": "", "content_type": ""}
    except Exception as exc:
        return {"ok": False, "url": str(url or ""), "error": f"Link không hợp lệ: {exc}", "text": "", "content_type": ""}


def _domain_score(text: str) -> float:
    lower = text.lower()
    terms = (
        "ma túy", "ma tuý", "chất ma túy", "tiền chất", "cai nghiện",
        "phòng chống ma túy", "phòng, chống ma túy", "tàng trữ", "vận chuyển",
        "mua bán", "sử dụng trái phép", "bộ luật hình sự", "luật phòng chống ma túy",
    )
    return min(1.0, sum(1 for term in terms if term in lower) / 4)


def _dataset_match_score(text: str) -> tuple[float, list[dict]]:
    results = retrieve(text[:1000], top_k=5)
    return (float(results[0].get("score", 0.0)) if results else 0.0), results


def _looks_explicitly_unrelated(text: str) -> bool:
    lower = text.lower()
    return any(re.search(pattern, lower) for pattern in (r"không liên quan.{0,80}ma túy", r"không liên quan.{0,80}pháp luật", r"nấu ăn", r"du lịch cuối tuần", r"thời trang", r"bóng đá"))


def evaluate_uploaded_text(text: str, *, source_url: str | None = None) -> dict:
    cleaned = clean_text(text)
    safety_reason = detect_safety_issue(cleaned)
    in_domain = is_in_domain(cleaned)
    domain_score = _domain_score(cleaned)
    match_score, matches = _dataset_match_score(cleaned)
    official_domain = None
    if source_url:
        try:
            official_domain = validate_source_url(source_url)["hostname"]
        except ValueError:
            official_domain = None
    official_score = 1.0 if official_domain else 0.0

    if safety_reason:
        verdict = "rejected"
        reason = "Nội dung có dấu hiệu hỗ trợ thực hiện, che giấu hoặc né tránh hành vi vi phạm pháp luật."
    elif _looks_explicitly_unrelated(cleaned) or (not in_domain and domain_score < 0.25):
        verdict = "rejected"
        reason = "Nội dung không nằm trong phạm vi pháp luật, chính sách hoặc thông tin chính thống liên quan đến ma túy."
    elif official_domain and domain_score >= 0.2:
        verdict = "accepted"
        reason = "Nguồn thuộc tên miền chính thống được phép và nội dung phù hợp phạm vi MaiThuyLaw."
    elif domain_score >= 0.3:
        verdict = "needs_review"
        reason = "Nội dung có liên quan nhưng chưa xác minh được nguồn chính thống; chưa được dùng làm căn cứ trả lời."
    else:
        verdict = "rejected"
        reason = "Nội dung chưa đủ phù hợp để dùng làm nguồn trả lời."

    source_matches = []
    for index, item in enumerate(matches[:5], start=1):
        meta = item.get("metadata", {}) or {}
        source_matches.append({
            "source_id": f"S{index}",
            "title": meta.get("title") or meta.get("source") or meta.get("doc_id") or "Nguồn tham khảo",
            "source_type": meta.get("source_type") or meta.get("type") or "unknown",
            "url": meta.get("canonical_url") or meta.get("url") or None,
            "score": float(item.get("score", 0.0)),
        })
    return {
        "verdict": verdict,
        "reason": reason,
        "safety_reason": safety_reason,
        "domain_score": round(domain_score, 3),
        "official_score": official_score,
        "official_domain": official_domain,
        "dataset_match_score": round(match_score, 3),
        "source_matches": source_matches,
        "preview": cleaned[:700],
    }
