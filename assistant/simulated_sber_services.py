"""Изолированные учебные двойники пяти документированных Sber API MCP-сервисов.

Имена tools и разделение сервисов взяты из публичной документации Sber API.
Ответы и упрощённые входные схемы НЕ являются контрактом промышленного API.
Ни один сетевой запрос в Сбер не выполняется.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from mcp import Client
from mcp.server.mcpserver import MCPServer

from .consent import ConsentScope
from .domain import Role
from .role_context import RoleContextManager


SERVICE_SCOPES = {
    "payment": "MCP_PAYMENT",
    "client_info": "MCP_CLIENT_INFO",
    "statement": "MCP_STATEMENT",
    "encashment": "MCP_ENCASHMENT",
    "placement": "MCP_COMMERCIAL_OFFERS",
    # Ниже локальные учебные scopes, не названия прав Sber API.
    "crm": "DEMO_CRM_READ",
    "hr": "DEMO_HR_READ",
    "it": "DEMO_IT_READ",
    "policy": "DEMO_POLICY_READ",
    "identity": "DEMO_IDENTITY_READ",
}
SERVICE_ROLES = {
    "payment": Role.BUSINESS, "client_info": Role.BUSINESS,
    "statement": Role.BUSINESS, "encashment": Role.BUSINESS,
    "placement": Role.BUSINESS, "crm": Role.BUSINESS,
    "hr": Role.EMPLOYEE, "it": Role.EMPLOYEE,
    "policy": Role.EMPLOYEE, "identity": None,
}
READ_TOOLS = {
    "payment": {"correspondent_rur.get", "rur_payment.get_state", "rur_payment.get_credit_info"},
    "client_info": {"accounts.get_list", "client_info.get_requisites", "client_info.get_card_index"},
    "statement": {"statement.get_summary", "statement.get_rur_transactions",
                  "statement.get_rur_increment"},
    "encashment": {"encashment.get_contracts_list", "encashment.get_objects_list_by_contract"},
    "placement": {"deposit.get_commercial_offers", "minimum_balance.get_commercial_offers"},
    "crm": {"crm.leads.get", "crm.opportunities.get"},
    "hr": {"hr.leave_balance.get", "hr.training_catalog.get"},
    "it": {"it.tickets.get"},
    "policy": {"policy.search"},
    "identity": {"identity.me"},
}


class SimulatedSberMcpGateway:
    """Демо-host: проверяет роль, согласие, scope и владельца до MCP-вызова."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._payment_drafts: dict[str, dict[str, dict]] = {}
        self._pending: dict[str, dict] = {}

    @property
    def payment_drafts(self) -> dict:
        with self._lock:
            return deepcopy(self._payment_drafts)

    @staticmethod
    def _subject(manager: RoleContextManager, required: Role | None = Role.BUSINESS) -> str:
        role = manager.active_role
        if role is None or (required is not None and role is not required):
            raise PermissionError("MCP-сервис недоступен в текущей роли")
        if not manager.check_consent(role, ConsentScope.LLM_PROCESSING):
            raise PermissionError("Согласие отозвано")
        return manager._current_session().subject_hash

    @staticmethod
    def _envelope(service: str, tool: str, data: dict) -> dict:
        return {
            "service": service, "tool": tool, "provenance": "demo_fixture",
            "as_of": "2026-11-09", "data": data,
        }

    def _server(
        self, service: str, subject: str, role: Role | None,
        *, allow_create: bool,
    ) -> MCPServer:
        server = MCPServer(name=f"demo-sber-api-{service}")

        if service == "client_info":
            @server.tool(name="accounts.get_list")
            def accounts_get_list(status: str = "OPEN", includeBlocks: bool = True) -> dict:
                accounts = [{"accountNumber": "DEMO-40702-1", "status": "OPEN",
                             "blocked": False, "currency": "RUB"}]
                if status not in {"OPEN", "ALL"}:
                    accounts = []
                return self._envelope(service, "accounts.get_list", {"accounts": accounts})

            @server.tool(name="client_info.get_requisites")
            def client_info_get_requisites() -> dict:
                return self._envelope(service, "client_info.get_requisites", {
                    "name": "ООО Учебный магазин", "inn": "7700000000",
                    "ogrn": "1000000000000", "taxationSystem": "DEMO_UNKNOWN",
                })

            @server.tool(name="client_info.get_card_index")
            def client_info_get_card_index(accountNumbers: list[str]) -> dict:
                self._require_account_list(accountNumbers)
                return self._envelope(service, "client_info.get_card_index", {
                    "documents_count": 0, "amount": "0.00",
                })

        elif service == "statement":
            @server.tool(name="statement.get_summary")
            def statement_get_summary(accountNumber: str, statementDate: str) -> dict:
                self._require_account(accountNumber)
                self._require_date(statementDate)
                return self._envelope(service, "statement.get_summary", {
                    "accountNumber": accountNumber, "statementDate": statementDate,
                    "opening_balance": "380000.00", "incoming": "25000.00",
                    "outgoing": "5000.00", "closing_balance": "400000.00",
                })

            @server.tool(name="statement.get_rur_transactions")
            def statement_get_rur_transactions(
                accountNumber: str, statementDate: str, page: int = 1
            ) -> dict:
                self._require_account(accountNumber)
                self._require_date(statementDate)
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                transactions = ([
                    {"id": "DEMO-TX-IN", "amount": "25000.00", "direction": "IN"},
                    {"id": "DEMO-TX-OUT", "amount": "5000.00", "direction": "OUT"},
                ] if page == 1 else [])
                return self._envelope(service, "statement.get_rur_transactions", {
                    "page": page, "transactions": transactions,
                })

            @server.tool(name="statement.get_rur_increment")
            def statement_get_rur_increment(
                accountNumber: str, lastModifyDate: str, page: int = 1
            ) -> dict:
                from datetime import datetime
                self._require_account(accountNumber)
                try:
                    datetime.fromisoformat(lastModifyDate)
                except ValueError as exc:
                    raise ValueError("Неверное время инкремента") from exc
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                return self._envelope(service, "statement.get_rur_increment", {
                    "page": page, "lastModifyDate": lastModifyDate,
                    "transactions": [{"id": "DEMO-TX-RECENT", "amount": "25000.00"}]
                    if page == 1 else [],
                })

        elif service == "payment":
            @server.tool(name="correspondent_rur.get")
            def correspondent_rur_get(searchCriteria: str) -> dict:
                if searchCriteria not in {"7700000000", "ООО Учебный поставщик"}:
                    return self._envelope(service, "correspondent_rur.get", {"counterparties": []})
                return self._envelope(service, "correspondent_rur.get", {
                    "counterparties": [{"inn": "7700000000", "name": "ООО Учебный поставщик",
                                        "accounts": ["DEMO-PAYEE-1", "DEMO-PAYEE-2"]}],
                })

            @server.tool(name="rur_payment.get_state")
            def rur_payment_get_state(externalId: str) -> dict:
                with self._lock:
                    draft = self._payment_drafts.get(subject, {}).get(externalId)
                if externalId == "demo-payment-1":
                    status = "IMPLEMENTED"  # Только готовая учебная запись.
                elif draft is not None:
                    status = draft["bankStatus"]
                else:
                    raise LookupError("Учебный платеж не найден")
                return self._envelope(service, "rur_payment.get_state", {
                    "externalId": externalId, "bankStatus": status,
                })

            @server.tool(name="rur_payment.get_credit_info")
            def rur_payment_get_credit_info() -> dict:
                return self._envelope(service, "rur_payment.get_credit_info", {
                    "credit_lines": [], "note": "ДЕМО: доступная ВКЛ не задана",
                })

            if allow_create:
                @server.tool(name="rur_payment.create_invoice")
                def rur_payment_create_invoice(
                    externalId: str, amount: str, payeeInn: str,
                    payeeAccount: str, purpose: str,
                ) -> dict:
                    payload = self._validate_payment({
                        "externalId": externalId, "amount": amount,
                        "payeeInn": payeeInn, "payeeAccount": payeeAccount,
                        "purpose": purpose,
                    })
                    with self._lock:
                        drafts = self._payment_drafts.setdefault(subject, {})
                        if externalId in drafts:
                            raise ValueError("Повторный externalId")
                        draft = {**payload, "bankStatus": "CREATED", "executed": False,
                                 "signed": False, "provenance": "demo_fixture"}
                        drafts[externalId] = draft
                    return self._envelope(service, "rur_payment.create_invoice", draft)

        elif service == "encashment":
            @server.tool(name="encashment.get_contracts_list")
            def encashment_get_contracts_list(page: int = 1, isActual: bool = True) -> dict:
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                contracts = ([{"contractId": "DEMO-ENC-1", "isActual": True}]
                             if page == 1 and isActual else [])
                return self._envelope(service, "encashment.get_contracts_list", {
                    "page": page, "contracts": contracts,
                })

            @server.tool(name="encashment.get_objects_list_by_contract")
            def encashment_get_objects_list_by_contract(
                contractId: str, page: int = 1
            ) -> dict:
                if contractId != "DEMO-ENC-1":
                    raise PermissionError("Чужой учебный договор")
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                return self._envelope(service, "encashment.get_objects_list_by_contract", {
                    "objects": [{"objectId": "DEMO-STORE-1", "isActual": True}]
                    if page == 1 else [],
                })

        elif service == "placement":
            @server.tool(name="deposit.get_commercial_offers")
            def deposit_get_commercial_offers(page: int = 1) -> dict:
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                return self._envelope(service, "deposit.get_commercial_offers", {
                    "offers": [{"offerId": "DEMO-DEPOSIT-1", "terms": "только учебное предложение"}]
                    if page == 1 else [],
                })

            @server.tool(name="minimum_balance.get_commercial_offers")
            def minimum_balance_get_commercial_offers(page: int = 1) -> dict:
                if page < 1:
                    raise ValueError("Страница начинается с 1")
                return self._envelope(service, "minimum_balance.get_commercial_offers", {
                    "offers": [{"offerId": "DEMO-NSO-1", "terms": "только учебное предложение"}]
                    if page == 1 else [],
                })

        elif service == "crm":
            @server.tool(name="crm.leads.get")
            def crm_leads_get() -> dict:
                return self._envelope(service, "crm.leads.get", {
                    "leads": [{"id": "DEMO-LEAD-1", "status": "new",
                               "source": "учебная заявка"}],
                })

            @server.tool(name="crm.opportunities.get")
            def crm_opportunities_get() -> dict:
                return self._envelope(service, "crm.opportunities.get", {
                    "opportunities": [{"id": "DEMO-OPP-1", "stage": "contacted",
                                       "amount": "15000.00"}],
                })

        elif service == "hr":
            @server.tool(name="hr.leave_balance.get")
            def hr_leave_balance_get() -> dict:
                return self._envelope(service, "hr.leave_balance.get", {
                    "days_available": 14, "note": "только учебная HR-система",
                })

            @server.tool(name="hr.training_catalog.get")
            def hr_training_catalog_get() -> dict:
                return self._envelope(service, "hr.training_catalog.get", {
                    "courses": [{"id": "DEMO-COURSE-1", "title": "Работа с данными"}],
                })

        elif service == "it":
            @server.tool(name="it.tickets.get")
            def it_tickets_get() -> dict:
                return self._envelope(service, "it.tickets.get", {
                    "tickets": [{"id": "DEMO-IT-1", "status": "open",
                                 "topic": "Учебный VPN"}],
                })

        elif service == "policy":
            @server.tool(name="policy.search")
            def policy_search(query: str = "") -> dict:
                if "отпуск" in query.lower():
                    docs = [{"source_id": "demo-employee-vacation", "version": "demo-1",
                             "title": "Учебный отпуск", "approved": False}]
                else:
                    docs = []
                return self._envelope(service, "policy.search", {"documents": docs})

        elif service == "identity":
            @server.tool(name="identity.me")
            def identity_me() -> dict:
                return self._envelope(service, "identity.me", {
                    "role": role.value if role else "unknown", "identity": "demo_subject",
                    "authenticated_by": "local_demo_token",
                })
        else:
            raise PermissionError("Неизвестный MCP-сервис")
        return server

    @staticmethod
    def _require_account(account: str) -> None:
        if account != "DEMO-40702-1":
            raise PermissionError("Счёт не принадлежит учебному субъекту")

    @classmethod
    def _require_account_list(cls, accounts: list[str]) -> None:
        for account in accounts:
            cls._require_account(account)

    @staticmethod
    def _require_date(value: str) -> None:
        from datetime import date
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Дата должна быть YYYY-MM-DD") from exc

    @staticmethod
    def _validate_payment(payload: dict) -> dict:
        try:
            amount = Decimal(str(payload.get("amount", "")))
        except InvalidOperation as exc:
            raise ValueError("Неверная сумма") from exc
        if not amount.is_finite() or not Decimal("0") < amount <= Decimal("1000000"):
            raise ValueError("Сумма вне учебного лимита")
        external_id = str(payload.get("externalId", ""))
        if not external_id.startswith("demo-") or len(external_id) > 80:
            raise ValueError("Неверный учебный externalId")
        if payload.get("payeeInn") != "7700000000" or payload.get("payeeAccount") not in {"DEMO-PAYEE-1", "DEMO-PAYEE-2"}:
            raise ValueError("Контрагент не найден в учебном справочнике")
        purpose = str(payload.get("purpose", "")).strip()
        if not 1 <= len(purpose) <= 210:
            raise ValueError("Неверное назначение платежа")
        return {"externalId": external_id, "amount": str(amount),
                "payeeInn": "7700000000", "payeeAccount": payload["payeeAccount"],
                "purpose": purpose}

    async def _call(self, service: str, subject: str, tool: str,
                    args: dict, *, role: Role | None = Role.BUSINESS,
                    allow_create: bool = False) -> dict:
        async with Client(self._server(service, subject, role, allow_create=allow_create)) as client:
            result = await client.call_tool(tool, args)
        if result.is_error or not result.content:
            raise RuntimeError("Учебный MCP-сервис отказал в запросе")
        try:
            value = json.loads(result.content[0].text)
        except (AttributeError, ValueError) as exc:
            raise RuntimeError("Некорректный MCP-ответ") from exc
        if (not isinstance(value, dict) or value.get("service") != service
                or value.get("tool") != tool or value.get("provenance") != "demo_fixture"
                or not isinstance(value.get("data"), dict)):
            raise RuntimeError("MCP-ответ не прошёл проверку происхождения")
        return value

    def call(self, manager: RoleContextManager, service: str, tool: str,
             args: dict, *, scopes: set[str] | None = None) -> dict:
        required = SERVICE_SCOPES.get(service)
        if required is None or tool not in READ_TOOLS[service]:
            raise PermissionError("MCP-инструмент не разрешён")
        subject = self._subject(manager, SERVICE_ROLES[service])
        granted = scopes if scopes is not None else {"MCP_COMMON", *SERVICE_SCOPES.values()}
        if not {"MCP_COMMON", required}.issubset(granted):
            raise PermissionError("Недостаточно учебных MCP scopes")
        # Проверка владельца перед передачей данных MCP-серверу.
        if "accountNumber" in args:
            self._require_account(str(args["accountNumber"]))
        if "accountNumbers" in args:
            self._require_account_list(args["accountNumbers"])
        if "contractId" in args and args["contractId"] != "DEMO-ENC-1":
            raise PermissionError("Чужой учебный договор")
        result = asyncio.run(self._call(
            service, subject, tool, args, role=manager.active_role,
        ))
        # Повторная проверка на случай отзыва согласия во время вызова.
        self._subject(manager, SERVICE_ROLES[service])
        return result

    def prepare_payment_draft(self, manager: RoleContextManager,
                              payload: dict) -> dict:
        subject = self._subject(manager)
        clean = self._validate_payment(payload)
        session = manager._current_session()
        pending = {
            "action_id": secrets.token_urlsafe(16),
            "confirmation_token": secrets.token_urlsafe(24),
            "subject": subject, "session_id": session.session_id,
            "payload": clean, "expires_at": time.time() + 300,
        }
        with self._lock:
            self._pending[pending["action_id"]] = pending
        return {"action_id": pending["action_id"],
                "confirmation_token": pending["confirmation_token"],
                "payload": deepcopy(clean), "status": "pending_user_confirmation"}

    def confirm_payment_draft(self, manager: RoleContextManager,
                              action_id: str, token: str) -> dict:
        subject = self._subject(manager)
        with self._lock:
            pending = self._pending.get(action_id)
            if (pending is None or pending["subject"] != subject
                    or pending["session_id"] != manager._current_session().session_id
                    or pending["expires_at"] < time.time()
                    or not secrets.compare_digest(pending["confirmation_token"], token)):
                raise PermissionError("Черновик недоступен или подтверждение неверно")
            self._pending.pop(action_id)
        result = asyncio.run(self._call(
            "payment", subject, "rur_payment.create_invoice",
            pending["payload"], role=Role.BUSINESS, allow_create=True,
        ))
        self._subject(manager)
        draft = result["data"]
        if draft.get("bankStatus") != "CREATED" or draft.get("executed") is not False:
            raise RuntimeError("MCP-черновик имеет недопустимый статус")
        return draft
