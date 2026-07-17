from backend.citations import verify_citations

LEGAL = {"content": "Điều 5 quy định mức phạt 10 triệu đồng.", "metadata": {"source_type": "legal"}}
NEWS = {"content": "Bản tin đề cập một vụ việc.", "metadata": {"source_type": "news"}}


def test_valid_legal_citation():
    result = verify_citations("Theo Điều 5, mức phạt là 10 triệu đồng [1].", [LEGAL], [])
    assert result.valid
    assert result.coverage == 1.0


def test_invalid_citation_index_is_rejected():
    result = verify_citations("Theo Điều 5, mức phạt là 10 triệu đồng [2].", [LEGAL], [])
    assert not result.valid
    assert result.invalid_citations == [2]


def test_sanction_claim_cannot_rely_on_news():
    result = verify_citations("Mức phạt là 10 triệu đồng [1].", [NEWS], [])
    assert not result.valid
    assert result.legal_claims_without_legal_source


def test_unsupported_cited_claim_is_rejected():
    result = verify_citations("Điều 99 quy định hình phạt 20 năm tù [1].", [LEGAL], [])
    assert not result.valid
    assert result.unsupported_claims
