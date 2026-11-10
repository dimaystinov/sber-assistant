"""Юридические вопросы не должны получать неподтверждённый ответ модели."""

from assistant.chat_graph import build_chat_graph
from assistant.domain import Role
from assistant.demo_tools import DemoToolBroker
from assistant.gigachat import ChatResponse
from tests.test_chat_graph import FakeModel, manager_for


def test_legal_question_is_stopped_before_model_for_each_role() -> None:
    scenarios = (
        (Role.RETAIL, "Как по закону обжаловать отказ банка?"),
        (Role.RETAIL, "Банк списал деньги без согласия, что делать?"),
        (Role.BUSINESS, "Какие налоги я должен заплатить?"),
        (Role.EMPLOYEE, "Могут ли меня уволить по ТК РФ?"),
    )
    for role, query in scenarios:
        model = FakeModel()
        result = build_chat_graph(
            manager_for(role), model, DemoToolBroker()
        ).invoke({"query": query, "cross_role_opt_in": False})
        assert result["decision"] == "legal_source_required"
        assert "официаль" in result["answer"].lower()
        assert model.calls == []
        assert model.critic_calls == []


def test_plain_business_question_is_not_classified_as_law() -> None:
    model = FakeModel()
    result = build_chat_graph(
        manager_for(Role.BUSINESS), model, DemoToolBroker()
    ).invoke({"query": "Как проверить рекламу?", "cross_role_opt_in": False})
    assert result["decision"] == "answered"
    assert model.calls


def test_legal_claim_in_generated_draft_is_hidden() -> None:
    model = FakeModel()

    def legal_draft(role, query, context=None):
        return ChatResponse("По закону вы обязаны оплатить штраф.", role, 7)

    model.chat = legal_draft
    result = build_chat_graph(
        manager_for(Role.BUSINESS), model, DemoToolBroker()
    ).invoke({"query": "Что делать дальше?", "cross_role_opt_in": False})
    assert result["decision"] == "legal_source_required"
    assert "штраф" not in result["answer"]
    assert model.critic_calls == []
