"""Deterministic multi-agent orchestration for grounded legal answers.

The agents are deliberately small and side-effect bounded. FastAPI owns request
validation and persistence; this module owns routing-dependent retrieval,
controlled official-source search, evidence merging, answer synthesis, and
output safety review.
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from backend.agent import generate_answer_with_usage
from backend.citations import CitationVerification, verify_citations
from backend.dataset import retrieve
from backend.guards import output_safety_check
from backend.intent import IntentResult
from backend.realtime import realtime_enabled, realtime_unavailable_answer, search_realtime, wants_realtime

SAFE_FALLBACK_VI = (
    "Mình chưa thấy căn cứ đủ trực tiếp trong nguồn hiện có để trả lời chắc chắn. "
    "Bạn có thể hỏi cụ thể hơn hoặc gửi văn bản chính thống để mình đối chiếu."
)
SAFE_FALLBACK_EN = (
    "I do not yet see sufficiently direct support in the available sources. "
    "Please ask a more specific question or provide an official document for comparison."
)

_EXTERNAL_EVIDENCE_TERMS = (
    "doi chieu voi", "so sanh voi", "kiem chung voi", "xac minh voi",
    "theo phap luat hien hanh", "theo quy dinh hien hanh", "can cu phap ly",
    "nguon chinh thong", "tra cuu them", "tim them nguon", "bo sung nguon",
    "dung voi phap luat", "co dung luat", "khac voi quy dinh", "cap nhat moi nhat",
)


def _normalize_request_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def _attachment_mode(message: str, attachments: list[dict]) -> str:
    """Use an attached document as primary context unless the user asks for external comparison."""
    if not attachments:
        return "none"
    normalized = _normalize_request_text(message)
    if any(term in normalized for term in _EXTERNAL_EVIDENCE_TERMS):
        return "hybrid"
    return "attachment_only"


@dataclass
class WorkflowState:
    message: str
    retrieval_query: str
    intent: IntentResult
    attachments: list[dict]
    language: str = "vi"
    controlled_search: bool = False
    top_k: int = 6
    attachment_mode: str = "none"
    dataset_results: list[dict] = field(default_factory=list)
    answer: str = ""
    blocked_reason: str | None = None
    citation_verification: CitationVerification | None = None
    realtime_unavailable: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)
    generation_usage: dict[str, Any] = field(default_factory=dict)

    @property
    def source_count(self) -> int:
        return len(self.dataset_results) + len(self.attachments)

    def record(self, agent: str, started_at: float, **details: Any) -> None:
        self.trace.append({
            "agent": agent,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            **details,
        })


class WorkflowAgent(Protocol):
    name: str

    def run(self, state: WorkflowState) -> WorkflowState: ...


class LegalRetrievalAgent:
    name = "legal_retrieval"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        if state.intent.intent == "identity" or state.attachment_mode == "attachment_only":
            state.dataset_results = []
        else:
            state.dataset_results = retrieve(
                state.retrieval_query,
                top_k=state.top_k,
                source_types=state.intent.required_sources or None,
            )
        state.record(
            self.name,
            started,
            status="ok",
            intent=state.intent.intent,
            required_sources=list(state.intent.required_sources),
            attachment_mode=state.attachment_mode,
            result_count=len(state.dataset_results),
        )
        return state


class PolicyNewsResearchAgent:
    name = "policy_news_research"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        enabled = realtime_enabled()
        should_search = state.controlled_search and enabled and state.attachment_mode != "attachment_only"
        added = 0
        if should_search:
            for item in search_realtime(state.retrieval_query, language=state.language):
                url = item.get("url") or ""
                host = urlsplit(url).hostname or ""
                state.dataset_results.append({
                    "content": item.get("content", ""),
                    "score": 1.0,
                    "metadata": {
                        "title": item.get("title"),
                        "url": url,
                        "canonical_url": url,
                        "source_type": "news",
                        "official_domain": host,
                        "publisher": host,
                    },
                })
                added += 1
        state.realtime_unavailable = bool(
            not state.attachments and wants_realtime(state.message) and not enabled
        )
        state.record(
            self.name,
            started,
            status="ok",
            consented=state.controlled_search,
            enabled=enabled,
            attachment_mode=state.attachment_mode,
            added=added,
            unavailable=state.realtime_unavailable,
        )
        return state


class EvidenceMergeAgent:
    name = "evidence_merge"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        merged: list[dict] = []
        seen: set[str] = set()
        for item in state.dataset_results:
            meta = item.get("metadata") or {}
            key = str(
                meta.get("doc_id")
                or meta.get("canonical_url")
                or meta.get("url")
                or item.get("chunk_id")
                or item.get("content", "")[:160]
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        state.dataset_results = merged[: max(state.top_k, 1)]
        state.record(self.name, started, status="ok", result_count=len(merged))
        return state


class AnswerSynthesisAgent:
    name = "answer_synthesis"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        if state.realtime_unavailable:
            state.answer = realtime_unavailable_answer(state.language)
            mode = "realtime_unavailable"
        else:
            synthesis_message = state.message
            if state.attachment_mode == "attachment_only":
                if state.language == "en":
                    synthesis_message = (
                        "Read the attached document as the primary context and answer only from its content. "
                        "If it is insufficient, state the limitation instead of adding outside information.\n\n"
                        f"User question: {state.message}"
                    )
                else:
                    synthesis_message = (
                        "Hãy tự đọc tài liệu đính kèm như ngữ cảnh chính và chỉ trả lời bằng nội dung có trong tài liệu. "
                        "Nếu tài liệu chưa đủ, hãy nói rõ giới hạn thay vì bổ sung thông tin bên ngoài.\n\n"
                        f"Câu hỏi của người dùng: {state.message}"
                    )
            generation = generate_answer_with_usage(
                message=synthesis_message,
                dataset_results=state.dataset_results,
                attachments=state.attachments,
                language=state.language,
            )
            state.answer = generation.answer
            state.generation_usage = {
                "provider": generation.provider,
                "model": generation.model,
                "prompt_tokens": generation.prompt_tokens,
                "output_tokens": generation.output_tokens,
                "total_tokens": generation.total_tokens,
                "llm_called": generation.llm_called,
            }
            mode = generation.provider
        state.record(
            self.name,
            started,
            status="ok",
            mode=mode,
            attachment_mode=state.attachment_mode,
            answer_chars=len(state.answer),
            usage=state.generation_usage,
        )
        return state


class CitationVerificationAgent:
    name = "citation_verification"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        verification = verify_citations(
            state.answer,
            state.dataset_results,
            state.attachments,
            intent=state.intent.intent,
        )
        if (
            state.attachment_mode == "attachment_only"
            and not verification.invalid_citations
            and not verification.unsupported_claims
        ):
            verification.legal_claims_without_legal_source = []
            verification.valid = True
        state.citation_verification = verification
        if not verification.valid:
            state.blocked_reason = "Citation verification failed"
            state.answer = SAFE_FALLBACK_EN if state.language == "en" else SAFE_FALLBACK_VI
            state.dataset_results = []
        state.record(
            self.name,
            started,
            status="ok",
            valid=verification.valid,
            coverage=verification.coverage,
            attachment_mode=state.attachment_mode,
            unsupported_claims=len(verification.unsupported_claims),
            invalid_citations=verification.invalid_citations,
        )
        return state


class SafetyReviewAgent:
    name = "safety_review"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        allowed, reason = output_safety_check(state.answer, state.source_count)
        if not allowed:
            state.blocked_reason = reason
            state.answer = SAFE_FALLBACK_EN if state.language == "en" else SAFE_FALLBACK_VI
            state.dataset_results = []
        state.record(self.name, started, status="ok", allowed=allowed, reason=reason)
        return state


class FinalResponseAgent:
    name = "final_response"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        state.answer = str(state.answer or "").strip()
        state.record(
            self.name,
            started,
            status="ok",
            source_count=state.source_count,
            attachment_mode=state.attachment_mode,
            blocked=bool(state.blocked_reason),
        )
        return state


class LegalAnswerWorkflow:
    """Execute the production legal-answer agents in a fixed auditable order."""

    def __init__(self, agents: list[WorkflowAgent] | None = None) -> None:
        self.agents = agents or [
            LegalRetrievalAgent(),
            PolicyNewsResearchAgent(),
            EvidenceMergeAgent(),
            AnswerSynthesisAgent(),
            CitationVerificationAgent(),
            SafetyReviewAgent(),
            FinalResponseAgent(),
        ]

    def run(self, state: WorkflowState) -> WorkflowState:
        for agent in self.agents:
            state = agent.run(state)
        return state


def run_legal_workflow(
    *,
    message: str,
    retrieval_query: str,
    intent: IntentResult,
    attachments: list[dict],
    language: str,
    controlled_search: bool,
    top_k: int,
) -> WorkflowState:
    state = WorkflowState(
        message=message,
        retrieval_query=retrieval_query,
        intent=intent,
        attachments=attachments,
        language=language,
        controlled_search=controlled_search,
        top_k=top_k,
        attachment_mode=_attachment_mode(message, attachments),
    )
    return LegalAnswerWorkflow().run(state)
