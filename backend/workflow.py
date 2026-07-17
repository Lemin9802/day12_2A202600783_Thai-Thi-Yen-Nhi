"""Deterministic multi-agent orchestration for grounded legal answers.

The agents are deliberately small and side-effect bounded. FastAPI owns request
validation and persistence; this module owns routing-dependent retrieval,
controlled official-source search, evidence merging, answer synthesis, and
output safety review.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from backend.agent import generate_answer
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


@dataclass
class WorkflowState:
    message: str
    retrieval_query: str
    intent: IntentResult
    attachments: list[dict]
    language: str = "vi"
    controlled_search: bool = False
    top_k: int = 6
    dataset_results: list[dict] = field(default_factory=list)
    answer: str = ""
    blocked_reason: str | None = None
    realtime_unavailable: bool = False
    trace: list[dict[str, Any]] = field(default_factory=list)

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
        if state.intent.intent == "identity":
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
            result_count=len(state.dataset_results),
        )
        return state


class PolicyNewsResearchAgent:
    name = "policy_news_research"

    def run(self, state: WorkflowState) -> WorkflowState:
        started = time.perf_counter()
        enabled = realtime_enabled()
        should_search = state.controlled_search and enabled
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
            state.answer = generate_answer(
                message=state.message,
                dataset_results=state.dataset_results,
                attachments=state.attachments,
                language=state.language,
            )
            mode = "grounded_generation"
        state.record(self.name, started, status="ok", mode=mode, answer_chars=len(state.answer))
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
    )
    return LegalAnswerWorkflow().run(state)
