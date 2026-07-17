# MaiThuyLaw AI Backend Reference

The production backend is implemented in `backend/` and served by `backend.main:app`.

Current capabilities:

- intent-routed multi-agent legal answer workflow;
- hybrid BM25+dense retrieval with RRF;
- legal, policy, and verified-news source filtering;
- Gemini synthesis plus cited offline fallback;
- claim-level citation verification and output safety;
- signed public sessions or API-key restricted mode;
- Redis-backed history, quotas, and token-cost accounting;
- controlled file/link ingestion;
- health, readiness, history, usage, and chat APIs.

Canonical documentation:

- [`architecture.md`](architecture.md)
- [`retrieval-evaluation.md`](retrieval-evaluation.md)
- [`safety-and-citations.md`](safety-and-citations.md)
- [`deployment.md`](deployment.md)
- [`release-evidence.md`](release-evidence.md)
