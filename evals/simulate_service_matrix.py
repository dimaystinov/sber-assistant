"""Расширенная симуляция сервисов MCP по трём ролям.

Эпизоды параметризованы по субъекту и отдельному состоянию. Это проверка
контрактов учебных двойников, не нагрузочный тест Sber API и не оценка LLM.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from assistant.chat_graph import build_chat_graph
from assistant.consent import ConsentScope, ConsentService
from assistant.demo_tools import DemoToolBroker
from assistant.domain import Role, SubjectIdentity
from assistant.mcp_tools import McpDemoToolBroker
from assistant.role_context import RoleContextManager
from assistant.simulated_sber_services import SimulatedSberMcpGateway
from evals.simulate_deployment import DeterministicModel


@dataclass(frozen=True)
class Case:
    name: str
    role: Role
    service: str
    tool: str = ""
    args: tuple[tuple[str, object], ...] = ()
    expected_key: str = ""

    def arguments(self) -> dict:
        return dict(self.args)


BUSINESS_READS = (
    Case("accounts", Role.BUSINESS, "client_info", "accounts.get_list", expected_key="accounts"),
    Case("requisites", Role.BUSINESS, "client_info", "client_info.get_requisites", expected_key="inn"),
    Case("card_index", Role.BUSINESS, "client_info", "client_info.get_card_index",
         (("accountNumbers", ["DEMO-40702-1"]),), "documents_count"),
    Case("statement_summary", Role.BUSINESS, "statement", "statement.get_summary",
         (("accountNumber", "DEMO-40702-1"), ("statementDate", "2026-11-09")), "closing_balance"),
    Case("statement_transactions", Role.BUSINESS, "statement", "statement.get_rur_transactions",
         (("accountNumber", "DEMO-40702-1"), ("statementDate", "2026-11-09"), ("page", 1)), "transactions"),
    Case("statement_increment", Role.BUSINESS, "statement", "statement.get_rur_increment",
         (("accountNumber", "DEMO-40702-1"), ("lastModifyDate", "2026-11-09T09:00:00"), ("page", 1)), "transactions"),
    Case("counterparty", Role.BUSINESS, "payment", "correspondent_rur.get",
         (("searchCriteria", "7700000000"),), "counterparties"),
    Case("payment_status", Role.BUSINESS, "payment", "rur_payment.get_state",
         (("externalId", "demo-payment-1"),), "bankStatus"),
    Case("credit_info", Role.BUSINESS, "payment", "rur_payment.get_credit_info", expected_key="credit_lines"),
    Case("encashment_contracts", Role.BUSINESS, "encashment", "encashment.get_contracts_list",
         (("page", 1),), "contracts"),
    Case("encashment_objects", Role.BUSINESS, "encashment", "encashment.get_objects_list_by_contract",
         (("contractId", "DEMO-ENC-1"), ("page", 1)), "objects"),
    Case("deposit_offers", Role.BUSINESS, "placement", "deposit.get_commercial_offers",
         (("page", 1),), "offers"),
    Case("nso_offers", Role.BUSINESS, "placement", "minimum_balance.get_commercial_offers",
         (("page", 1),), "offers"),
    Case("crm_leads", Role.BUSINESS, "crm", "crm.leads.get", expected_key="leads"),
    Case("crm_opportunities", Role.BUSINESS, "crm", "crm.opportunities.get", expected_key="opportunities"),
    Case("business_identity", Role.BUSINESS, "identity", "identity.me", expected_key="role"),
)
BUSINESS_OTHER = tuple(Case(name, Role.BUSINESS, service) for name, service in (
    ("payment_draft", "payment"), ("payment_wrong_token", "payment"),
    ("payment_replay", "payment"), ("payment_bad_amount", "payment"),
    ("missing_scope", "statement"), ("foreign_account", "statement"),
    ("business_cash_gap", "calculator"), ("ad_confirm", "advertising"),
))
RETAIL = tuple(Case(name, Role.RETAIL, service) for name, service in (
    ("retail_identity", "identity"), ("retail_balance", "retail_account"),
    ("retail_catalog", "retail_catalog"), ("cart_confirm", "retail_cart"),
    ("booking_confirm", "retail_booking"), ("retail_wrong_business", "client_info"),
    ("retail_wrong_employee", "hr"), ("cart_wrong_token", "retail_cart"),
    ("cart_replay", "retail_cart"), ("retail_revoked", "identity"),
    ("retail_rate_gate", "retail_policy"), ("retail_legal_gate", "retail_policy"),
))
EMPLOYEE = tuple(Case(name, Role.EMPLOYEE, service) for name, service in (
    ("employee_identity", "identity"), ("hr_leave", "hr"),
    ("hr_training", "hr"), ("it_tickets", "it"),
    ("policy_search", "policy"), ("employee_tasks", "employee_tasks"),
    ("employee_performance", "employee_performance"),
    ("task_confirm", "employee_tasks"), ("ticket_confirm", "it"),
    ("employee_wrong_business", "payment"), ("employee_wrong_crm", "crm"),
    ("employee_revoked", "hr"), ("employee_real_policy_gate", "policy"),
    ("employee_unknown_policy_gate", "policy"),
))
BY_ROLE = {Role.RETAIL: RETAIL, Role.BUSINESS: BUSINESS_READS + BUSINESS_OTHER,
           Role.EMPLOYEE: EMPLOYEE}


def _manager(role: Role, episode: int) -> RoleContextManager:
    manager = RoleContextManager(
        SubjectIdentity(f"service-matrix-person-{episode}"), ConsentService()
    )
    manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "simulation")
    manager.switch_role(role, "simulation")
    return manager


def _denied(fn: Callable[[], object]) -> bool:
    try:
        fn()
    except PermissionError:
        return True
    return False


def _payment_payload(tag: str, amount: str = "1250.00") -> dict:
    return {"externalId": f"demo-matrix-payment-{tag}", "amount": amount,
            "payeeInn": "7700000000", "payeeAccount": "DEMO-PAYEE-1",
            "purpose": f"Учебный счет {tag}"}


def _run(case: Case, manager: RoleContextManager,
         gateway: SimulatedSberMcpGateway, broker: McpDemoToolBroker,
         tag: str) -> tuple[bool, str]:
    name = case.name
    if case.tool:
        result = gateway.call(manager, case.service, case.tool, case.arguments())
        return case.expected_key in result["data"], "read"
    if name.endswith("identity"):
        result = gateway.call(manager, "identity", "identity.me", {})
        return result["data"]["role"] == case.role.value, "identity"
    if name in {"retail_balance", "retail_catalog", "employee_tasks", "employee_performance"}:
        tool = {"retail_balance": "retail_balance", "retail_catalog": "retail_catalog",
                "employee_tasks": "employee_tasks", "employee_performance": "employee_performance"}[name]
        result = broker.read(manager, tool)
        return result.verified and result.provenance == "demo_fixture", "read"
    if name in {"cart_confirm", "booking_confirm", "ad_confirm", "task_confirm", "ticket_confirm"}:
        specs = {
            "cart_confirm": ("add_to_cart", {"sku": "demo-headphones", "quantity": 1}),
            "booking_confirm": ("book_appointment", {"slot": "2026-11-12T12:00:00+03:00"}),
            "ad_confirm": ("create_ad_campaign", {"channel": "search", "budget": "1200", "title": f"Учебная реклама {tag}"}),
            "task_confirm": ("assign_task", {"assignee": "Анна", "title": f"Учебная задача {tag}"}),
            "ticket_confirm": ("create_support_ticket", {"topic": f"Учебный ИТ-сбой {tag}"}),
        }
        kind, payload = specs[name]
        before = broker.state(manager)
        draft = broker.prepare_action(manager, kind, payload)
        unchanged = broker.state(manager) == before
        event = broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
        return unchanged and event.status == "simulated", "simulated"
    if name in {"cart_wrong_token", "cart_replay"}:
        draft = broker.prepare_action(manager, "add_to_cart", {"sku": "demo-router", "quantity": 1})
        if name == "cart_wrong_token":
            return _denied(lambda: broker.confirm_action(manager, draft.action_id, "wrong")), "denied"
        broker.confirm_action(manager, draft.action_id, draft.confirmation_token)
        return _denied(lambda: broker.confirm_action(manager, draft.action_id, draft.confirmation_token)), "denied"
    if name in {"retail_wrong_business", "employee_wrong_business"}:
        return _denied(lambda: gateway.call(manager, "client_info", "accounts.get_list", {})), "denied"
    if name in {"retail_wrong_employee", "employee_wrong_crm"}:
        service, tool = (("hr", "hr.leave_balance.get") if case.role is Role.RETAIL
                         else ("crm", "crm.leads.get"))
        return _denied(lambda: gateway.call(manager, service, tool, {})), "denied"
    if name in {"retail_revoked", "employee_revoked"}:
        manager.withdraw_consent(case.role, ConsentScope.LLM_PROCESSING, "simulation")
        return _denied(lambda: gateway.call(manager, case.service,
            "identity.me" if case.role is Role.RETAIL else "hr.leave_balance.get", {})), "denied"
    if name in {"retail_rate_gate", "retail_legal_gate", "employee_real_policy_gate", "employee_unknown_policy_gate"}:
        queries = {"retail_rate_gate": "Какая ставка по ипотеке сегодня?",
                   "retail_legal_gate": "Как по закону обжаловать отказ банка?",
                   "employee_real_policy_gate": "Какой действующий внутренний регламент Сбера?",
                   "employee_unknown_policy_gate": "Как оформить неизвестный рабочий процесс?"}
        expected = {"retail_rate_gate": "live_data_required",
                    "retail_legal_gate": "legal_source_required",
                    "employee_real_policy_gate": "internal_policy_required",
                    "employee_unknown_policy_gate": "source_required"}
        result = build_chat_graph(manager, DeterministicModel(), broker).invoke({"query": queries[name]})
        return result["decision"] == expected[name], result["decision"]
    if name in {"hr_leave", "hr_training", "it_tickets", "policy_search"}:
        specs = {"hr_leave": ("hr", "hr.leave_balance.get", {}),
                 "hr_training": ("hr", "hr.training_catalog.get", {}),
                 "it_tickets": ("it", "it.tickets.get", {}),
                 "policy_search": ("policy", "policy.search", {"query": "отпуск"})}
        service, tool, args = specs[name]
        result = gateway.call(manager, service, tool, args)
        if name == "policy_search":
            return result["data"]["documents"][0]["approved"] is False, "demo_document"
        return bool(result["data"]), "read"
    if name == "business_cash_gap":
        result = broker.calculate_cash_gap(manager, {
            "kind": "cash_gap", "amount_due": "700000", "available": "400000",
            "days_until_due": 10,
        })
        return "300 000" in result, "calculated"
    if name == "missing_scope":
        return _denied(lambda: gateway.call(manager, "statement", "statement.get_summary", {
            "accountNumber": "DEMO-40702-1", "statementDate": "2026-11-09",
        }, scopes={"MCP_COMMON"})), "denied"
    if name == "foreign_account":
        return _denied(lambda: gateway.call(manager, "statement", "statement.get_summary", {
            "accountNumber": "DEMO-OTHER", "statementDate": "2026-11-09",
        })), "denied"
    if name == "payment_bad_amount":
        try:
            gateway.prepare_payment_draft(manager, _payment_payload(tag, "-1"))
        except ValueError:
            return True, "denied"
        return False, "unexpected_prepare"
    if name in {"payment_draft", "payment_wrong_token", "payment_replay"}:
        pending = gateway.prepare_payment_draft(manager, _payment_payload(tag))
        if name == "payment_wrong_token":
            return _denied(lambda: gateway.confirm_payment_draft(manager, pending["action_id"], "wrong")), "denied"
        draft = gateway.confirm_payment_draft(manager, pending["action_id"], pending["confirmation_token"])
        valid = draft["bankStatus"] == "CREATED" and draft["executed"] is False
        if name == "payment_replay":
            valid = valid and _denied(lambda: gateway.confirm_payment_draft(
                manager, pending["action_id"], pending["confirmation_token"]
            ))
        return valid, "draft_created"
    raise AssertionError(f"Unknown service scenario {name}")


def run_service_matrix(per_role: int = 1200, seed: int = 20261110) -> dict:
    if per_role < 1:
        raise ValueError("per_role must be positive")
    rng = random.Random(seed)
    rows = []
    episode = 0
    for role in Role:
        templates = BY_ROLE[role]
        offset = rng.randrange(len(templates))
        for index in range(per_role):
            case = templates[(index + offset) % len(templates)]
            episode += 1
            manager = _manager(role, episode)
            gateway = SimulatedSberMcpGateway()
            broker = McpDemoToolBroker()
            tag = f"{role.value}-{episode}"
            try:
                passed, observed = _run(case, manager, gateway, broker, tag)
            except Exception as exc:
                passed, observed = False, type(exc).__name__
            rows.append({"episode": episode, "scenario": case.name,
                         "service": case.service, "role": role.value,
                         "input_key": tag, "passed": passed, "observed": observed})
    by_role = {role.value: {"passed": sum(row["passed"] for row in rows if row["role"] == role.value),
                            "total": per_role} for role in Role}
    return {"schema_version": 1, "seed": seed, "per_role": per_role,
            "episodes": len(rows), "scenario_types": sum(map(len, BY_ROLE.values())),
            "service_families": sorted({case.service for cases in BY_ROLE.values() for case in cases}),
            "by_role": by_role, "failures": [row for row in rows if not row["passed"]],
            "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-role", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--output", type=Path, default=Path("evals/results/service-matrix.json"))
    args = parser.parse_args()
    report = run_service_matrix(args.per_role, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
