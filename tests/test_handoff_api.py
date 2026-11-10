"""The role transition is usable over HTTP without sharing either role's memory."""

from fastapi.testclient import TestClient

from assistant import api
from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.role_context import RoleContextManager


HEADERS = {"Authorization": "Bearer demo-test-token"}


def client(monkeypatch) -> tuple[TestClient, RoleContextManager]:
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    monkeypatch.setenv("ASSISTANT_ENV", "demo")
    manager = RoleContextManager(SubjectIdentity("person"), ConsentService())
    api._RUNTIME.consent = manager._consents
    api._RUNTIME.managers = {"demo-subject": manager}
    api._RUNTIME.handoffs.clear()
    return TestClient(api.app), manager


def consent(http: TestClient, role: str, scope: str) -> str:
    channel = {"retail": "sberbank_online", "business": "sbi_business"}[role]
    response = http.post(
        "/v1/consents", headers=HEADERS,
        json={"role": role, "scope": scope, "channel": channel},
    )
    assert response.status_code == 200
    return response.json()["consent_id"]


def test_http_handoff_is_one_time_and_does_not_transfer_memory(monkeypatch) -> None:
    http, manager = client(monkeypatch)
    for role in ("retail", "business"):
        consent(http, role, ConsentScope.LLM_PROCESSING.value)
        consent(http, role, ConsentScope.CROSS_RETRIEVAL_RETAIL.value)
    http.post("/v1/role/switch", headers=HEADERS,
              json={"target_role": "retail", "channel": "sberbank_online"})
    manager.remember("секретный номер счёта 123")
    issued = http.post("/v1/handoff/request", headers=HEADERS,
                       json={"target_role": "business", "intent": "continue_application", "opt_in": True})
    assert issued.status_code == 200
    token = issued.json()["token"]
    assert "123" not in str(issued.json())
    assert http.post("/v1/handoff/claim", headers=HEADERS, json={"token": token}).status_code == 403
    http.post("/v1/role/switch", headers=HEADERS,
              json={"target_role": "business", "channel": "sbi_business"})
    claimed = http.post("/v1/handoff/claim", headers=HEADERS, json={"token": token})
    assert claimed.status_code == 200
    assert claimed.json()["signal"] == {"intent": "continue_application", "source_role": "retail"}
    assert "расчётного счёта" in claimed.json()["suggested_question"]
    assert "123" not in str(claimed.json())
    assert manager.get_context("номер счёта")["own_context"] == []
    assert http.post("/v1/handoff/claim", headers=HEADERS, json={"token": token}).status_code == 403


def test_http_handoff_requires_explicit_consent_and_blocks_employee(monkeypatch) -> None:
    http, _ = client(monkeypatch)
    consent(http, "retail", ConsentScope.LLM_PROCESSING.value)
    http.post("/v1/role/switch", headers=HEADERS,
              json={"target_role": "retail", "channel": "sberbank_online"})
    body = {"target_role": "business", "intent": "continue_application", "opt_in": True}
    assert http.post("/v1/handoff/request", headers=HEADERS, json=body).status_code == 403
    body["target_role"] = "employee"
    assert http.post("/v1/handoff/request", headers=HEADERS, json=body).status_code == 403
