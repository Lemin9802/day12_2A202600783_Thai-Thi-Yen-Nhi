from __future__ import annotations

import os
import re
from typing import Literal

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None


Language = Literal["vi", "en"]


STOP_PREFIXES = [
    "tóm tắt link này giúp tôi",
    "tóm tắt link này",
    "tóm tắt file này",
    "kiểm tra nguồn này",
    "hãy kiểm tra",
    "giúp tôi",
    "cho tôi biết",
    "vui lòng",
]


def _clean_message(message: str) -> str:
    text = re.sub(r"https?://\S+", " nguồn ", message or "")
    text = re.sub(r"\s+", " ", text).strip(" .,:;!?\"'")
    lowered = text.lower()
    for prefix in STOP_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip(" .,:;!?\"'")
            lowered = text.lower()
    return text or "Cuộc trò chuyện mới"


def fallback_title(message: str, language: Language = "vi") -> str:
    text = _clean_message(message)

    replacements = {
        "Thông tin từ 2025 về phòng chống ma túy ở Việt Nam có gì đáng chú ý": "Phòng chống ma túy ở Việt Nam 2025",
        "Vậy còn cơ sở cai nghiện bắt buộc thì sao": "Cơ sở cai nghiện bắt buộc",
        "Tóm tắt nguồn về ma túy": "Tóm tắt nguồn về ma túy",
    }

    normalized = text.strip(" ?.!:")
    for key, value in replacements.items():
        if key.lower() in normalized.lower():
            return value if language == "vi" else "Vietnam Drug Prevention Policy"

    if language == "en":
        if "cai nghiện" in normalized.lower():
            return "Compulsory Rehabilitation Rules"
        if "phòng chống ma túy" in normalized.lower():
            return "Vietnam Drug Prevention Policy"
        if "nguồn" in normalized.lower() or "link" in normalized.lower():
            return "Official Source Review"

    words = normalized.split()
    title = " ".join(words[:9])
    title = title[:58].rstrip(" ,.;:-")
    if not title:
        title = "Cuộc trò chuyện mới" if language == "vi" else "New conversation"

    return title[0].upper() + title[1:]


def _sanitize_title(title: str, language: Language) -> str:
    title = re.sub(r"[\n\r\t]+", " ", title or "")
    title = re.sub(r'^[\'"“”`]+|[\'"“”`]+$', "", title.strip())
    title = re.sub(r"\s+", " ", title)
    title = title.strip(" .,:;!?-–—")

    if len(title) > 64:
        title = title[:64].rstrip(" ,.;:-–—")

    if not title:
        return "Cuộc trò chuyện mới" if language == "vi" else "New conversation"

    return title


def generate_chat_title(message: str, language: Language = "vi") -> str:
    fallback = fallback_title(message, language)

    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()

    if not api_key or genai is None:
        return fallback

    language_name = "Vietnamese" if language == "vi" else "English"

    prompt = f"""
You create short, professional chat titles for a legal information assistant.

Language: {language_name}
Rules:
- 4 to 8 words if possible.
- No emoji.
- No quotation marks.
- No trailing punctuation.
- Do not mention "chat", "conversation", or "question".
- Keep Vietnamese legal terms accurate if the title is Vietnamese.
- If the user pasted a URL, summarize the topic as "source review" or "tóm tắt nguồn", not the URL.

User's first message:
{message}

Return only the title.
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        title = _sanitize_title(getattr(response, "text", "") or "", language)
        return title or fallback
    except Exception:
        return fallback
