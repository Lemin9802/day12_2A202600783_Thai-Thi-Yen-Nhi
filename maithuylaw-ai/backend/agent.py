from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env.local", override=False)
load_dotenv(ROOT_DIR / ".env", override=False)

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

try:
    from google import genai
except Exception:
    genai = None

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    provider: str
    model: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_called: bool = False

    def usage_dict(self) -> dict[str, Any]:
        return asdict(self) | {"answer": None}


def _usage_value(usage: Any, *names: str) -> int:
    for name in names:
        if isinstance(usage, dict) and name in usage:
            return int(usage.get(name) or 0)
        value = getattr(usage, name, None)
        if value is not None:
            return int(value or 0)
    return 0


def _clean_raw_chunk_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[,.;:\-\s]+", "", text)
    text = re.sub(r"\b(score|source_type)\s*=\s*[\w.:-]+", "", text, flags=re.I)
    text = re.sub(r"\((legal|news|realtime|attachment)[^)]*score\s*=\s*[\d.]+[^)]*\)", "", text, flags=re.I)
    return text.strip()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_from_item(item: Any) -> str:
    if isinstance(item, str): return item
    if not isinstance(item, dict): return ""
    for key in ("text", "content", "page_content", "preview"):
        value = item.get(key)
        if isinstance(value, str) and value.strip(): return value
    return ""


def _meta_from_item(item: Any) -> dict:
    if not isinstance(item, dict): return {}
    meta = item.get("metadata") or {}
    return meta if isinstance(meta, dict) else {}


def _source_title(item: Any, fallback: str) -> str:
    meta = _meta_from_item(item)
    if isinstance(item, dict):
        for key in ("title", "name", "filename", "source"):
            value = item.get(key)
            if isinstance(value, str) and value.strip(): return value.strip()
    for key in ("title", "source", "doc_id", "path"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip(): return value.strip()
    return fallback


_HIDDEN_USER_TERMS = ("dataset", "rag", "backend", "metadata", "score", "provider", "fallback", "build production", "crawler/local", "index production")


def _strip_internal_context_labels(text: str) -> str:
    text = str(text or "")
    for pattern in (r"\bKey context for RAG\b\s*[-:]*\s*", r"\bKey context\b\s*[-:]*\s*", r"\bSummary\b\s*[-:]*\s*", r"\bRAG\b\s*[-:]*\s*", r"\bUse for\b\s*[-:]*\s*"):
        text = re.sub(pattern, "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _has_hidden_user_term(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in _HIDDEN_USER_TERMS) or "key context" in lowered or "summary" in lowered


def _is_identity_question(question: str) -> bool:
    q = str(question or "").lower()
    return "maithuylaw" in q.replace(" ", "") and any(term in q for term in ("là gì", "la gi", "nghĩa là gì", "nghia la gi", "vì sao tên", "vi sao ten"))


def _identity_answer(language: str) -> str:
    if language == "en":
        return "MaiThuyLaw combines “Mai Thúy” and “Law”. It is an AI assistant for Vietnamese drug-related law, policy, and official sources."
    return "MaiThuyLaw là tên dự án ghép từ “Mai Thúy” và “Law”. “Mai Thúy” là cách nói lái/đọc trại vui của “ma túy” trong tiếng Việt, còn “Law” là luật."


def _is_drug_definition_question(question: str) -> bool:
    q = str(question or "").lower()
    return any(term in q for term in ("ma túy là gì", "ma tuy la gi", "chất ma túy là gì", "chat ma tuy la gi", "định nghĩa ma túy", "dinh nghia ma tuy"))


def _is_low_value_for_question(question: str, sentence: str) -> bool:
    lowered = str(sentence or "").lower()
    if _has_hidden_user_term(lowered): return True
    if _is_drug_definition_question(question):
        concept_terms = ("chất ma túy", "chat ma tuy", "danh mục", "danh muc", "tiền chất", "tien chat")
        generic = ("nhiệm vụ", "phòng, chống", "công an", "tái hòa nhập", "hệ thống chính trị")
        if any(term in lowered for term in generic) and not any(term in lowered for term in concept_terms): return True
    return False


def _clean_context_text(text: str) -> str:
    text = _strip_internal_context_labels(_clean_raw_chunk_text(text))
    if "**Content level:**" in text:
        text = re.sub(r"(?is)^.*?\*\*Content level:\*\*.*?(?:article text|source card)\.\s*", "", text, count=1)
    text = re.sub(r"Do not use for[^.]+\.?", "", text, flags=re.I)
    text = re.sub(r"Không dùng thay cho căn cứ pháp luật chính thức\s*-?", "", text, flags=re.I)
    return text.strip()


def _clean_answer(text: str) -> str:
    text = text or ""
    text = re.sub(r"\((legal|news|realtime|attachment)[^)]*score\s*=\s*[\d.]+[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\b(source_type|score)\s*=\s*[\w.:-]+", "", text, flags=re.I)
    text = re.sub(r"Do not use for[^.]+\.?", "", text, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _is_sanction_question(question: str) -> bool:
    q = str(question or "").lower()
    return any(term in q for term in ("sử dụng trái phép", "su dung trai phep", "bị xử lý", "bi xu ly", "xử lý thế nào", "xu ly the nao", "xử phạt", "xu phat", "bị phạt", "bi phat", "mức phạt", "hình phạt", "trách nhiệm hình sự"))


def _has_direct_sanction_evidence(question: str, items: list[Any]) -> bool:
    for item in items or []:
        meta = _meta_from_item(item)
        source_type = str(meta.get("source_type") or meta.get("type") or "").lower()
        if source_type != "legal": continue
        blob = " ".join([_source_title(item, ""), _text_from_item(item), " ".join(str(v) for v in meta.values())]).lower()
        if any(term in blob for term in ("xử phạt", "bị phạt", "phạt tiền", "trách nhiệm hình sự", "xử lý vi phạm hành chính", "mức phạt", "hình phạt")):
            return True
    return False


def _insufficient_sanction_answer(language: str) -> str:
    if language == "en": return "I do not yet see direct legal authority in the available sources to state the exact sanction. Please provide an article number, document, or official link."
    return "Mình chưa thấy căn cứ pháp lý đủ trực tiếp trong nguồn hiện có để kết luận chính xác mức xử lý. Bạn có thể gửi số điều, tên văn bản hoặc link nguồn chính thống để mình đối chiếu."


def _build_context(items: list[Any], prefix: str, start_index: int = 1) -> str:
    blocks = []
    for index, item in enumerate(items[:8], start_index):
        body = _clean_context_text(_text_from_item(item))
        if body: blocks.append(f"[{index}] {_source_title(item, f'Nguồn {index}')}\n{body[:1800]}")
    return "\n\n".join(blocks)


def _build_attachment_context(items: list[Any], start_index: int = 1) -> str:
    blocks = []
    for index, item in enumerate(items[:4], start_index):
        if not isinstance(item, dict) or item.get("verdict") != "accepted": continue
        preview = _clean_context_text(item.get("preview") or item.get("text") or item.get("content") or "")
        if preview: blocks.append(f"[{index}] {item.get('name') or item.get('filename') or f'Đính kèm {index}'}\n{preview[:1800]}")
    return "\n\n".join(blocks)


def _sentence_candidates(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?…])\s+|\n+", _clean_context_text(text))
    out = []
    for piece in pieces:
        sentence = _strip_internal_context_labels(re.sub(r"\s+", " ", piece).strip(" -•\t\r\n"))
        if len(sentence) >= 45 and not _has_hidden_user_term(sentence) and sentence not in out: out.append(sentence)
    return out


def _fallback_answer(question: str, retrieved: list[Any], attachments: list[Any], language: str) -> str:
    if _is_sanction_question(question) and not attachments and not _has_direct_sanction_evidence(question, retrieved):
        return _insufficient_sanction_answer(language)
    candidates: list[tuple[int, str]] = []
    if attachments:
        source_items = list(enumerate(attachments[:4], len(retrieved) + 1))
        for source_id, item in source_items:
            if not isinstance(item, dict) or item.get("verdict") != "accepted":
                continue
            text = item.get("preview") or item.get("text") or item.get("content") or ""
            for sentence in _sentence_candidates(text):
                if not _is_low_value_for_question(question, sentence):
                    candidates.append((source_id, sentence))
                    break
    else:
        for source_id, item in enumerate(retrieved[:5], 1):
            for sentence in _sentence_candidates(_text_from_item(item)):
                if not _is_low_value_for_question(question, sentence):
                    candidates.append((source_id, sentence))
                    break
    candidates = candidates[:4]
    if not candidates:
        return "I do not yet see enough direct basis in the available sources." if language == "en" else "Mình chưa thấy căn cứ đủ trực tiếp trong nguồn hiện có để trả lời chắc chắn. Bạn có thể hỏi cụ thể hơn hoặc gửi link/số điều từ nguồn chính thống để mình đối chiếu."
    bullets = "\n".join(f"- {sentence} [{source_id}]" for source_id, sentence in candidates)
    if language == "en":
        return "## Brief answer\nI found related controlled sources.\n\n## Key points\n" + bullets + "\n\n## Note\nCheck the original document for a concrete case."
    return "## Tóm tắt ngắn\nMình tìm thấy các nguồn được kiểm soát có liên quan.\n\n## Điểm chính\n" + bullets + "\n\n## Lưu ý\nVới trường hợp cụ thể, bạn nên đối chiếu văn bản gốc hoặc hỏi cơ quan có thẩm quyền."


def _gemini_settings() -> tuple[str, str] | None:
    if LLM_PROVIDER in {"none", "off", "false", "0"}: return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key or genai is None: return None
    return api_key, DEFAULT_GEMINI_MODEL or "gemini-3.1-flash-lite"


def generate_answer_with_usage(*args: Any, **kwargs: Any) -> GenerationResult:
    question = kwargs.get("question") or kwargs.get("message") or kwargs.get("query") or (args[0] if args and isinstance(args[0], str) else "")
    retrieved = kwargs.get("retrieved") or kwargs.get("dataset_results") or kwargs.get("sources") or kwargs.get("context") or kwargs.get("matches") or []
    attachments = kwargs.get("attachments") or kwargs.get("attachment_contexts") or []
    language = "en" if str(kwargs.get("language") or kwargs.get("lang") or "vi").lower().startswith("en") else "vi"
    if _is_identity_question(question):
        return GenerationResult(_identity_answer(language), provider="deterministic")
    retrieved_list, attachment_list = _as_list(retrieved), _as_list(attachments)
    settings = _gemini_settings()
    if not settings:
        return GenerationResult(_fallback_answer(question, retrieved_list, attachment_list, language), provider="fallback")
    instructions = (
        "You are MaiThuyLaw AI. Use only controlled sources. Never invent legal rules, sanctions, article numbers, document names, or citations. Cite only numeric source IDs such as [1] or [1,2]. Do not expose technical internals."
        if language == "en" else
        "Bạn là MaiThuyLaw AI. Chỉ sử dụng nội dung trong các nguồn được cung cấp. "
        "Không tự bịa điều luật, mức phạt, số điều, tên văn bản hoặc thông tin ngoài nguồn. "
        "Mỗi ý trả lời có nội dung thực chất phải kết thúc bằng mã nguồn số như [1] hoặc [1,2]. "
        "Khi có tài liệu đính kèm, hãy đọc và ưu tiên trả lời trực tiếp từ tài liệu đó. "
        "Không lộ thông tin kỹ thuật nội bộ."
    )
    prompt = f"{instructions}\n\nCâu hỏi:\n{question}\n\nNguồn:\n{_build_context(retrieved_list, 'S', 1) or '(Không có)'}\n\nĐính kèm:\n{_build_attachment_context(attachment_list, len(retrieved_list) + 1) or '(Không có)'}"
    api_key, model = settings
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt, config={"temperature": 0.2, "max_output_tokens": 900})
        answer = _clean_answer(getattr(response, "text", "") or "")
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = _usage_value(usage, "prompt_token_count", "prompt_tokens")
        output_tokens = _usage_value(usage, "candidates_token_count", "output_tokens")
        total_tokens = _usage_value(usage, "total_token_count", "total_tokens") or prompt_tokens + output_tokens
        if answer:
            if _is_sanction_question(question) and not attachment_list and not _has_direct_sanction_evidence(question, retrieved_list):
                answer = _insufficient_sanction_answer(language)
            return GenerationResult(
                answer=answer,
                provider="gemini",
                model=model,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                llm_called=True,
            )
    except Exception:
        pass
    return GenerationResult(_fallback_answer(question, retrieved_list, attachment_list, language), provider="fallback", model=model)


def generate_answer(*args: Any, **kwargs: Any) -> str:
    return generate_answer_with_usage(*args, **kwargs).answer
