"""Контролируемая симуляция маршрутов и действий демонстрационного ассистента.

Это проверка механических инвариантов, а не оценка качества GigaChat или
эффекта реального внедрения. Данные, пользователи и инструменты синтетические.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path

from assistant.chat_graph import build_chat_graph
from assistant.consent import ConsentScope, ConsentService
from assistant.demo_tools import DemoToolBroker
from assistant.mcp_tools import McpDemoToolBroker
from assistant.domain import Role, SubjectIdentity
from assistant.gigachat import ChatResponse, CritiqueResult
from assistant.role_context import RoleContextManager


@dataclass(frozen=True)
class Scenario:
    name: str
    role: Role
    family: str


SCENARIOS = (
    Scenario("retail_balance", Role.RETAIL, "chat"),
    Scenario("retail_rate_without_source", Role.RETAIL, "chat"),
    Scenario("retail_legal", Role.RETAIL, "chat"),
    Scenario("business_cash_gap", Role.BUSINESS, "chat"),
    Scenario("business_unstructured_numbers", Role.BUSINESS, "chat"),
    Scenario("business_general", Role.BUSINESS, "chat"),
    Scenario("business_legal", Role.BUSINESS, "chat"),
    Scenario("employee_vacation", Role.EMPLOYEE, "chat"),
    Scenario("employee_real_policy", Role.EMPLOYEE, "chat"),
    Scenario("employee_unknown", Role.EMPLOYEE, "chat"),
    Scenario("employee_legal", Role.EMPLOYEE, "chat"),
    Scenario("cart_confirm", Role.RETAIL, "action"),
    Scenario("booking_confirm", Role.RETAIL, "action"),
    Scenario("ad_confirm", Role.BUSINESS, "action"),
    Scenario("task_confirm", Role.EMPLOYEE, "action"),
    Scenario("ticket_confirm", Role.EMPLOYEE, "action"),
    Scenario("cart_wrong_role", Role.BUSINESS, "attack"),
    Scenario("task_wrong_role", Role.RETAIL, "attack"),
    Scenario("wrong_token", Role.RETAIL, "attack"),
    Scenario("replay_confirm", Role.RETAIL, "attack"),
    Scenario("revoked_consent", Role.BUSINESS, "attack"),
    Scenario("critic_failure", Role.BUSINESS, "attack"),
)


class DeterministicModel:
    """Только заглушка языкового слоя; не измеряет точность модели."""

    def __init__(self, critic_fails: bool = False) -> None:
        self.chat_calls = 0
        self.critic_calls = 0
        self.critic_fails = critic_fails

    def chat(self, role: Role, query: str, context: str | None) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse("Учебный ответ по предоставленным данным.", role, 0)

    def critique(
        self, role: Role, query: str, context: str | None, draft: str
    ) -> CritiqueResult:
        self.critic_calls += 1
        if self.critic_fails:
            raise RuntimeError("Сбой учебного критика")
        return CritiqueResult(True, "Учебное подтверждение", 0)


def _manager(role: Role, episode: int) -> tuple[RoleContextManager, str]:
    manager = RoleContextManager(
        SubjectIdentity(f"simulated-person-{episode}"), ConsentService()
    )
    consent_id = manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "simulation")
    manager.switch_role(role, "simulation")
    return manager, consent_id


def _chat_case(
    name: str, role: Role, manager: RoleContextManager,
    broker: DemoToolBroker, rng: random.Random, case_tag: str = "",
) -> tuple[bool, str]:
    due = rng.randint(500_000, 900_000)
    available = rng.randint(100_000, due - 1)
    cases = {
        "retail_balance": ("Какой остаток моего счёта?", "tool_result", None, 0),
        "retail_rate_without_source": ("Какая ставка по ипотеке сегодня?", "live_data_required", None, 0),
        "retail_legal": ("Как по закону обжаловать отказ банка?", "legal_source_required", None, 0),
        "business_cash_gap": (
            f"Через 10 дней платёж {due}, доступно {available}.",
            "calculated",
            {"kind": "cash_gap", "amount_due": str(due),
             "available": str(available), "days_until_due": 10},
            0,
        ),
        "business_unstructured_numbers": (
            f"Платёж {due}, доступно {available}. Сколько не хватает?",
            "calculation_required", None, 0,
        ),
        "business_general": ("Как улучшить продажи?", "answered", None, 1),
        "business_legal": ("Какие налоги платит компания?", "legal_source_required", None, 0),
        "employee_vacation": ("Как оформить отпуск?", "answered", None, 1),
        "employee_real_policy": (
            "Какой действующий внутренний регламент Сбера по отпуску?",
            "internal_policy_required", None, 0,
        ),
        "employee_unknown": (
            "Как оформить неизвестный рабочий процесс?", "source_required", None, 0,
        ),
        "employee_legal": ("Могут ли меня уволить по ТК РФ?", "legal_source_required", None, 0),
    }
    query, expected, calculation, expected_model_calls = cases[name]
    if case_tag:
        query += f" Учебный код {case_tag}."
    model = DeterministicModel()
    result = build_chat_graph(manager, model, broker).invoke({
        "query": query, "cross_role_opt_in": False,
        "calculation": calculation,
    })
    observed = str(result["decision"])
    passed = observed == expected and model.chat_calls == expected_model_calls
    if name == "business_cash_gap":
        expected_gap = f"{due - available:,}".replace(",", " ")
        passed = passed and expected_gap in result["answer"]
    if name == "retail_balance":
        passed = passed and "ДЕМО" in result["answer"]
    if name == "employee_vacation":
        passed = passed and any(
            source["source_id"] == "demo-employee-vacation"
            for source in result.get("sources", [])
        )
    return passed, observed


def _action_spec(
    name: str, rng: random.Random, case_tag: str = ""
) -> tuple[str, dict, str]:
    if name == "cart_confirm":
        return "add_to_cart", {"sku": "demo-headphones", "quantity": rng.randint(1, 5)}, "cart"
    if name == "booking_confirm":
        return "book_appointment", {"slot": "2026-11-12T12:00:00+03:00"}, "bookings"
    if name == "ad_confirm":
        return "create_ad_campaign", {
            "channel": "search", "budget": str(rng.randint(1_000, 50_000)),
            "title": f"Учебная кампания {case_tag}".strip(),
        }, "ad_campaigns"
    if name == "task_confirm":
        return "assign_task", {
            "assignee": "Анна", "title": f"Учебная задача {case_tag}".strip()
        }, "tasks"
    return "create_support_ticket", {
        "topic": f"Учебное обращение {case_tag}".strip()
    }, "tickets"


def _action_case(
    name: str, manager: RoleContextManager, broker: DemoToolBroker,
    rng: random.Random, case_tag: str = "",
) -> tuple[bool, str]:
    kind, payload, state_key = _action_spec(name, rng, case_tag)
    before = broker.state(manager)
    draft = broker.prepare_action(manager, kind, payload)
    prepared_without_effect = broker.state(manager) == before
    event = broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
    after = broker.state(manager)
    passed = (
        prepared_without_effect and event.status == "simulated"
        and len(after[state_key]) == len(before[state_key]) + 1
    )
    return passed, "simulated" if passed else "state_mismatch"


def _attack_case(
    name: str, manager: RoleContextManager, broker: DemoToolBroker,
    consent_id: str,
) -> tuple[bool, str]:
    if name == "critic_failure":
        model = DeterministicModel(critic_fails=True)
        result = build_chat_graph(manager, model, broker).invoke({
            "query": "Как улучшить продажи?", "cross_role_opt_in": False,
        })
        passed = (
            result["decision"] == "needs_review"
            and "Учебный ответ" not in result["answer"]
            and model.chat_calls == model.critic_calls == 1
        )
        return passed, str(result["decision"])
    if name in {"cart_wrong_role", "task_wrong_role"}:
        kind = "add_to_cart" if name == "cart_wrong_role" else "assign_task"
        payload = (
            {"sku": "demo-headphones", "quantity": 1}
            if name == "cart_wrong_role"
            else {"assignee": "Анна", "title": "Чужая задача"}
        )
        try:
            broker.prepare_action(manager, kind, payload)
        except PermissionError:
            return True, "denied"
        return False, "prepared_without_role"
    kind, payload, state_key = _action_spec("ad_confirm" if name == "revoked_consent" else "cart_confirm", random.Random(1))
    draft = broker.prepare_action(manager, kind, payload)
    before = broker.state(manager)
    if name == "wrong_token":
        token = "incorrect-token"
    elif name == "revoked_consent":
        manager.withdraw_consent(manager.active_role, ConsentScope.LLM_PROCESSING,
                                 "simulation", consent_id)
        token = draft.confirmation_token
    else:
        broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
        before = broker.state(manager)
        token = draft.confirmation_token
    try:
        broker.confirm_action(manager, draft.action_id, token)
    except PermissionError:
        if name == "revoked_consent":
            # После отзыва активной роли нет; проверяем хранилище напрямую.
            unchanged = len(broker._ad_campaigns) == len(before[state_key])
        else:
            unchanged = broker.state(manager) == before
        return unchanged, "denied" if unchanged else "state_changed"
    return False, "executed_without_authorization"


def run_simulation(repetitions: int = 12, seed: int = 20261109) -> dict:
    """Выполнить фиксированный набор сценариев с новым состоянием на эпизод."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    rng = random.Random(seed)
    cases: list[dict] = []
    episode = 0
    for repetition in range(repetitions):
        order = list(SCENARIOS)
        rng.shuffle(order)
        for scenario in order:
            episode += 1
            manager, consent_id = _manager(scenario.role, episode)
            broker = DemoToolBroker()
            try:
                if scenario.family == "chat":
                    passed, observed = _chat_case(
                        scenario.name, scenario.role, manager, broker, rng
                    )
                elif scenario.family == "action":
                    passed, observed = _action_case(
                        scenario.name, manager, broker, rng
                    )
                else:
                    passed, observed = _attack_case(
                        scenario.name, manager, broker, consent_id
                    )
            except Exception as exc:
                passed, observed = False, type(exc).__name__
            cases.append({
                "episode": episode, "repetition": repetition,
                "scenario": scenario.name, "role": scenario.role.value,
                "family": scenario.family, "passed": passed,
                "observed": observed,
            })
    by_family: dict[str, dict[str, int]] = {}
    by_role: dict[str, dict[str, int]] = {}
    for row in cases:
        for group, key in ((by_family, row["family"]), (by_role, row["role"])):
            stats = group.setdefault(key, {"passed": 0, "total": 0})
            stats["total"] += 1
            stats["passed"] += int(row["passed"])
    return {
        "schema_version": 1,
        "seed": seed,
        "repetitions": repetitions,
        "scenario_types": len(SCENARIOS),
        "episodes": len(cases),
        "by_family": by_family,
        "by_role": by_role,
        "failures": [row for row in cases if not row["passed"]],
        "cases": cases,
    }


_LARGE_ROLE_CASES = {
    Role.RETAIL: (
        "retail_balance", "retail_rate_without_source", "retail_legal",
        "cart_confirm", "booking_confirm", "task_wrong_role", "wrong_token",
        "replay_confirm",
    ),
    Role.BUSINESS: (
        "business_cash_gap", "business_unstructured_numbers",
        "business_general", "business_legal", "ad_confirm", "cart_wrong_role",
        "revoked_consent", "critic_failure",
    ),
    Role.EMPLOYEE: (
        "employee_vacation", "employee_real_policy", "employee_unknown",
        "employee_legal", "task_confirm", "ticket_confirm", "cart_wrong_role",
    ),
}


def _alphabetic_tag(value: int) -> str:
    """Уникальный алфавитный код без цифр, чтобы не менять бизнес-маршрут."""
    letters = []
    value += 1
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(ord("a") + remainder))
    return "".join(reversed(letters))


def run_large_simulation(
    per_role: int = 1200, seed: int = 20261109, *, mcp: bool = False
) -> dict:
    """Параметризованные эпизоды по ролям, без сетевых вызовов к модели.

    `per_role` означает число уникальных входных эпизодов, а не число
    независимых рабочих процессов или реальных пользователей.
    """
    if per_role < 1:
        raise ValueError("per_role must be positive")
    rng = random.Random(seed)
    templates = {scenario.name: scenario for scenario in SCENARIOS}
    cases: list[dict] = []
    episode = 0
    for role in Role:
        names = _LARGE_ROLE_CASES[role]
        offset = rng.randrange(len(names))
        for index in range(per_role):
            name = names[(index + offset) % len(names)]
            template = templates[name]
            tag = _alphabetic_tag(index)
            episode += 1
            manager, consent_id = _manager(role, episode)
            # Уникальное исходное состояние даже там, где учебный каталог
            # допускает лишь конечное число товаров и свободных слотов.
            manager.remember(f"Синтетический эпизод {tag}")
            broker = McpDemoToolBroker() if mcp else DemoToolBroker()
            try:
                if template.family == "chat":
                    passed, observed = _chat_case(
                        name, role, manager, broker, rng, tag
                    )
                elif template.family == "action":
                    passed, observed = _action_case(
                        name, manager, broker, rng, tag
                    )
                else:
                    passed, observed = _attack_case(
                        name, manager, broker, consent_id
                    )
            except Exception as exc:
                passed, observed = False, type(exc).__name__
            cases.append({
                "episode": episode, "scenario": name, "role": role.value,
                "family": template.family, "input_key": f"{role.value}:{name}:{tag}",
                "passed": passed, "observed": observed,
            })
    by_role: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    for row in cases:
        for group, key in ((by_role, row["role"]), (by_family, row["family"])):
            stat = group.setdefault(key, {"passed": 0, "total": 0})
            stat["total"] += 1
            stat["passed"] += int(row["passed"])
    return {
        "schema_version": 1, "seed": seed, "per_role": per_role,
        "harness": "in_process_mcp" if mcp else "direct_demo_broker",
        "episodes": len(cases),
        "workflow_templates": sum(len(v) for v in _LARGE_ROLE_CASES.values()),
        "by_role": by_role, "by_family": by_family,
        "failures": [row for row in cases if not row["passed"]],
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=12)
    parser.add_argument("--per-role", type=int, default=0)
    parser.add_argument("--mcp", action="store_true", help="Прогнать через ролевой MCP broker")
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--output", type=Path, default=Path("evals/results/deployment-simulation.json"))
    args = parser.parse_args()
    report = (
        run_large_simulation(args.per_role, args.seed, mcp=args.mcp)
        if args.per_role else run_simulation(args.repetitions, args.seed)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    summary = {key: value for key, value in report.items() if key != "cases"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
