# MaiThuyLaw AI Architecture

## Runtime boundary

FastAPI handles transport, authentication, session ownership, quota enforcement, file/link validation, and persistence. `backend/workflow.py` owns the AI execution path. This separation keeps HTTP concerns out of agent logic and makes the workflow testable without a web server.

## Workflow state

`WorkflowState` carries:

- user message and memory-rewritten retrieval query;
- routed intent and required source types;
- accepted attachments;
- controlled-search consent;
- retrieved evidence;
- generated answer;
- citation-verification result;
- model token usage;
- an auditable per-agent trace.

## Agent sequence

1. **Legal Retrieval Agent** — runs hybrid retrieval with intent source filters.
2. **Policy/News Research Agent** — performs approved-domain search only when consent and server configuration are both present.
3. **Evidence Merge Agent** — deduplicates documents and limits evidence volume.
4. **Answer Synthesis Agent** — uses Gemini or the cited deterministic fallback.
5. **Citation Verification Agent** — validates IDs, claim coverage, source support, and legal-source requirements.
6. **Safety Review Agent** — blocks unsafe or internally leaking output.
7. **Final Response Agent** — normalizes the final answer and trace metadata.

## Retrieval architecture

The retrieval pipeline contains two independent rankers:

- **Sparse ranker:** BM25 over chunk content and selected metadata.
- **Dense ranker:** deterministic feature-hashed vectors with 384 dimensions.

The two rankings are combined with weighted Reciprocal Rank Fusion. Intent-specific source boosts are applied for legal, policy, news, and sanction questions. Results are deduplicated by document ID.

The dense index is persisted as compressed NumPy data and validated against a dataset signature. `scripts/build_dense_index.py` rebuilds it deterministically.

## Persistence

Production persistence uses Redis:

- chat objects with TTL;
- per-user sorted chat indexes;
- minute/day quota counters;
- monthly token and estimated-cost hashes.

When Redis is absent, development falls back to atomic local JSON files. The `/health` response reports which backend is active.

## Trust boundaries

- User-supplied IDs do not define ownership in public mode; signed sessions do.
- API-key mode resolves an explicit integration identity.
- URL ingestion validates HTTPS, domain allowlists, DNS resolution, public IPs, redirects, content type, and size.
- Only accepted attachments enter the answer context.
- Model output is never returned before citation and safety review.
