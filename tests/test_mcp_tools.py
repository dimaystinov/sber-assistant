"""MCP проходит через ролевой broker, а не через произвольный вызов модели."""

import pytest
from fastapi.testclient import TestClient

from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.mcp_tools import McpDemoToolBroker
from assistant.chat_graph import build_chat_graph
from assistant.role_context import RoleContextManager
from assistant import api


def _manager(role: Role) -> RoleContextManager:
    manager = RoleContextManager(SubjectIdentity("mcp-test"), ConsentService())
    manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "test")
    manager.switch_role(role, "test")
    return manager


def test_mcp_knowledge_is_role_scoped_and_preserves_provenance() -> None:
    broker = McpDemoToolBroker()
    retail = broker.knowledge_search(_manager(Role.RETAIL), "Добавить товар в корзину")
    assert [doc.source_id for doc in retail] == ["demo-retail-cart"]
    assert all(doc.role is Role.RETAIL and doc.provenance == "demo_fixture" for doc in retail)
    assert broker.knowledge_search(_manager(Role.RETAIL), "Как оформить отпуск?") == []


def test_mcp_calculator_matches_decimal_reference() -> None:
    broker = McpDemoToolBroker()
    answer = broker.calculate_cash_gap(
        _manager(Role.BUSINESS),
        {"kind": "cash_gap", "amount_due": "700000", "available": "400000", "days_until_due": 10},
    )
    assert "300 000" in answer
    assert "30 000" in answer


def test_mcp_calculator_denies_wrong_role_and_revoked_consent() -> None:
    broker = McpDemoToolBroker()
    retail = _manager(Role.RETAIL)
    with pytest.raises(PermissionError):
        broker.calculate_cash_gap(retail, {"kind": "cash_gap", "amount_due": "1", "available": "0", "days_until_due": 1})
    business = _manager(Role.BUSINESS)
    business.withdraw_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "test")
    with pytest.raises(PermissionError):
        broker.calculate_cash_gap(business, {"kind": "cash_gap", "amount_due": "1", "available": "0", "days_until_due": 1})


def test_mcp_rejects_tampered_source_and_read_result() -> None:
    class TamperingBroker(McpDemoToolBroker):
        async def _call(self, role, tool, arguments, manager=None):
            result = await super()._call(role, tool, arguments, manager)
            if tool == "search_knowledge":
                result["documents"][0]["source_id"] = "demo-employee-vacation"
            if tool == "read_demo_data":
                result["text"] = "подменённые данные"
            return result

    broker = TamperingBroker()
    manager = _manager(Role.RETAIL)
    with pytest.raises(RuntimeError, match="источник"):
        broker.knowledge_search(manager, "Добавить товар в корзину")
    with pytest.raises(RuntimeError, match="источника"):
        broker.read(manager, "retail_balance")


def test_chat_graph_uses_mcp_calculator_without_model() -> None:
    class ModelThatMustNotRun:
        def chat(self, *args):
            raise AssertionError("LLM must not calculate")

    class TrackingBroker(McpDemoToolBroker):
        called = False

        def calculate_cash_gap(self, manager, payload):
            self.called = True
            return super().calculate_cash_gap(manager, payload)

    broker = TrackingBroker()
    result = build_chat_graph(
        _manager(Role.BUSINESS), ModelThatMustNotRun(), broker
    ).invoke({
        "query": "Какой кассовый разрыв?",
        "calculation": {"kind": "cash_gap", "amount_due": "700000", "available": "400000", "days_until_due": 10},
    })
    assert result["decision"] == "calculated"
    assert broker.called
    assert "300 000" in result["answer"]


def test_mcp_read_only_balance_flows_through_chat_graph() -> None:
    class TrackingBroker(McpDemoToolBroker):
        called_tools = []

        async def _call(self, role, tool, arguments, manager=None):
            self.called_tools.append(tool)
            return await super()._call(role, tool, arguments, manager)

    broker = TrackingBroker()
    result = build_chat_graph(
        _manager(Role.RETAIL), object(), broker
    ).invoke({"query": "Какой баланс моего счёта?"})
    assert result["decision"] == "tool_result"
    assert "12 345,67" in result["answer"]
    assert "read_demo_data" in broker.called_tools


def test_mcp_read_only_tool_rejects_cross_role_call() -> None:
    broker = McpDemoToolBroker()
    with pytest.raises(PermissionError):
        broker.read(_manager(Role.RETAIL), "employee_tasks")


def test_http_chat_uses_mcp_for_demo_balance(monkeypatch) -> None:
    manager = _manager(Role.RETAIL)
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "mcp-test-token")
    monkeypatch.setenv("ASSISTANT_ENV", "demo")
    monkeypatch.setattr(api._RUNTIME, "consent", manager._consents)
    monkeypatch.setattr(api._RUNTIME, "managers", {"demo-subject": manager})
    monkeypatch.setattr(api._RUNTIME, "broker", McpDemoToolBroker())
    response = TestClient(api.app).post(
        "/v1/chat", headers={"Authorization": "Bearer mcp-test-token"},
        json={"query": "Какой баланс моего счёта?"},
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "tool_result"
    assert response.json()["sources"][0]["source_id"] == "demo-retail-balance"
