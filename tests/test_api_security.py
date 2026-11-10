from fastapi.testclient import TestClient

from assistant import api


def test_api_rejects_missing_and_wrong_token(monkeypatch):
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    client = TestClient(api.app)
    assert client.get("/v1/role/active").status_code == 401
    assert client.get(
        "/v1/role/active", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_role_channel_mismatch_is_rejected(monkeypatch):
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    api._RUNTIME.consent = None
    client = TestClient(api.app)
    response = client.post(
        "/v1/consents",
        headers={"Authorization": "Bearer demo-test-token"},
        json={
            "scope": "llm_processing",
            "role": "employee",
            "channel": "sberbank_online",
        },
    )
    assert response.status_code == 403


def test_demo_identity_fails_closed_in_production_mode(monkeypatch):
    monkeypatch.setenv("ASSISTANT_ENV", "production")
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    response = TestClient(api.app).get(
        "/v1/role/active", headers={"Authorization": "Bearer demo-test-token"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Демо-авторизация отключена вне режима demo"
