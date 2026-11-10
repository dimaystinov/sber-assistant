from assistant.consent import ConsentScope, ConsentService
from assistant.domain import Role, SubjectIdentity
from assistant.gigachat import ChatResponse, CritiqueResult
from assistant.role_context import RoleContextManager
from assistant.chat_graph import build_chat_graph
from assistant.demo_tools import DemoToolBroker


class FakeModel:
    def __init__(self, approval=True):
        self.calls = []
        self.critic_calls = []
        self.approval = approval

    def chat(self, role, query, context=None):
        self.calls.append((role, query, context))
        return ChatResponse("Модель ответила", role, 7)

    def critique(self, role, query, context, draft):
        self.critic_calls.append((role, query, context, draft))
        return CritiqueResult(self.approval, "Проверка" if self.approval else "Нет основания")


def manager_for(role):
    manager = RoleContextManager(SubjectIdentity("synthetic-person"), ConsentService())
    manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "test")
    manager.switch_role(role, "test")
    return manager


def test_hr_procedure_without_verified_source_stops_before_model():
    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({"query": "Как оформить отпуск?", "cross_role_opt_in": False})
    assert result["decision"] == "source_required"
    assert "HR" in result["answer"]
    assert model.calls == []


def test_retail_balance_without_live_source_stops_before_model():
    manager = manager_for(Role.RETAIL)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({"query": "Какой баланс моего счёта?", "cross_role_opt_in": False})
    assert result["decision"] == "live_data_required"
    assert model.calls == []


def test_other_private_or_current_retail_facts_also_require_source():
    manager = manager_for(Role.RETAIL)
    model = FakeModel()
    graph = build_chat_graph(manager, model)
    for query in ("Сколько денег на карте?", "Какая ставка по ипотеке сегодня?"):
        result = graph.invoke({"query": query, "cross_role_opt_in": False})
        assert result["decision"] == "live_data_required"
    assert model.calls == []


def test_employee_unknown_kpi_stops_without_source():
    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({"query": "Где посмотреть мой KPI?", "cross_role_opt_in": False})
    assert result["decision"] == "source_required"
    assert model.calls == []


def test_business_advice_uses_model_after_role_gate():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({"query": "Продажи упали. Что проверить?", "cross_role_opt_in": False})
    assert result["decision"] == "answered"
    assert result["answer"] == "Модель ответила"
    assert model.calls == [(Role.BUSINESS, "Продажи упали. Что проверить?", None)]
    assert len(model.critic_calls) == 1


def test_critic_rejection_hides_draft():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel(approval=False)
    result = build_chat_graph(manager, model).invoke({"query": "Что делать?", "cross_role_opt_in": False})
    assert result["decision"] == "needs_review"
    assert "Модель ответила" not in result["answer"]
    assert len(model.critic_calls) == 1


def test_fabricated_source_reference_is_hidden_even_if_critic_approves():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()
    model.chat = lambda role, query, context=None: ChatResponse(
        "Оформление доступно по источнику №108.", role, 7
    )
    result = build_chat_graph(manager, model, DemoToolBroker()).invoke({
        "query": "Как продолжить оформление расчётного счёта?",
        "cross_role_opt_in": False,
    })
    assert result["decision"] == "source_reference_invalid"
    assert "108" not in result["answer"]
    assert model.critic_calls == []


def test_handoff_question_has_role_bound_demo_source():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()
    result = build_chat_graph(manager, model, DemoToolBroker()).invoke({
        "query": "Помоги продолжить оформление расчётного счёта в учебном СберБизнесе: какой следующий шаг?",
        "cross_role_opt_in": False,
    })
    assert result["decision"] == "source_answer"
    assert any(s["source_id"] == "demo-business-onboarding" for s in result["sources"])
    assert "ДЕМО:" in result["answer"]
    assert model.calls == []


def test_critic_failure_hides_draft():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()

    def fail(*args):
        raise ValueError("invalid critic output")

    model.critique = fail
    result = build_chat_graph(manager, model).invoke({"query": "Что делать?", "cross_role_opt_in": False})
    assert result["decision"] == "needs_review"
    assert "Модель ответила" not in result["answer"]


def test_cash_gap_is_calculated_by_code_without_model():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({
        "query": "Через 10 дней платёж 700000, доступно 400000. Что делать?",
        "cross_role_opt_in": False,
        "calculation": {
            "kind": "cash_gap", "amount_due": "700000", "available": "400000",
            "days_until_due": 10,
        },
    })
    assert result["decision"] == "calculated"
    assert "300 000" in result["answer"]
    assert "30 000" in result["answer"]
    assert model.calls == []
    assert model.critic_calls == []


def test_unverified_business_formula_is_hidden_before_critic():
    model = FakeModel()

    def formula_draft(role, query, context=None):
        return ChatResponse(
            "ROI = (прибыль минус расходы) / расходы × 100%", role, 7
        )

    model.chat = formula_draft
    result = build_chat_graph(
        manager_for(Role.BUSINESS), model, DemoToolBroker()
    ).invoke({"query": "Стоит ли увеличивать рекламу?", "cross_role_opt_in": False})
    assert result["decision"] == "calculation_required"
    assert "ROI" not in result["answer"]
    assert model.critic_calls == []


def test_business_numbers_need_structured_calculation():
    manager = manager_for(Role.BUSINESS)
    model = FakeModel()
    result = build_chat_graph(manager, model).invoke({
        "query": "Платёж 700000, доступно 400000. Сколько не хватает?",
        "cross_role_opt_in": False,
    })
    assert result["decision"] == "calculation_required"
    assert model.calls == []


def test_calculation_cannot_be_used_from_other_role():
    import pytest

    manager = manager_for(Role.RETAIL)
    model = FakeModel()
    with pytest.raises(PermissionError):
        build_chat_graph(manager, model).invoke({
            "query": "Что делать?", "cross_role_opt_in": False,
            "calculation": {
                "kind": "cash_gap", "amount_due": "700000", "available": "400000",
                "days_until_due": 10,
            },
        })
    assert model.calls == []


def test_employee_uses_cited_demo_document_with_critic():
    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    broker = DemoToolBroker()
    result = build_chat_graph(manager, model, broker).invoke({
        "query": "Как оформить отпуск?", "cross_role_opt_in": False,
    })
    assert result["decision"] == "answered"
    assert "demo-employee-vacation" in model.calls[0][2]
    assert model.critic_calls


def test_retail_balance_uses_verified_demo_tool_without_model():
    manager = manager_for(Role.RETAIL)
    model = FakeModel()
    broker = DemoToolBroker()
    result = build_chat_graph(manager, model, broker).invoke({
        "query": "Какой баланс счёта?", "cross_role_opt_in": False,
    })
    assert result["decision"] == "tool_result"
    assert "ДЕМО" in result["answer"]
    assert model.calls == []


def test_unknown_employee_question_falls_back_to_support():
    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    broker = DemoToolBroker()
    result = build_chat_graph(manager, model, broker).invoke({
        "query": "Что с квантовым ускорителем?", "cross_role_opt_in": False,
    })
    assert result["decision"] == "source_required"
    assert model.calls == []


def test_demo_instruction_cannot_answer_request_for_real_sber_regulation():
    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    result = build_chat_graph(manager, model, DemoToolBroker()).invoke({
        "query": "Как оформить отпуск по внутреннему регламенту Сбера?",
        "cross_role_opt_in": False,
    })
    assert result["decision"] == "internal_policy_required"
    assert "учебн" in result["answer"].lower()
    assert model.calls == []


def test_untrusted_cross_role_metadata_is_not_sent_to_model():
    manager = RoleContextManager(SubjectIdentity("synthetic-person"), ConsentService())
    manager.grant_consent(Role.RETAIL, ConsentScope.LLM_PROCESSING, "test")
    manager.switch_role(Role.RETAIL, "test")
    manager.remember(
        "секретный текст оборот 100000",
        {"cross_shareable_verified": True, "cross_shareable_summary": "оборот 100000"},
    )
    manager.grant_consent(Role.BUSINESS, ConsentScope.LLM_PROCESSING, "test")
    manager.grant_consent(Role.BUSINESS, ConsentScope.CROSS_RETRIEVAL_RETAIL, "test")
    manager.grant_consent(Role.RETAIL, ConsentScope.CROSS_RETRIEVAL_RETAIL, "test")
    manager.switch_role(Role.BUSINESS, "test")
    model = FakeModel()

    build_chat_graph(manager, model).invoke({"query": "оборот", "cross_role_opt_in": True})
    sent_context = model.calls[0][2]
    assert sent_context is None


def test_tool_gateway_denies_unknown_and_write_tools():
    from assistant.tool_policy import authorize_tool
    assert authorize_tool("delete_account", Role.RETAIL, {}) is False
    assert authorize_tool("read_profile", Role.RETAIL, {}) is False


def test_api_uses_graph_gate_before_model(monkeypatch):
    from fastapi.testclient import TestClient
    from assistant import api

    manager = manager_for(Role.EMPLOYEE)
    model = FakeModel()
    monkeypatch.setenv("ASSISTANT_DEMO_TOKEN", "demo-test-token")
    api._RUNTIME.consent = manager._consents
    api._RUNTIME.managers = {"demo-subject": manager}
    api._RUNTIME.gigachat = model
    response = TestClient(api.app).post(
        "/v1/chat",
        headers={"Authorization": "Bearer demo-test-token"},
        json={"query": "Как оформить отпуск?"},
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "answered"
    assert response.json()["sources"][0]["source_id"] == "demo-employee-vacation"
    assert "demo-employee-vacation" in model.calls[0][2]
