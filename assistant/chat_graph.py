"""Управляемый граф диалога: код решает, когда модель можно вызвать."""
from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .calculations import CashGapInput, cash_gap_answer
from .domain import Role
from .demo_tools import DemoToolBroker
from .legal_policy import is_legal_question, source_required_answer
from .role_context import RoleContextManager


class ChatState(TypedDict, total=False):
    query: str
    cross_role_opt_in: bool
    role: Role
    context: dict[str, Any]
    decision: str
    answer: str
    draft: str
    tokens_used: int
    calculation: dict[str, Any]
    sources: list[dict[str, str]]


_RETAIL_LIVE_FACT = re.compile(
    r"баланс|остаток|сколько денег|ставк|тариф|лимит|мои операц|мой сч[её]т",
    re.I,
)
_REAL_INTERNAL_POLICY = re.compile(
    r"внутренн\w*|\bвнд\b|настоящ\w*\s+правил\w*|"
    r"действующ\w*\s+(?:регламент\w*|правил\w*|политик\w*)|"
    r"реальн\w*\s+(?:регламент\w*|правил\w*|политик\w*)",
    re.I,
)
_UNVERIFIED_MATH = re.compile(r"[=×÷]|\b\d+(?:[.,]\d+)?\s*%")
_SOURCE_REFERENCE = re.compile(
    r"источник(?:е|а|у|ом|и|ов)?\s*(?:№|#)\s*([\w.-]+)", re.I
)


def _format_context(context: dict[str, Any]) -> str | None:
    """Помечает происхождение каждого типа разрешённого контекста."""
    own = [item["text"] for item in context["own_context"]]
    cross = [item["summary"] for item in context["cross_context_anonymized"]]
    parts: list[str] = []
    if own:
        parts.append("Контекст текущей роли:\n" + "\n".join(own))
    if cross:
        parts.append(
            "Разрешённый обезличенный агрегат другой роли:\n"
            + "\n".join(cross)
        )
    return "\n\n".join(parts) or None


def build_chat_graph(
    manager: RoleContextManager, model: Any,
    broker: DemoToolBroker | None = None,
):
    """Собрать граф для одной сессии без инструментов модели."""

    def retrieve(state: ChatState) -> ChatState:
        context = manager.get_context(
            state["query"],
            cross_role_opt_in=state.get("cross_role_opt_in", False),
        )
        role = Role(context["role"])
        sources: list[dict[str, str]] = []
        if broker is not None:
            for document in broker.knowledge_search(manager, state["query"]):
                context["own_context"].append({
                    "text": (
                        f"[ДЕМО источник {document.source_id}, версия "
                        f"{document.version}] {document.text}"
                    ),
                    "source_id": document.source_id,
                    "version": document.version,
                    "verified_source": True,
                    "source_text": document.text,
                })
                sources.append({
                    "source_id": document.source_id,
                    "version": document.version,
                    "provenance": document.provenance,
                })
            tool_name = None
            query = state["query"].lower()
            if role is Role.RETAIL and re.search(r"баланс|остаток|сколько денег", query):
                tool_name = "retail_balance"
            elif role is Role.EMPLOYEE and re.search(r"kpi|результат|эффективност", query):
                tool_name = "employee_performance"
            elif role is Role.EMPLOYEE and re.search(r"мои задач|список задач|поручен", query):
                tool_name = "employee_tasks"
            if tool_name is not None:
                result = broker.read(manager, tool_name)
                context["own_context"].append({
                    "text": f"[ДЕМО инструмент {result.source_id}] {result.text}",
                    "source_id": result.source_id,
                    "version": result.version,
                    "verified_source": result.verified,
                    "tool_result": result.text,
                    "tool_name": tool_name,
                })
                sources.append({
                    "source_id": result.source_id,
                    "version": result.version,
                    "provenance": result.provenance,
                })
        return {"role": role, "context": context, "sources": sources}

    def gate(state: ChatState) -> ChatState:
        role, query = state["role"], state["query"]
        if is_legal_question(query):
            return {
                "decision": "legal_source_required",
                "answer": source_required_answer(role),
                "tokens_used": 0,
            }
        if role is Role.EMPLOYEE and _REAL_INTERNAL_POLICY.search(query):
            return {
                "decision": "internal_policy_required",
                "answer": (
                    "В базе есть только учебные примеры, а действующий "
                    "внутренний документ Сбера мне не предоставлен. Проверьте "
                    "его в разрешённом внутреннем канале или обратитесь к "
                    "владельцу процесса. Публичный Кодекс этики доступен на "
                    "https://www.sberbank.com/ru/sustainability/ethics, "
                    "но не заменяет конкретную рабочую инструкцию."
                ),
                "tokens_used": 0,
            }
        if (
            role is Role.BUSINESS
            and "продолжить оформление расчётного счёта" in query.lower()
            and "учебном сбербизнесе" in query.lower()
        ):
            source = next(
                (item for item in state["context"]["own_context"]
                 if item.get("source_id") == "demo-business-onboarding"
                 and item.get("verified_source") is True), None
            )
            if source is not None:
                return {
                    "decision": "source_answer",
                    "answer": source["source_text"],
                    "tokens_used": 0,
                }
        tool_items = [
            item for item in state["context"]["own_context"]
            if item.get("tool_result") and item.get("verified_source")
        ]
        if state.get("calculation") and role is not Role.BUSINESS:
            raise PermissionError(
                "Расчёт кассового разрыва доступен только в бизнес-роли"
            )
        if role is Role.RETAIL and _RETAIL_LIVE_FACT.search(query):
            if tool_items and tool_items[0].get("tool_name") == "retail_balance":
                return {
                    "decision": "tool_result", "answer": tool_items[0]["tool_result"],
                    "tokens_used": 0,
                }
            return {
                "decision": "live_data_required",
                "answer": (
                    "У меня нет подтверждённых актуальных данных по вашему "
                    "запросу. Проверьте их в официальном канале Сбера или "
                    "подключите разрешённый источник."
                ),
                "tokens_used": 0,
            }
        if role is Role.BUSINESS and state.get("calculation"):
            data = CashGapInput.model_validate(state["calculation"])
            answer = (
                broker.calculate_cash_gap(manager, data.model_dump(mode="json"))
                if broker is not None and hasattr(broker, "calculate_cash_gap")
                else cash_gap_answer(data)
            )
            return {
                "decision": "calculated",
                "answer": answer,
                "tokens_used": 0,
            }
        if role is Role.BUSINESS and re.search(r"\d", query):
            return {
                "decision": "calculation_required",
                "answer": (
                    "Для надёжного расчёта заполните структурные поля: сумма "
                    "обязательства, доступные деньги и число дней до платежа. "
                    "После этого я вычислю дефицит кодом."
                ),
                "tokens_used": 0,
            }
        if role is Role.EMPLOYEE:
            if tool_items:
                return {
                    "decision": "tool_result", "answer": tool_items[0]["tool_result"],
                    "tokens_used": 0,
                }
            sources = state["context"].get("own_context", [])
            if not any(item.get("verified_source") for item in sources):
                return {
                    "decision": "source_required",
                    "answer": (
                        "У меня нет подтверждённой актуальной инструкции. "
                        "Найдите её в HR-портале или обратитесь к HR; пришлите "
                        "документ, и я помогу разобраться в нём."
                    ),
                    "tokens_used": 0,
                }
        return {"decision": "generate"}

    def route(state: ChatState) -> str:
        return "generate" if state["decision"] == "generate" else "done"

    def generate(state: ChatState) -> ChatState:
        context_text = _format_context(state["context"])
        result = model.chat(state["role"], state["query"], context_text)
        return {"draft": result.content, "tokens_used": result.tokens_used}

    def critique(state: ChatState) -> ChatState:
        referenced = _SOURCE_REFERENCE.findall(state["draft"])
        allowed_ids = {item["source_id"] for item in state.get("sources", [])}
        if any(reference not in allowed_ids for reference in referenced):
            return {
                "answer": (
                    "Ответ содержит ссылку на источник, которого нет в разрешённой "
                    "базе текущей роли. Проверьте документы и повторите запрос."
                ),
                "decision": "source_reference_invalid",
            }
        if is_legal_question(state["draft"]):
            return {
                "answer": source_required_answer(state["role"]),
                "decision": "legal_source_required",
            }
        if state["role"] is Role.BUSINESS and _UNVERIFIED_MATH.search(state["draft"]):
            return {
                "answer": (
                    "Числовые выводы и формулы требуют проверки кодом. "
                    "Укажите исходные данные в структурных полях или "
                    "обратитесь к специалисту для проверки расчёта."
                ),
                "decision": "calculation_required",
            }
        context_text = _format_context(state["context"])
        try:
            verdict = model.critique(
                state["role"], state["query"], context_text, state["draft"]
            )
            if verdict.approved is True:
                return {
                    "answer": state["draft"],
                    "decision": "answered",
                    "tokens_used": state["tokens_used"] + verdict.tokens_used,
                }
        except Exception:
            # Непонятный или недоступный вердикт никогда не публикует черновик.
            pass
        return {
            "answer": (
                "Ответ требует дополнительной проверки. Уточните исходные "
                "данные или обратитесь к специалисту."
            ),
            "decision": "needs_review",
        }

    builder = StateGraph(ChatState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("gate", gate)
    builder.add_node("generate", generate)
    builder.add_node("critique", critique)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "gate")
    builder.add_conditional_edges(
        "gate", route, {"generate": "generate", "done": END}
    )
    builder.add_edge("generate", "critique")
    builder.add_edge("critique", END)
    return builder.compile()
