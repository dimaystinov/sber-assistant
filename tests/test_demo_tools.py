"""Проверка прав и одноразового подтверждения симулированных инструментов."""

import pytest

from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.role_context import RoleContextManager
from assistant.demo_tools import DemoToolBroker


def _manager(role: Role) -> RoleContextManager:
    manager = RoleContextManager(SubjectIdentity("demo-person"), ConsentService())
    manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "demo")
    manager.switch_role(role, "demo")
    return manager


def test_read_tool_is_bound_to_active_role() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.RETAIL)

    result = broker.read(manager, "retail_balance")
    assert result.role is Role.RETAIL
    assert result.verified is True
    assert "ДЕМО" in result.text
    with pytest.raises(PermissionError):
        broker.read(manager, "employee_procedure")


def test_hr_document_has_provenance() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.EMPLOYEE)

    result = broker.read(manager, "employee_procedure")
    assert result.source_id
    assert result.version
    assert result.verified is True
    assert "учебная" in result.text.lower()


def test_simulated_payment_needs_confirmation_and_is_single_use() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.BUSINESS)
    draft = broker.prepare_payment(manager, "1500.00", "Учебный поставщик")

    assert not broker.events
    event = broker.confirm_payment(manager, draft.action_id, draft.confirmation_token)
    assert event.status == "simulated"
    assert len(broker.events) == 1
    with pytest.raises(PermissionError):
        broker.confirm_payment(manager, draft.action_id, draft.confirmation_token)


def test_simulated_payment_cannot_cross_role_or_change_amount() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.BUSINESS)
    draft = broker.prepare_payment(manager, "1500.00", "Учебный поставщик")

    with pytest.raises(PermissionError):
        broker.confirm_payment(manager, draft.action_id, "wrong-token")
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "demo")
    manager.switch_role(Role.RETAIL, "demo")
    with pytest.raises(PermissionError):
        broker.confirm_payment(manager, draft.action_id, draft.confirmation_token)
    assert not broker.events


def test_retail_cart_and_booking_are_confirmed_actions() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.RETAIL)

    cart_draft = broker.prepare_action(
        manager, "add_to_cart", {"sku": "demo-headphones", "quantity": 2}
    )
    assert broker.state(manager)["cart"] == []
    broker.confirm_action(
        manager, cart_draft.action_id, cart_draft.confirmation_token
    )
    assert broker.state(manager)["cart"][0]["quantity"] == 2

    booking_draft = broker.prepare_action(
        manager, "book_appointment", {"slot": "2026-11-12T12:00:00+03:00"}
    )
    broker.confirm_action(
        manager, booking_draft.action_id, booking_draft.confirmation_token
    )
    assert len(broker.state(manager)["bookings"]) == 1


def test_business_competitors_and_ad_campaign_are_sandboxed() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.BUSINESS)

    result = broker.read(manager, "business_competitors")
    assert "ДЕМО" in result.text
    assert "конкурент" in result.text.lower()
    draft = broker.prepare_action(
        manager,
        "create_ad_campaign",
        {"channel": "search", "budget": "12000", "title": "Учебная реклама"},
    )
    assert broker.state(manager)["ad_campaigns"] == []
    broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
    assert broker.state(manager)["ad_campaigns"][0]["budget"] == "12000"


def test_employee_tasks_and_performance_are_transparent_demo_data() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.EMPLOYEE)

    report = broker.read(manager, "employee_performance")
    assert "ДЕМО" in report.text
    assert "источник" in report.text.lower()
    draft = broker.prepare_action(
        manager,
        "assign_task",
        {"assignee": "Анна", "title": "Проверить учебный отчёт"},
    )
    broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
    assert broker.state(manager)["tasks"][-1]["assignee"] == "Анна"


def test_action_cannot_be_prepared_in_wrong_role() -> None:
    broker = DemoToolBroker()
    manager = _manager(Role.RETAIL)
    with pytest.raises(PermissionError):
        broker.prepare_action(
            manager,
            "assign_task",
            {"assignee": "Анна", "title": "Чужая задача"},
        )
