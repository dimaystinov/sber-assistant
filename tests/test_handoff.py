"""A cross-role handoff shares only workflow state, never role data."""

import pytest

from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.handoff import HandoffCoordinator, HandoffDenied
from assistant.role_context import RoleContextManager


def manager() -> RoleContextManager:
    return RoleContextManager(SubjectIdentity("synthetic-person"), ConsentService())


def grant_pair(person: RoleContextManager) -> None:
    for role in (Role.RETAIL, Role.BUSINESS):
        person.grant_consent(role, ConsentScope.LLM_PROCESSING, "test")
        person.grant_consent(role, ConsentScope.CROSS_RETRIEVAL_RETAIL, "test")


def test_handoff_is_opaque_one_time_and_bound_to_target_role() -> None:
    person = manager()
    grant_pair(person)
    person.switch_role(Role.RETAIL)
    person.remember("секретная выписка клиента")
    coordinator = HandoffCoordinator(person)

    token = coordinator.request(Role.BUSINESS, intent="continue_application", opt_in=True)
    with pytest.raises(HandoffDenied):
        coordinator.claim(token)
    person.switch_role(Role.BUSINESS)
    signal = coordinator.claim(token)
    assert signal == {"intent": "continue_application", "source_role": "retail"}
    assert "секретная" not in str(signal)
    with pytest.raises(HandoffDenied):
        coordinator.claim(token)


def test_handoff_denies_employee_and_missing_consent() -> None:
    person = manager()
    person.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "test")
    person.switch_role(Role.RETAIL)
    coordinator = HandoffCoordinator(person)
    with pytest.raises(HandoffDenied):
        coordinator.request(Role.EMPLOYEE, intent="continue_application", opt_in=True)
    with pytest.raises(HandoffDenied):
        coordinator.request(Role.BUSINESS, intent="continue_application", opt_in=True)
    grant_pair(person)
    with pytest.raises(HandoffDenied):
        coordinator.request(Role.BUSINESS, intent="continue_application", opt_in=False)
    with pytest.raises(HandoffDenied):
        coordinator.request(Role.BUSINESS, intent="secret balance 123", opt_in=True)


def test_handoff_rechecks_consent_when_claimed() -> None:
    person = manager()
    grant_pair(person)
    person.switch_role(Role.RETAIL)
    coordinator = HandoffCoordinator(person)
    token = coordinator.request(Role.BUSINESS, intent="continue_application", opt_in=True)
    person.withdraw_consent(Role.RETAIL, ConsentScope.CROSS_RETRIEVAL_RETAIL, "test")
    person.switch_role(Role.BUSINESS)
    with pytest.raises(HandoffDenied):
        coordinator.claim(token)
