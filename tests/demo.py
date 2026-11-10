"""Сквозной демо-сценарий: онбординг → смена роли → cross-retrieval → отзыв согласия."""
from __future__ import annotations

from assistant.consent import ConsentService, ConsentScope
from assistant.context_store import RedisSessionStore, VectorStore
from assistant.domain import Role, SubjectIdentity
from assistant.gigachat import GigaChatClient
from assistant.role_context import RoleContextManager, RoleSwitchDenied


def main() -> None:
    print("=== Универсальный помощник Сбера: демо прототипа ===\n")

    consent = ConsentService()
    identity = SubjectIdentity("sber_id_ivanov_42")
    manager = RoleContextManager(
        identity, consent, RedisSessionStore(), VectorStore()
    )
    llm = GigaChatClient(mode="offline")
    hash_ret = identity.subject_hash(Role.RETAIL)
    hash_biz = identity.subject_hash(Role.BUSINESS)

    # 1. Онбординг: выдаются согласия в каждой роли
    print("-- 1. Онбординг (СберБанк Онлайн) --")
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    ctx = manager.switch_role(Role.RETAIL, "sberbank_online")
    print(f"    роль: {ctx.session.role.value}, ns: {ctx.session.namespace}, sess: {ctx.session.session_id[:14]}…")
    manager.remember("клиент хранит сбережения в рознице; переписка: вопросы по карте")
    print(f"    hashes: retail={hash_ret[:8]}… business={hash_biz[:8]}… (несвязываемые)\n")

    # 2. Переключение роли в СберБизнес
    print("-- 2. Переключение роли в СберБизнес --")
    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "sbi_business")
    biz_ctx = manager.switch_role(Role.BUSINESS, "sbi_business")
    print(f"    роль: {biz_ctx.session.role.value}, ns: {biz_ctx.session.namespace}, switched_now={biz_ctx.switched_now}")
    manager.remember("переписка: ИП Браво планирует кредит на 5 млн")
    answer = llm.chat(manager.active_role, "Какой кредит мне подойдёт?",
                      context="ИП Браво: обороты 4 млн/мес")
    print(f"    LLM> {answer.content[:90]}…\n")

    # 3. Кросс-анализ (opt-in: двойное согласие)
    print("-- 3. Cross-retrieval (retail × business) --")
    print("    согласие cross_retrieval проверяем для активной роли business…")
    print("    требуется согласие обеих ролей + opt-in текущего запроса")
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    manager.grant_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL, "sbi_business")
    result = manager.get_context("сбережения спорт-бизнес")
    print(f"    own_context: {len(result['own_context'])} документ(ов) из biz_ns")
    print(f"    cross_context_anonymized: {result['cross_context_anonymized']}\n")

    # 4. Отзыв согласия на розничную роль
    print("-- 4. Отзыв согласия на розничную роль --")
    manager.withdraw_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "sberbank_online")
    print(f"    активная роль: {manager.active_role}")
    print(f"    журнал согласий: {len(list(consent.journal.iter_all()))} записей (append-only, WORM)")
    try:
        manager.switch_role(Role.RETAIL, "sberbank_online")
    except RoleSwitchDenied as denied_exc:
        print(f"    повторный вход в retail отказан: {denied_exc.reason[:70]}…")
    print("\n=== Демо завершено ===")


if __name__ == "__main__":
    main()
