"""Ключевые сценарии RoleContextManager: изоляция, согласия, отзыв, cross-retrieval."""
from __future__ import annotations

import pytest

from assistant.consent import ConsentScope, CONSENT_DOCS
from assistant.domain import Role, SubjectIdentity
from assistant.role_context import RoleContextManager, RoleSwitchDenied


def make_manager() -> tuple[RoleContextManager, dict]:
    identity = SubjectIdentity("sber_id_user_42")
    from assistant.consent import ConsentService
    from assistant.context_store import RedisSessionStore, VectorStore

    redis_store, vector_store = RedisSessionStore(), VectorStore()
    manager = RoleContextManager(identity, ConsentService(), redis_store, vector_store)
    return manager, {"redis": redis_store, "vectors": vector_store}


def test_hashes_are_unlinkable() -> None:
    identity = SubjectIdentity("sber_id_user_42")
    hashes = identity.hashes()
    assert len(set(hashes.values())) == 3  # три роли — три разных hash
    assert not any(h == "sber_id_user_42" for h in hashes.values())


def test_switch_role_requires_consent() -> None:
    manager, _ = make_manager()
    with pytest.raises(RoleSwitchDenied) as err:
        manager.switch_role(Role.RETAIL)
    assert err.value.required_scope is ConsentScope.LLM_PROCESSING
    assert err.value.doc_version_required == CONSENT_DOCS[ConsentScope.LLM_PROCESSING].version


def test_switch_creates_isolated_namespace_and_session() -> None:
    manager, stores = make_manager()
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    retail_ctx = manager.switch_role(Role.RETAIL, "sberbank_online")
    assert retail_ctx.session.namespace == "retail_ns"

    manager.remember("карта клиента — переписка: моя выписка хранения покупок")

    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "sbi_business")
    biz_ctx = manager.switch_role(Role.BUSINESS, "sbi_business")
    assert biz_ctx.switched_now is True
    assert biz_ctx.session.namespace == "biz_ns"
    assert biz_ctx.session.role is Role.BUSINESS

    # Контекст retail недоступен из biz-роли напрямую
    ctx = manager.get_context("выписка хранения покупок")
    assert ctx["own_context"] == [], "biz-роль не видит retail-данные"
    # И старая сессия уничтожена
    assert stores["redis"].get_alive(Role.RETAIL, manager._current_hash(Role.RETAIL)) is None


def test_cross_retrieval_requires_both_consents() -> None:
    manager, _ = make_manager()
    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "sbi_business")
    manager.switch_role(Role.BUSINESS, "sbi_business")
    ctx = manager.get_context("обороты")
    assert ctx["cross_context_anonymized"] == []  # retail-согласия нет

    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    manager.grant_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL, "sbi_business")
    # Данных retail у biz-проф ili нет, но механика двух согласий уже активна
    assert manager.check_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL)


def test_cross_retrieval_requires_opt_in_on_this_request() -> None:
    manager, _ = make_manager()
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    manager.switch_role(Role.RETAIL, "sberbank_online")
    manager.remember("оборот 100000 рублей; переписка: личные сведения")
    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "sbi_business")
    manager.grant_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL, "sbi_business")
    manager.switch_role(Role.BUSINESS, "sbi_business")

    assert manager.get_context("оборот")["cross_context_anonymized"] == []
    opted_in = manager.get_context("оборот", cross_role_opt_in=True)
    assert opted_in["cross_context_anonymized"] == []


def test_cross_retrieval_uses_only_preverified_summary() -> None:
    manager, _ = make_manager()
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    manager.switch_role(Role.RETAIL, "sberbank_online")
    manager.remember(
        "личные сведения перед: оборот 100000 рублей",
        {"cross_shareable_verified": True, "cross_shareable_summary": "оборот 100000 рублей"},
    )
    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "sbi_business")
    manager.grant_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL, "sbi_business")
    manager.switch_role(Role.BUSINESS, "sbi_business")

    context = manager.get_context("оборот", cross_role_opt_in=True)
    assert context["cross_context_anonymized"] == [{"summary": "оборот 100000 рублей"}]
    assert "личные сведения" not in str(context)


def test_withdraw_revokes_sessions_and_deletes_data() -> None:
    manager, stores = make_manager()
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    ctx = manager.switch_role(Role.RETAIL, "sberbank_online")
    doc_id = manager.remember("мои транзакции за март")

    manager.withdraw_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")

    assert manager.active_role is None, "сессия роли сброшена после отзыва"
    assert stores["redis"].drop_all_for(ctx.session.subject_hash, Role.RETAIL) == 0
    assert stores["vectors"].delete_subject(Role.RETAIL, ctx.session.subject_hash) == 0
    assert doc_id.startswith("doc-")

    # Повторное использование роли невозможно без нового согласия
    with pytest.raises(RoleSwitchDenied):
        manager.switch_role(Role.RETAIL)


def test_employee_role_restricted_to_hr_scope() -> None:
    manager, _ = make_manager()
    manager.grant_consent(Role.EMPLOYEE, ConsentScope.HR_ANALYTICS, "hr_portal")
    assert manager.check_consent(Role.EMPLOYEE, ConsentScope.HR_ANALYTICS)
    manager.grant_consent(Role.EMPLOYEE, ConsentScope.LLM_PROCESSING, "hr_portal")
    ctx = manager.switch_role(Role.EMPLOYEE, "hr_portal")
    assert ctx.session.namespace == "emp_ns"
