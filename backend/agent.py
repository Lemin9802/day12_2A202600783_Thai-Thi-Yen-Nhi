from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env.local", override=False)
load_dotenv(ROOT_DIR / ".env", override=False)


import os
import re
from typing import Any

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None



def _clean_raw_chunk_text(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"^[,.;:\-\s]+", "", value)

    # If a chunk starts mid-word/mid-sentence, trim to the first reasonable legal marker.
    markers = [
        "Điều ",
        "Khoản ",
        "Quyết định ",
        "Nghị định ",
        "Thông tư ",
        "Pháp lệnh ",
        "Theo ",
        "Ủy ban ",
        "Lực lượng ",
        "Kỳ đánh giá",
        "Địa bàn ",
        "Tuyến ",
    ]

    first = None
    for marker in markers:
        idx = value.find(marker)
        if idx > 0:
            first = idx if first is None else min(first, idx)

    if first is not None:
        value = value[first:].strip()

    # Drop badly truncated fragments that still begin lowercase.
    if value and value[0].islower():
        parts = re.split(r"(?<=[.!?])\s+", value)
        parts = [p for p in parts if p and not p[0].islower()]
        value = " ".join(parts).strip() or value

    return value


def _extract_clean_sentences(chunks, limit: int = 5) -> list[str]:
    sentences = []
    seen = set()

    for item in chunks or []:
        if isinstance(item, dict):
            raw = item.get("text") or item.get("content") or item.get("page_content") or ""
        else:
            raw = getattr(item, "text", "") or getattr(item, "content", "") or str(item)

        cleaned = _clean_raw_chunk_text(raw)
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned):
            sentence = sentence.strip(" -•\t\r\n")
            if len(sentence) < 45:
                continue
            if sentence and sentence[0].islower():
                continue
            key = sentence[:120].lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)

            if len(sentences) >= limit:
                return sentences

    return sentences


def _clean_fallback_answer(answer: str) -> str:
    text = str(answer or "")

    bad_markers = [
        "Mình tìm thấy một số thông tin liên quan trong tài liệu hiện có.",
        "Thông tin từ dataset hiện có",
        "Trả lời từ dataset",
        "Đối chiếu",
    ]

    for marker in bad_markers:
        text = text.replace(marker, "")

    lines = []
    for line in text.splitlines():
        stripped = line.strip()

        # Remove raw broken bullets such as "- iên tỉnh..." / "- ó thường xuyên..."
        if stripped.startswith("- "):
            body = stripped[2:].strip()
            if body and body[0].islower():
                continue
            if len(body) < 35:
                continue

        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_from_item(item: Any) -> str:
    if isinstance(item, str):
        return item

    if not isinstance(item, dict):
        return ""

    for key in ("text", "content", "page_content", "preview"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return ""


def _meta_from_item(item: Any) -> dict:
    if not isinstance(item, dict):
        return {}

    meta = item.get("metadata") or {}
    return meta if isinstance(meta, dict) else {}


def _source_title(item: Any, fallback: str) -> str:
    meta = _meta_from_item(item)

    if isinstance(item, dict):
        for key in ("title", "name", "filename", "source"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    for key in ("title", "source", "doc_id", "path"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return fallback


def _clean_context_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\((legal|news|realtime|attachment)[^)]*score\s*=\s*[\d.]+[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\b(score|source_type)\s*=\s*[\w.:-]+", "", text, flags=re.I)
    text = re.sub(r"Do not use for[^.]+\.?", "", text, flags=re.I)
    text = re.sub(r"Không dùng thay cho căn cứ pháp luật chính thức\s*-?", "", text, flags=re.I)
    return text.strip()


def _clean_answer(text: str) -> str:
    text = text or ""
    text = re.sub(r"\((legal|news|realtime|attachment)[^)]*score\s*=\s*[\d.]+[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\bsource_type\s*=\s*[\w.:-]+", "", text, flags=re.I)
    text = re.sub(r"\bscore\s*=\s*[\d.]+", "", text, flags=re.I)
    text = re.sub(r"Do not use for[^.]+\.?", "", text, flags=re.I)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_sanction_question(question: str) -> bool:
    q = str(question or "").lower()
    return any(term in q for term in (
        "sử dụng trái phép", "su dung trai phep", "bị xử lý", "bi xu ly",
        "xử lý thế nào", "xu ly the nao", "xử phạt", "xu phat",
        "bị phạt", "bi phat", "mức phạt", "muc phat", "hình phạt",
        "trách nhiệm hình sự", "trach nhiem hinh su",
    ))


def _asks_unlawful_use(question: str) -> bool:
    q = str(question or "").lower()
    return any(term in q for term in (
        "sử dụng trái phép", "su dung trai phep",
        "sử dụng ma túy trái phép", "su dung ma tuy trai phep",
    ))


def _has_direct_sanction_evidence(question: str, items: list[Any]) -> bool:
    unlawful_use_query = _asks_unlawful_use(question)

    unlawful_use_subject = (
        "sử dụng trái phép", "su dung trai phep",
        "sử dụng ma túy trái phép", "su dung ma tuy trai phep",
        "người sử dụng trái phép", "nguoi su dung trai phep",
    )
    general_subject = (
        "sử dụng trái phép", "su dung trai phep", "người sử dụng", "nguoi su dung",
        "người nghiện", "nguoi nghien", "nghiện ma túy", "nghien ma tuy",
    )
    direct_legal_consequence = (
        "xử phạt", "xu phat", "bị phạt", "bi phat", "phạt tiền", "phat tien",
        "cảnh cáo", "canh cao", "trách nhiệm hình sự", "trach nhiem hinh su",
        "xử lý vi phạm hành chính", "xu ly vi pham hanh chinh",
        "mức phạt", "muc phat", "hình phạt", "hinh phat",
    )
    rehab_consequence = (
        "biện pháp xử lý hành chính", "bien phap xu ly hanh chinh",
        "cai nghiện bắt buộc", "cai nghien bat buoc",
        "đưa vào cơ sở cai nghiện", "dua vao co so cai nghien",
    )

    for item in items or []:
        meta = _meta_from_item(item)
        blob = " ".join([
            _source_title(item, ""),
            _text_from_item(item),
            " ".join(str(v) for v in meta.values()),
        ]).lower()

        if unlawful_use_query:
            # A document about "người nghiện" / compulsory rehabilitation is not
            # a direct basis for the exact sanction of unlawful drug use unless it
            # explicitly covers unlawful use and a concrete legal consequence.
            if any(term in blob for term in unlawful_use_subject) and any(term in blob for term in direct_legal_consequence):
                return True
            continue

        if any(term in blob for term in general_subject) and any(term in blob for term in direct_legal_consequence + rehab_consequence):
            return True
    return False


def _insufficient_sanction_answer(language: str) -> str:
    if language == "en":
        return "\n".join([
            "## Insufficient evidence",
            "The current MaiThuyLaw dataset does not contain a direct legal basis that is clear enough to answer the exact sanction for unlawful drug use.",
            "",
            "## What I can still help with",
            "- I can look up related rules on compulsory rehabilitation if you ask specifically about rehabilitation measures.",
            "- I can answer about a specific official document if you provide its link or article number.",
            "",
            "## Note",
            "For a concrete case, check the original legal document or ask a competent authority or lawyer.",
        ])

    return "\n".join([
        "## Chưa đủ căn cứ",
        "Tài liệu hiện có chưa có căn cứ pháp lý trực tiếp và đủ rõ để trả lời chính xác mức xử lý đối với hành vi sử dụng trái phép chất ma túy.",
        "",
        "## Có thể tra cứu tiếp",
        "- Nếu bạn hỏi riêng về biện pháp cai nghiện bắt buộc, mình có thể đối chiếu các nguồn hiện có về thủ tục và thẩm quyền.",
        "- Nếu bạn có số điều, tên văn bản hoặc link văn bản chính thống, bạn có thể gửi vào để mình đối chiếu cụ thể hơn.",
        "",
        "## Lưu ý",
        "Không nên suy diễn mức phạt từ các nguồn tin vụ án hoặc văn bản không điều chỉnh trực tiếp hành vi đang hỏi.",
    ])


def _build_context(items: list[Any], prefix: str) -> str:
    blocks = []

    for index, item in enumerate(items[:8], 1):
        title = _source_title(item, f"Nguồn {index}")
        body = _clean_context_text(_text_from_item(item))

        if not body:
            continue

        blocks.append(f"[{prefix}{index}] {title}\n{body[:1800]}")

    return "\n\n".join(blocks)


def _build_attachment_context(items: list[Any]) -> str:
    blocks = []

    for index, item in enumerate(items[:4], 1):
        if not isinstance(item, dict):
            continue

        name = item.get("name") or item.get("filename") or f"Đính kèm {index}"
        verdict = item.get("verdict") or "needs_review"
        preview = _clean_context_text(
            item.get("preview") or item.get("text") or item.get("content") or ""
        )

        if not preview:
            continue

        blocks.append(f"[A{index}] {name} | verdict={verdict}\n{preview[:1800]}")

    return "\n\n".join(blocks)


def _fallback_answer(question: str, retrieved: list[Any], attachments: list[Any], language: str) -> str:
    if _is_sanction_question(question) and not attachments and not _has_direct_sanction_evidence(question, retrieved):
        return _insufficient_sanction_answer(language)

    context = _build_attachment_context(attachments) or _build_context(retrieved, "S")
    snippets = []

    for block in context.split("\n\n")[:4]:
        body = " ".join(block.splitlines()[1:])
        body = _clean_context_text(body)
        if body:
            snippets.append(body[:260].rstrip(" ,.;") + ".")

    if language == "en":
        lines = [
            "## Brief answer",
            "I found relevant information in the available materials, but the AI drafting service is temporarily unavailable.",
            "",
            "## Key points",
        ]
        if snippets:
            lines.extend(f"- {snippet}" for snippet in snippets)
        else:
            lines.append("- I could not find a sufficiently clear excerpt to summarize with confidence.")

        lines.extend(["", "## References"])
    else:
        lines = [
            "## Tóm tắt ngắn",
            "Mình tìm thấy một số thông tin liên quan trong tài liệu hiện có.",
            "",
            "## Các điểm đáng chú ý",
        ]
        if snippets:
            lines.extend(f"- {snippet}" for snippet in snippets)
        else:
            lines.append("- Chưa tìm thấy đoạn trích đủ rõ để tóm tắt chắc chắn.")

        lines.extend(["", "## Nguồn tham khảo"])

    for index, item in enumerate(retrieved[:5], 1):
        lines.append(f"- [S{index}] {_source_title(item, f'Nguồn {index}')}")

    for index, item in enumerate(attachments[:3], 1):
        if isinstance(item, dict):
            lines.append(f"- [A{index}] {item.get('name') or item.get('filename') or 'Đính kèm'}")

    if language == "en":
        lines.extend([
            "",
            "## Note",
            "This information is for reference only. For a specific case, check the original legal documents or consult a competent authority.",
        ])
    else:
        lines.extend([
            "",
            "## Lưu ý",
            "Thông tin chỉ phục vụ tra cứu. Với vụ việc cụ thể, nên đối chiếu văn bản gốc hoặc hỏi cơ quan/chuyên gia có thẩm quyền.",
        ])

    return "\n".join(lines)


def generate_answer(*args: Any, **kwargs: Any) -> str:
    question = (
        kwargs.get("question")
        or kwargs.get("message")
        or kwargs.get("query")
        or (args[0] if args and isinstance(args[0], str) else "")
    )

    retrieved = (
        kwargs.get("retrieved")
        or kwargs.get("dataset_results")
        or kwargs.get("sources")
        or kwargs.get("context")
        or kwargs.get("matches")
        or []
    )

    attachments = kwargs.get("attachments") or kwargs.get("attachment_contexts") or []
    language = kwargs.get("language") or kwargs.get("lang") or "vi"
    language = "en" if str(language).lower().startswith("en") else "vi"

    retrieved_list = _as_list(retrieved)
    attachment_list = _as_list(attachments)

    context = _build_context(retrieved_list, "S")
    attachment_context = _build_attachment_context(attachment_list)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "").strip()

    if not api_key or not model or genai is None:
        return _fallback_answer(question, retrieved_list, attachment_list, language)

    if language == "en":
        instructions = """
You are MaiThuyLaw AI, a professional legal information assistant focused on Vietnamese drug-related law, policy, and official news.

Write in English.
Do not expose technical metadata such as score, source_type, dataset, backend, provider, API key, fallback, or configuration.
Do not copy raw broken OCR/chunk text verbatim. Synthesize the meaning into clear, readable points.
If a Vietnamese legal title is important, keep the Vietnamese title and explain it in English.
Use concise headings:
- Brief answer
- Key points
- References
- Note
Use citations like [S1], [S2], [A1] when relying on sources.
Do not include unsafe operational guidance related to illegal drugs.
Do not mention "dataset answer" or "MaiThuyLaw dataset".
""".strip()
    else:
        instructions = """
Bạn là MaiThuyLaw AI, trợ lý thông tin pháp luật chuyên nghiệp về pháp luật, chính sách và nguồn tin chính thống liên quan đến ma túy tại Việt Nam.

Viết bằng tiếng Việt tự nhiên, rõ ràng, lịch sự.
Không để lộ metadata kỹ thuật như score, source_type, dataset, backend, provider, API key, fallback hoặc cấu hình.
Không bê nguyên văn các đoạn OCR/chunk bị lỗi, bị cụt chữ hoặc có lẫn tiếng Anh kỹ thuật. Hãy đọc hiểu và diễn giải lại thành ý chính sạch, đúng nghĩa.
Không viết các heading thô như "Thông tin từ dataset hiện có", "Trả lời từ dataset", "Đối chiếu với nguồn MaiThuyLaw".
Nếu nguồn không có căn cứ trực tiếp cho câu hỏi về mức xử lý, mức phạt hoặc trách nhiệm pháp lý, hãy nói "Chưa đủ căn cứ" thay vì suy diễn từ tin tức hoặc nguồn gián tiếp.
Ưu tiên format:
- Tóm tắt ngắn
- Các điểm đáng chú ý
- Nguồn tham khảo
- Lưu ý
Dùng citation ngắn như [S1], [S2], [A1] khi dựa vào nguồn.
Không đưa hướng dẫn nguy hiểm, lách luật, che giấu hoặc thực hiện hành vi liên quan đến ma túy.
""".strip()

    prompt = f"""
{instructions}

Câu hỏi của người dùng:
{question}

Nguồn từ tài liệu tham khảo:
{context or "(Không có nguồn phù hợp.)"}

Nội dung file/link đính kèm nếu có:
{attachment_context or "(Không có đính kèm.)"}

Hãy trả lời như một sản phẩm pháp luật AI dành cho người dùng cuối: mạch lạc, có đầu mục, dễ đọc, không thô kỹ thuật.
""".strip()

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        answer = _clean_answer(getattr(response, "text", "") or "")
        if answer:
            if _is_sanction_question(question) and not attachment_list and not _has_direct_sanction_evidence(question, retrieved_list):
                return _insufficient_sanction_answer(language)
            return answer
    except Exception:
        pass

    return _fallback_answer(question, retrieved_list, attachment_list, language)
