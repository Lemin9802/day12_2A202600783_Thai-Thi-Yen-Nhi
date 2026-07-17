from backend.intent import route_intent
from backend.workflow import PolicyNewsResearchAgent, WorkflowState, run_legal_workflow


def test_workflow_executes_auditable_agent_path():
    question = "Nghị định 28/2026/NĐ-CP quy định gì?"
    state = run_legal_workflow(
        message=question,
        retrieval_query=question,
        intent=route_intent(question),
        attachments=[],
        language="vi",
        controlled_search=False,
        top_k=4,
    )
    names = [step["agent"] for step in state.trace]
    assert names == [
        "legal_retrieval",
        "policy_news_research",
        "evidence_merge",
        "answer_synthesis",
        "citation_verification",
        "safety_review",
        "final_response",
    ]
    assert state.citation_verification and state.citation_verification.valid
    assert state.dataset_results


def test_identity_route_skips_retrieval():
    question = "MaiThuyLaw là gì?"
    state = run_legal_workflow(
        message=question,
        retrieval_query=question,
        intent=route_intent(question),
        attachments=[],
        language="vi",
        controlled_search=False,
        top_k=4,
    )
    assert state.dataset_results == []
    assert state.citation_verification and state.citation_verification.valid


def test_controlled_search_agent_requires_consent(monkeypatch):
    monkeypatch.setattr("backend.workflow.realtime_enabled", lambda: True)
    monkeypatch.setattr(
        "backend.workflow.search_realtime",
        lambda query, language="vi": [{"title": "Official update", "url": "https://mps.gov.vn/update", "content": "Official policy update"}],
    )
    intent = route_intent("tin mới về chính sách ma túy")
    without_consent = WorkflowState("tin mới", "tin mới", intent, [], controlled_search=False)
    with_consent = WorkflowState("tin mới", "tin mới", intent, [], controlled_search=True)
    PolicyNewsResearchAgent().run(without_consent)
    PolicyNewsResearchAgent().run(with_consent)
    assert without_consent.dataset_results == []
    assert len(with_consent.dataset_results) == 1
