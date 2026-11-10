from fastapi.testclient import TestClient

from assistant import api


def test_bearer_token_creates_manager_and_online_client(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "test-key")
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    api._RUNTIME.consent = None
    response = TestClient(api.app).get(
        "/v1/role/active",
        headers={"Authorization": "Bearer demo-test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"active_role": None}
    assert api._RUNTIME.gigachat._mode == "online"
