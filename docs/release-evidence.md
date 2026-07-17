# Release Evidence

## Local validation record

Date: 2026-07-17

Validated against the repository after the production hardening series:

```text
python -m compileall -q backend scripts tests      PASS
python scripts/validate_dataset_manifest.py         PASS
python scripts/evaluate_retrieval.py                PASS
pytest -q                                           29 passed
frontend npm ci                                     PASS
frontend npm run build                              PASS
frontend npm audit --audit-level=moderate           no moderate/high/critical vulnerabilities
```

Dataset result:

```text
chunks=224
documents=27
source_type_counts={'legal': 182, 'news': 28, 'policy': 14}
```

Retrieval regression result:

```text
BM25:       R@3=1.000 R@5=1.000 MRR=1.000
Hybrid RRF: R@3=1.000 R@5=1.000 MRR=1.000
```

## CI-only gates

Docker was not available in the local authoring environment. GitHub Actions therefore owns these release gates:

- production Docker image build;
- container startup;
- `/ready` polling;
- API smoke test against the running container.

## Live deployment evidence

Pending user-owned Railway secrets and deployment. After deployment, record:

```text
Public URL:
Deployed commit:
Deployment timestamp:
/health result:
/ready result:
Redis backend:
Smoke-test output:
```

Do not mark live deployment complete until the public URL passes `scripts/smoke_test_backend.py`.
