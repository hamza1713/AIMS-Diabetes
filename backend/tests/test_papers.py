"""
Test Research Papers Endpoints
"""

def test_get_papers(client):
    response = client.get("/api/v1/papers")
    assert response.status_code == 200
    papers = response.json()
    assert isinstance(papers, list)
    assert len(papers) > 0
    first_paper = papers[0]
    assert "title" in first_paper
    assert "page_count" in first_paper
