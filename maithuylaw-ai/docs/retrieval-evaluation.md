# Retrieval Evaluation

## Implemented retrieval modes

- `retrieve_bm25`: sparse release baseline.
- `retrieve`: production hybrid BM25+dense retrieval with weighted RRF.

Every production result includes:

```text
retrieval_mode
sparse_score
dense_score
rrf_score
retrieval_intent
source_type
```

## Dataset composition

```text
224 chunks
27 documents
182 legal chunks
14 policy chunks
28 news chunks
```

Policy chunks are official policy-management source cards separated from incident/news material so policy questions can be filtered and ranked independently.

## Regression benchmark

Queries are stored in `tests/fixtures/retrieval_queries.json`. Run:

```bash
python scripts/evaluate_retrieval.py
python scripts/evaluate_retrieval.py --json
```

Current result:

| Retriever | Recall@3 | Recall@5 | MRR |
|---|---:|---:|---:|
| BM25 | 1.000 | 1.000 | 1.000 |
| Hybrid RRF | 1.000 | 1.000 | 1.000 |

This five-query set verifies release regressions across legal, policy, and news routing. It is not statistically sufficient for a claim that hybrid retrieval outperforms BM25 generally. A future evaluation should add paraphrases, ambiguous questions, hard negatives, temporal queries, and human relevance judgments.

## Release acceptance

CI requires:

- manifest consistency;
- policy corpus presence;
- hybrid result metadata;
- Recall@3 at least `0.8`;
- Recall@5 equal to `1.0` on the regression set;
- hybrid MRR not below the BM25 baseline.
