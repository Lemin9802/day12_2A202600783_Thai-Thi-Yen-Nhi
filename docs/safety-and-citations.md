# Safety and Citation Contract

## Input controls

The system separates legal-education questions from operational wrongdoing requests. It refuses instructions for buying, selling, hiding, transporting, manufacturing, using, or concealing drugs, destroying evidence, evading police, or defeating drug tests.

Out-of-domain requests are rejected unless an accepted attachment provides sufficient domain evidence.

## Citation numbering

Production source order is deterministic:

1. retrieved dataset or controlled-search sources;
2. accepted attachments.

The model prompt and API response use the same numeric IDs. Citation normalization removes IDs outside the available source range.

## Claim-level verification

`backend/citations.py` checks:

- citation IDs exist;
- substantive claims have acceptable citation coverage;
- cited evidence has lexical and numeric support for the claim;
- article, penalty, imprisonment, and fine claims use legal sources;
- unsupported or incorrectly sourced claims are not returned as conclusions.

The verifier emits:

```json
{
  "valid": true,
  "coverage": 0.75,
  "substantive_claims": 4,
  "cited_claims": 3,
  "invalid_citations": [],
  "unsupported_claims": [],
  "legal_claims_without_legal_source": []
}
```

If verification fails, the workflow returns an insufficient-evidence answer and removes unsupported sources from the outward response.

## Output safety

After citation validation, output safety rejects:

- operational wrongdoing instructions;
- internal implementation text;
- specific uncited legal sanctions.

This is a deterministic final gate independent of model behavior.

## Limitations

The current source-support check is deterministic token/number overlap, not a trained natural-language-inference model. It is intentionally conservative for sanction claims. Human review remains necessary for high-stakes use.
