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


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()


def _clean_raw_chunk_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^[,.;:\-\s]+", "", text)
    text = re.sub(r"\b(score|source_type)\s*=\s*[\w.:-]+", "", text, flags=re.I)
    text = re.sub(r"\((legal|news|realtime|attachment)[^)]*score\s*=\s*[\d.]+[^)]*\)", "", text, flags=re.I)
    text = text.strip()

    markers = [
        "Điều ", "Khoản ", "Quyết định ", "Nghị định ", "Thông tư ", "Pháp lệnh ",
        "Theo ", "Ủy ban ", "Bộ Công an ", "Tòa án ", "Cơ quan ", "Người ",
        "Trường hợp ", "Hồ sơ ", "Thủ tục ", "Kỳ đánh giá", "Địa bàn ", "Tuyến ",
    ]
    first = None
    for marker in markers:
        idx = text.find(marker)
        if idx > 0:
            first = idx if first is None else min(first, idx)
    if first is not None:
        text = text[first:].strip()

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
    text = _clean_raw_chunk_text(text)
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
            if any(term in blob for term in unlawful_use_subject) and any(term in blob for term in direct_legal_consequence):
                return True
            continue
        if any(term in blob for term in general_subject) and any(term in blob for term in direct_legal_consequence + rehab_consequence):
            return True
    return False


def _insufficient_sanction_answer(language: str) -> str:
    if language == "en":
        return "\n".join([
            "## Not enough direct legal basis",
            "I found related materials, but they do not directly answer the exact legal consequence for unlawful drug use.",
            "",
            "## What you can do next",
            "- Ask specifically about compulsory rehabilitation if that is the situation you want to understand.",
            "- Provide an article number, document name, or official link so I can compare it directly.",
            "",
            "## Note",
            "For legal consequences, I should not infer a sanction from related news or indirect documents.",
        ])
    return "\n".join([
        "## Chưa đủ căn cứ trực tiếp",
        "Mình tìm thấy một số nguồn liên quan, nhưng các nguồn hiện có chưa đủ trực tiếp để kết luận chính xác hành vi này sẽ bị xử lý như thế nào.",
        "",
        "## Bạn có thể làm tiếp",
        "- Nếu bạn đang hỏi về cai nghiện bắt buộc, mình có thể giải thích riêng quy trình và thẩm quyền áp dụng.",
        "- Nếu bạn có số điều, tên văn bản hoặc link nguồn chính thống, hãy gửi vào để mình đối chiếu cụ thể hơn.",
        "",
        "## Lưu ý",
        "Với câu hỏi về mức phạt hoặc hậu quả pháp lý, mình sẽ không suy diễn từ nguồn chỉ liên quan gián tiếp.",
    ])


def _build_context(items: list[Any], prefix: str) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items[:8], 1):
        title = _source_title(item, f"Nguồn {index}")
        body = _clean_context_text(_text_from_item(item))
        if not body:
            continue
        blocks.append(f"[{prefix}{index}] {title}\n{body[:1800]}")
    return "\n\n".join(blocks)


def _build_attachment_context(items: list[Any]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(items[:4], 1):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("filename") or f"Đính kèm {index}"
        verdict = item.get("verdict") or "needs_review"
        preview = _clean_context_text(item.get("preview") or item.get("text") or item.get("content") or "")
        if not preview:
            continue
        blocks.append(f"[A{index}] {name} | verdict={verdict}\n{preview[:1800]}")
    return "\n\n".join(blocks)


def _sentence_candidates(text: str) -> list[str]:
    cleaned = _clean_context_text(text)
    pieces = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    out: list[str] = []
    for piece in pieces:
        sentence = piece.strip(" -•\t\r\n")
        if len(sentence) < 45:
            continue
        if re.search(r"\b[a-z]+-[a-z]+-[a-z]+", sentence.lower()):
            continue
        out.append(sentence[:260].rstrip(" ,.;") + ".")
    return out


def _fallback_answer(question: str, retrieved: list[Any], attachments: list[Any], language: str) -> str:
    if _is_sanction_question(question) and not attachments and not _has_direct_sanction_evidence(question, retrieved):
        return _insufficient_sanction_answer(language)

    context = _build_attachment_context(attachments) or _build_context(retrieved, "S")
    snippets: list[str] = []
    for block in context.split("\n\n")[:5]:
        body = " ".join(block.splitlines()[1:])
        for sentence in _sentence_candidates(body):
            if sentence not in snippets:
                snippets.append(sentence)
            if len(snippets) >= 4:
                break
        if len(snippets) >= 4:
            break

    if language == "en":
        if not snippets:
            return "I found related official sources, but they are not clear enough to summarize confidently. Please provide a more specific document, article number, or official link."
        lines = [
            "## Brief answer",
            "I found related official materials. The AI drafting layer is not available right now, so here is a cautious source-based summary.",
            "",
            "## Key points",
        ]
    else:
        if not snippets:
            return "Mình tìm thấy nguồn liên quan, nhưng nội dung trích được chưa đủ rõ để trả lời chắc chắn. Bạn có thể hỏi cụ thể hơn hoặc gửi link/số điều cần đối chiếu."
        lines = [
            "## Tóm tắt ngắn",
            "Mình tìm thấy một số nguồn chính thống liên quan. Dưới đây là phần tóm tắt thận trọng dựa trên nguồn hiện có.",
            "",
            "## Điểm chính",
        ]

    lines.extend(f"- {snippet}" for snippet in snippets)
    if language == "en":
        lines.extend(["", "## Note", "This is a source-based summary. For a concrete case, check the original document or consult a competent authority."])
    else:
        lines.extend(["", "## Lưu ý", "Với trường hợp cụ thể, bạn vẫn nên đối chiếu văn bản gốc hoặc hỏi cơ quan/chuyên gia có thẩm quyền."])
    return "\n".join(lines)


def _gemini_settings() -> tuple[str, str] | None:
    if LLM_PROVIDER in {"none", "off", "false", "0"}:
        return None
    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key or genai is None:
        return None
    model = DEFAULT_GEMINI_MODEL or "gemini-1.5-flash"
    return api_key, model


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

    settings = _gemini_settings()
    if not settings:
        return _fallback_answer(question, retrieved_list, attachment_list, language)

    if language == "en":
        instructions = """
You are MaiThuyLaw AI, a careful legal information assistant for Vietnam drug-related law, policy, and official news.
Use only the provided sources and attachments. Do not invent legal rules, article numbers, sanctions, or citations.
Write for a normal user, not an engineer. Avoid words like dataset, RAG, backend, metadata, score, provider, fallback, or configuration.
If sources are directly relevant, explain the answer in clear practical language with 3-5 useful bullet points.
If sources are related but not direct enough, say that the evidence is not direct enough and suggest what source or search would help.
Use short headings: Brief answer, Key points, What this means, Note.
Cite sources briefly as [S1], [S2], [A1] when you rely on them.
Never provide operational guidance for illegal drug activity, evasion, concealment, or lawbreaking.
""".strip()
    else:
        instructions = """
Bạn là MaiThuyLaw AI, trợ lý thông tin pháp luật cẩn trọng về pháp luật, chính sách và nguồn tin chính thống liên quan đến ma túy tại Việt Nam.
Chỉ dựa trên nguồn được cung cấp trong phần nguồn tham khảo và nội dung đính kèm. Không tự bịa điều luật, mức phạt, số điều, tên văn bản hoặc trích dẫn.
Viết cho người dùng phổ thông đang cần hiểu vấn đề, không viết kiểu kỹ thuật. Không dùng các từ như dataset, RAG, backend, metadata, score, provider, fallback hoặc cấu hình.
Nếu nguồn đủ liên quan, hãy trả lời thật hữu ích: nêu quy trình/ý chính/điều kiện/thẩm quyền theo cách dễ hiểu, có 3-5 gạch đầu dòng cụ thể.
Nếu nguồn chỉ liên quan gián tiếp và chưa đủ căn cứ trực tiếp, hãy nói nhẹ nhàng rằng hiện chưa đủ căn cứ để kết luận chắc chắn và gợi ý người dùng tìm nguồn chính thống mới hơn hoặc gửi số điều/link văn bản.
Ưu tiên heading mềm mại: Tóm tắt ngắn, Điểm chính, Người dùng cần lưu ý, Nguồn liên quan.
Dùng citation ngắn như [S1], [S2], [A1] khi dựa vào nguồn.
Không đưa hướng dẫn nguy hiểm, lách luật, che giấu, né xử lý hoặc thực hiện hành vi liên quan đến ma túy.
""".strip()

    prompt = f"""
{instructions}

Câu hỏi của người dùng:
{question}

Nguồn tham khảo đã qua kiểm soát:
{context or "(Chưa có nguồn phù hợp.)"}

Nội dung file/link đính kèm nếu có:
{attachment_context or "(Không có đính kèm.)"}

Hãy trả lời như một sản phẩm pháp luật AI dành cho người dùng cuối: rõ ràng, mềm mại, đúng phạm vi, không thô kỹ thuật.
""".strip()

    api_key, model = settings
    try:
        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0.2, "max_output_tokens": 900},
            )
        except TypeError:
            response = client.models.generate_content(model=model, contents=prompt)
        answer = _clean_answer(getattr(response, "text", "") or "")
        if answer:
            if _is_sanction_question(question) and not attachment_list and not _has_direct_sanction_evidence(question, retrieved_list):
                return _insufficient_sanction_answer(language)
            return answer
    except Exception:
        pass

    return _fallback_answer(question, retrieved_list, attachment_list, language)
