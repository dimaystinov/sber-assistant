"""Изолированные симуляции банковских инструментов без внешних вызовов."""
from __future__ import annotations

import secrets
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .consent import ConsentScope
from .domain import Role
from .knowledge import DemoKnowledgeBase, KnowledgeDocument
from .role_context import RoleContextManager


@dataclass(frozen=True)
class ToolResult:
    name: str
    role: Role
    text: str
    source_id: str
    version: str
    verified: bool
    provenance: str = "demo_fixture"


@dataclass(frozen=True)
class PendingPayment:
    action_id: str
    confirmation_token: str
    amount: Decimal
    recipient: str
    role: Role
    subject_hash: str
    session_id: str
    expires_at: float


@dataclass(frozen=True)
class PaymentEvent:
    action_id: str
    amount: Decimal
    recipient: str
    status: str


@dataclass(frozen=True)
class PendingAction:
    action_id: str
    confirmation_token: str
    kind: str
    role: Role
    subject_hash: str
    session_id: str
    payload: dict
    expires_at: float


@dataclass(frozen=True)
class ActionEvent:
    action_id: str
    kind: str
    status: str
    payload: dict


class DemoToolBroker:
    """Серверный broker: модель не может вызвать confirm_payment()."""

    _READ_ROLES = {
        "retail_balance": Role.RETAIL,
        "retail_catalog": Role.RETAIL,
        "business_cash_position": Role.BUSINESS,
        "business_competitors": Role.BUSINESS,
        "business_ads": Role.BUSINESS,
        "employee_procedure": Role.EMPLOYEE,
        "employee_tasks": Role.EMPLOYEE,
        "employee_performance": Role.EMPLOYEE,
    }
    _ACTION_ROLES = {
        "add_to_cart": Role.RETAIL,
        "book_appointment": Role.RETAIL,
        "create_ad_campaign": Role.BUSINESS,
        "assign_task": Role.EMPLOYEE,
        "create_support_ticket": Role.EMPLOYEE,
    }
    _CATALOG = {
        "demo-headphones": {"name": "Учебные наушники", "price": "2490"},
        "demo-router": {"name": "Учебный роутер", "price": "3990"},
    }
    _SLOTS = ("2026-11-12T12:00:00+03:00", "2026-11-13T15:00:00+03:00")

    def __init__(self) -> None:
        self.knowledge = DemoKnowledgeBase()
        self._pending: dict[str, PendingPayment] = {}
        self._events: list[PaymentEvent] = []
        self._pending_actions: dict[str, PendingAction] = {}
        self._action_events: list[ActionEvent] = []
        self._cart: list[dict] = []
        self._bookings: list[dict] = []
        self._ad_campaigns: list[dict] = []
        self._tasks: list[dict] = [
            {"assignee": "Анна", "title": "Разобрать учебное обращение", "status": "done"},
            {"assignee": "Илья", "title": "Проверить учебную заявку", "status": "open"},
        ]
        self._tickets: list[dict] = []
        self._lock = threading.RLock()

    @property
    def events(self) -> tuple[PaymentEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @staticmethod
    def _session(manager: RoleContextManager, required: Role):
        if manager.active_role is not required:
            raise PermissionError("Инструмент недоступен в текущей роли")
        if not manager.check_consent(required, ConsentScope.LLM_PROCESSING):
            raise PermissionError("Согласие на обработку не активно")
        return manager._current_session()

    def knowledge_search(
        self, manager: RoleContextManager, query: str
    ) -> list[KnowledgeDocument]:
        role = manager.active_role
        if role is None:
            raise PermissionError("Активная роль не выбрана")
        self._session(manager, role)
        return self.knowledge.search(role, query)

    def read(
        self, manager: RoleContextManager, name: str, query: str = ""
    ) -> ToolResult:
        required = self._READ_ROLES.get(name)
        if required is None:
            raise PermissionError("Неизвестный инструмент")
        self._session(manager, required)
        if name == "retail_balance":
            return ToolResult(
                name, required,
                "ДЕМО: учебный остаток счёта — 12 345,67 ₽. Это не данные банка.",
                "demo-retail-balance", "2026-11-09", True,
            )
        if name == "retail_catalog":
            return ToolResult(
                name, required,
                "ДЕМО: каталог — учебные наушники 2 490 ₽, учебный роутер "
                "3 990 ₽. Корзина и бронирование работают только в симуляции.",
                "demo-retail-catalog", "2026-11-09", True,
            )
        if name == "business_cash_position":
            return ToolResult(
                name, required,
                "ДЕМО: доступно 400 000 ₽; платёж 700 000 ₽ через 10 дней. "
                "Это не данные банка.",
                "demo-business-cash", "2026-11-09", True,
            )
        if name == "business_competitors":
            return ToolResult(
                name, required,
                "ДЕМО: конкурент А продаёт аналог за 2 700 ₽, конкурент Б "
                "за 2 950 ₽; ваши учебные данные: цена 2 900 ₽, себестоимость "
                "1 900 ₽. Данные вымышлены и не являются рыночной аналитикой.",
                "demo-business-competitors", "2026-11-09", True,
            )
        if name == "business_ads":
            return ToolResult(
                name, required,
                "ДЕМО: учебная реклама — 10 000 показов, 200 кликов, "
                "расход 8 000 ₽, 10 заказов. Все показатели вымышлены.",
                "demo-business-ads", "2026-11-09", True,
            )
        if name == "employee_tasks":
            with self._lock:
                tasks = deepcopy(self._tasks)
            return ToolResult(
                name, required,
                f"ДЕМО: учебные задачи: {tasks}. Источник: демо-реестр задач.",
                "demo-employee-tasks", "2026-11-09", True,
            )
        if name == "employee_performance":
            with self._lock:
                done = sum(task["status"] == "done" for task in self._tasks)
                total = len(self._tasks)
            return ToolResult(
                name, required,
                f"ДЕМО: выполнено {done} из {total} учебных задач. Источник: "
                "демо-реестр задач. Это прозрачная сводка, не оценка сотрудника.",
                "demo-employee-performance", "2026-11-09", True,
            )
        documents = self.knowledge.search(required, query or "обучение", k=1)
        if not documents:
            raise LookupError("Для вопроса нет учебной инструкции")
        document = documents[0]
        return ToolResult(
            name, required, document.text, document.source_id,
            document.version, True,
        )

    def state(self, manager: RoleContextManager) -> dict:
        role = manager.active_role
        if role is None:
            raise PermissionError("Активная роль не выбрана")
        self._session(manager, role)
        with self._lock:
            if role is Role.RETAIL:
                return deepcopy({
                    "catalog": self._CATALOG, "slots": self._SLOTS,
                    "cart": self._cart, "bookings": self._bookings,
                })
            if role is Role.BUSINESS:
                return deepcopy({"ad_campaigns": self._ad_campaigns})
            return deepcopy({"tasks": self._tasks, "tickets": self._tickets})

    def prepare_action(
        self, manager: RoleContextManager, kind: str, payload: dict
    ) -> PendingAction:
        required = self._ACTION_ROLES.get(kind)
        if required is None:
            raise PermissionError("Неизвестное действие")
        session = self._session(manager, required)
        clean = self._validate_action(kind, payload)
        draft = PendingAction(
            secrets.token_urlsafe(16), secrets.token_urlsafe(24), kind,
            required, session.subject_hash, session.session_id, clean,
            time.time() + 300,
        )
        with self._lock:
            self._pending_actions[draft.action_id] = draft
        return draft

    def confirm_action(
        self, manager: RoleContextManager, action_id: str,
        confirmation_token: str,
    ) -> ActionEvent:
        with self._lock:
            draft = self._pending_actions.get(action_id)
            if draft is None:
                raise PermissionError("Черновик не найден")
            session = self._session(manager, draft.role)
            if (
                draft.expires_at < time.time()
                or draft.subject_hash != session.subject_hash
                or draft.session_id != session.session_id
                or not secrets.compare_digest(
                    draft.confirmation_token, confirmation_token
                )
            ):
                raise PermissionError("Черновик недоступен или подтверждение неверно")
            self._pending_actions.pop(action_id)
            item = deepcopy(draft.payload)
            if draft.kind == "add_to_cart":
                self._cart.append(item)
            elif draft.kind == "book_appointment":
                self._bookings.append(item)
            elif draft.kind == "create_ad_campaign":
                self._ad_campaigns.append(item)
            elif draft.kind == "assign_task":
                self._tasks.append({**item, "status": "open"})
            elif draft.kind == "create_support_ticket":
                self._tickets.append({**item, "status": "open"})
            event = ActionEvent(action_id, draft.kind, "simulated", item)
            self._action_events.append(event)
            return event

    def _validate_action(self, kind: str, payload: dict) -> dict:
        if kind == "add_to_cart":
            sku = payload.get("sku")
            quantity = payload.get("quantity")
            if sku not in self._CATALOG or type(quantity) is not int or not 1 <= quantity <= 5:
                raise ValueError("Неверный товар или количество")
            return {"sku": sku, "quantity": quantity}
        if kind == "book_appointment":
            slot = payload.get("slot")
            if slot not in self._SLOTS:
                raise ValueError("Недоступный учебный слот")
            return {"slot": slot}
        if kind == "create_ad_campaign":
            channel = payload.get("channel")
            title = str(payload.get("title", "")).strip()
            try:
                budget = Decimal(str(payload.get("budget")))
            except InvalidOperation as exc:
                raise ValueError("Неверный бюджет") from exc
            if (
                channel not in {"search", "social"}
                or not budget.is_finite()
                or not 0 < budget <= 50000
                or not 1 <= len(title) <= 80
            ):
                raise ValueError("Недопустимые параметры рекламы")
            return {"channel": channel, "budget": str(budget), "title": title}
        if kind == "assign_task":
            assignee = payload.get("assignee")
            title = str(payload.get("title", "")).strip()
            if assignee not in {"Анна", "Илья"} or not 1 <= len(title) <= 120:
                raise ValueError("Недопустимая учебная задача")
            return {"assignee": assignee, "title": title}
        topic = str(payload.get("topic", "")).strip()
        if not 1 <= len(topic) <= 160:
            raise ValueError("Укажите тему обращения")
        return {"topic": topic}

    def prepare_payment(
        self, manager: RoleContextManager, amount: str, recipient: str
    ) -> PendingPayment:
        session = self._session(manager, Role.BUSINESS)
        try:
            value = Decimal(amount)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Некорректная сумма") from exc
        if not value.is_finite() or value <= 0 or value > Decimal("1000000"):
            raise ValueError("Сумма вне учебного лимита")
        if value.as_tuple().exponent < -2:
            raise ValueError("Допускается не более двух знаков после запятой")
        recipient = recipient.strip()
        if not recipient or len(recipient) > 100:
            raise ValueError("Некорректный получатель")
        draft = PendingPayment(
            action_id=secrets.token_urlsafe(16),
            confirmation_token=secrets.token_urlsafe(24),
            amount=value,
            recipient=recipient,
            role=Role.BUSINESS,
            subject_hash=session.subject_hash,
            session_id=session.session_id,
            expires_at=time.time() + 300,
        )
        with self._lock:
            self._pending[draft.action_id] = draft
        return draft

    def confirm_payment(
        self, manager: RoleContextManager, action_id: str,
        confirmation_token: str,
    ) -> PaymentEvent:
        session = self._session(manager, Role.BUSINESS)
        with self._lock:
            draft = self._pending.get(action_id)
            if (
                draft is None
                or draft.expires_at < time.time()
                or draft.subject_hash != session.subject_hash
                or draft.session_id != session.session_id
                or not secrets.compare_digest(
                    draft.confirmation_token, confirmation_token
                )
            ):
                raise PermissionError("Черновик недоступен или подтверждение неверно")
            self._pending.pop(action_id)
            event = PaymentEvent(
                action_id=draft.action_id,
                amount=draft.amount,
                recipient=draft.recipient,
                status="simulated",
            )
            self._events.append(event)
            return event
