"""Сквозной доступ к учебным данным и действиям через HTTP."""

from fastapi.testclient import TestClient

from assistant import api
from assistant.demo_tools import DemoToolBroker
from assistant.domain import Role
from tests.test_chat_graph import FakeModel, manager_for


def _client(monkeypatch, role: Role) -> TestClient:
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    manager = manager_for(role)
    api._RUNTIME.consent = manager._consents
    api._RUNTIME.managers = {"demo-subject": manager}
    api._RUNTIME.gigachat = FakeModel()
    api._RUNTIME.broker = DemoToolBroker()
    return TestClient(api.app)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer demo-test-token"}


def test_demo_page_is_served_without_embedded_secret(monkeypatch) -> None:
    client = _client(monkeypatch, Role.RETAIL)
    response = client.get("/")
    assert response.status_code == 200
    assert "Помощник для трёх ролей" in response.text
    assert "demo-test-token" not in response.text


def test_employee_read_is_role_bound_and_cited(monkeypatch) -> None:
    client = _client(monkeypatch, Role.EMPLOYEE)
    response = client.get(
        "/v1/demo/read/employee_procedure?query=отпуск", headers=_headers()
    )
    assert response.status_code == 200
    assert response.json()["source_id"] == "demo-employee-vacation"
    assert "ДЕМО" in response.json()["text"]
    assert client.get(
        "/v1/demo/read/retail_balance", headers=_headers()
    ).status_code == 403


def test_action_requires_confirmation_and_is_one_time(monkeypatch) -> None:
    client = _client(monkeypatch, Role.RETAIL)
    prepared = client.post(
        "/v1/demo/actions/prepare", headers=_headers(),
        json={"kind": "add_to_cart", "payload": {"sku": "demo-router", "quantity": 1}},
    )
    assert prepared.status_code == 200
    assert client.get("/v1/demo/state", headers=_headers()).json()["state"]["cart"] == []
    draft = prepared.json()
    assert client.post(
        "/v1/demo/actions/confirm", headers=_headers(),
        json={"action_id": draft["action_id"], "confirmation_token": "wrong"},
    ).status_code == 403
    confirmed = client.post(
        "/v1/demo/actions/confirm", headers=_headers(),
        json={"action_id": draft["action_id"],
              "confirmation_token": draft["confirmation_token"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "simulated"
    assert client.get("/v1/demo/state", headers=_headers()).json()["state"]["cart"] == [
        {"sku": "demo-router", "quantity": 1}
    ]
    assert client.post(
        "/v1/demo/actions/confirm", headers=_headers(),
        json={"action_id": draft["action_id"],
              "confirmation_token": draft["confirmation_token"]},
    ).status_code == 403


def test_consent_withdrawal_checks_identifier(monkeypatch) -> None:
    client = _client(monkeypatch, Role.RETAIL)
    body = {"scope": "llm_processing", "role": "retail",
            "channel": "sberbank_online"}
    granted = client.post("/v1/consents", headers=_headers(), json=body).json()
    assert client.request(
        "DELETE", "/v1/consents/not-the-id", headers=_headers(), json=body,
    ).status_code == 404
    assert client.request(
        "DELETE", f"/v1/consents/{granted['consent_id']}",
        headers=_headers(), json=body,
    ).json()["status"] == "withdrawn_in_demo"
    assert client.get("/v1/demo/state", headers=_headers()).status_code == 403
