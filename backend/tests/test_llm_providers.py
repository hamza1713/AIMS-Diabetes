"""
Test LLM Provider Management Endpoints
"""

def test_get_llm_providers(client):
    response = client.get("/api/v1/llm/providers")
    assert response.status_code == 200
    data = response.json()
    assert "active_provider" in data
    assert "providers" in data
    provider_ids = [p["id"] for p in data["providers"]]
    assert "gemini" in provider_ids
    assert "ollama" in provider_ids


def test_set_active_provider(client):
    # Test switching to ollama
    res1 = client.post("/api/v1/llm/provider", json={"provider": "ollama"})
    assert res1.status_code == 200
    assert res1.json()["active_provider"] == "ollama"

    # Test switching back to gemini
    res2 = client.post("/api/v1/llm/provider", json={"provider": "gemini"})
    assert res2.status_code == 200
    assert res2.json()["active_provider"] == "gemini"

    # Test invalid provider
    res3 = client.post("/api/v1/llm/provider", json={"provider": "invalid_provider"})
    assert res3.status_code == 400
