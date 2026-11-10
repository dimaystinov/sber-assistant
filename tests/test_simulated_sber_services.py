"""Пять публично описанных Sber API MCP-сервисов, только учебные данные."""

import pytest
from fastapi.testclient import TestClient

from assistant import api
from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.role_context import RoleContextManager
from assistant.simulated_sber_services import SimulatedSberMcpGateway


def manager(role: Role, subject: str = "demo-owner") -> RoleContextManager:
    person = RoleContextManager(SubjectIdentity(subject), ConsentService())
    person.grant_consent(role, ConsentScope.LLM_PROCESSING, "test")
    person.switch_role(role, "test")
    return person


@pytest.mark.parametrize("service,tool,args,key", [
    ("client_info", "accounts.get_list", {}, "accounts"),
    ("statement", "statement.get_summary", {"accountNumber": "DEMO-40702-1", "statementDate": "2026-11-09"}, "closing_balance"),
    ("statement", "statement.get_rur_increment", {"accountNumber": "DEMO-40702-1", "lastModifyDate": "2026-11-09T09:00:00", "page": 1}, "transactions"),
    ("payment", "rur_payment.get_state", {"externalId": "demo-payment-1"}, "bankStatus"),
    ("encashment", "encashment.get_contracts_list", {"page": 1}, "contracts"),
    ("placement", "deposit.get_commercial_offers", {"page": 1}, "offers"),
])
def test_each_service_is_callable_via_mcp(service, tool, args, key) -> None:
    gateway = SimulatedSberMcpGateway()
    result = gateway.call(manager(Role.BUSINESS), service, tool, args)
    assert result["provenance"] == "demo_fixture"
    assert key in result["data"]


def test_service_scope_and_subject_are_checked_before_mcp() -> None:
    gateway = SimulatedSberMcpGateway()
    business = manager(Role.BUSINESS)
    with pytest.raises(PermissionError):
        gateway.call(business, "statement", "statement.get_summary", {
            "accountNumber": "DEMO-OTHER", "statementDate": "2026-11-09"
        })
    with pytest.raises(PermissionError):
        gateway.call(manager(Role.RETAIL), "client_info", "accounts.get_list", {})
    with pytest.raises(PermissionError):
        gateway.call(business, "payment", "rur_payment.get_state", {
            "externalId": "demo-payment-1"
        }, scopes={"MCP_COMMON"})


def test_payment_draft_requires_confirmation_and_never_executes() -> None:
    gateway = SimulatedSberMcpGateway()
    business = manager(Role.BUSINESS)
    payload = {
        "externalId": "demo-new-payment-1", "amount": "1250.00",
        "payeeInn": "7700000000", "payeeAccount": "DEMO-PAYEE-1",
        "purpose": "Учебный счет", 
    }
    pending = gateway.prepare_payment_draft(business, payload)
    with pytest.raises(PermissionError):
        gateway.confirm_payment_draft(business, pending["action_id"], "wrong")
    assert gateway.payment_drafts == {}
    draft = gateway.confirm_payment_draft(
        business, pending["action_id"], pending["confirmation_token"]
    )
    assert draft["bankStatus"] == "CREATED"
    assert draft["executed"] is False
    with pytest.raises(PermissionError):
        gateway.confirm_payment_draft(
            business, pending["action_id"], pending["confirmation_token"]
        )


def test_payment_draft_rejects_wrong_subject_and_bad_amount() -> None:
    gateway = SimulatedSberMcpGateway()
    owner = manager(Role.BUSINESS)
    payload = {"externalId": "demo-new-payment-2", "amount": "1.00",
               "payeeInn": "7700000000", "payeeAccount": "DEMO-PAYEE-1",
               "purpose": "Учебный счет"}
    pending = gateway.prepare_payment_draft(owner, payload)
    with pytest.raises(PermissionError):
        gateway.confirm_payment_draft(
            manager(Role.BUSINESS, "other"), pending["action_id"],
            pending["confirmation_token"],
        )
    with pytest.raises(ValueError):
        gateway.prepare_payment_draft(owner, {**payload, "amount": "-1"})


def test_demo_http_exposes_read_and_confirmed_draft(monkeypatch) -> None:
    owner = manager(Role.BUSINESS)
    monkeypatch.setenv("ASSISTANT_ENV", "demo")
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-sber-services-test")
    monkeypatch.setattr(api._RUNTIME, "consent", owner._consents)
    monkeypatch.setattr(api._RUNTIME, "managers", {"demo-subject": owner})
    monkeypatch.setattr(api._RUNTIME, "sber_mcp", SimulatedSberMcpGateway())
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer demo-sber-services-test"}
    read = client.post("/v1/demo/sber-mcp/call", headers=headers, json={
        "service": "client_info", "tool": "accounts.get_list", "arguments": {},
    })
    assert read.status_code == 200
    assert read.json()["data"]["accounts"][0]["accountNumber"] == "DEMO-40702-1"
    payload = {"externalId": "demo-http-payment-1", "amount": "100.00",
               "payeeInn": "7700000000", "payeeAccount": "DEMO-PAYEE-1",
               "purpose": "Учебный счет"}
    prepared = client.post("/v1/demo/sber-mcp/payments/prepare", headers=headers,
                           json={"payload": payload})
    assert prepared.status_code == 200
    pending = prepared.json()
    confirmed = client.post("/v1/demo/sber-mcp/payments/confirm", headers=headers,
                            json={"action_id": pending["action_id"],
                                  "confirmation_token": pending["confirmation_token"]})
    assert confirmed.status_code == 200
    assert confirmed.json()["bankStatus"] == "CREATED"
    assert confirmed.json()["executed"] is False


@pytest.mark.parametrize("role,service,tool,key", [
    (Role.BUSINESS, "crm", "crm.leads.get", "leads"),
    (Role.EMPLOYEE, "hr", "hr.leave_balance.get", "days_available"),
    (Role.EMPLOYEE, "it", "it.tickets.get", "tickets"),
    (Role.EMPLOYEE, "policy", "policy.search", "documents"),
    (Role.RETAIL, "identity", "identity.me", "role"),
])
def test_custom_demo_services_have_separate_role_scope(role, service, tool, key) -> None:
    gateway = SimulatedSberMcpGateway()
    result = gateway.call(manager(role), service, tool, {})
    assert result["provenance"] == "demo_fixture"
    assert key in result["data"]
    if service != "identity":
        wrong = Role.RETAIL if role is not Role.RETAIL else Role.BUSINESS
        with pytest.raises(PermissionError):
            gateway.call(manager(wrong), service, tool, {})
