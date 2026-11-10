"""Версионированная демонстрационная база знаний с изоляцией по роли."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .domain import Role


@dataclass(frozen=True)
class KnowledgeDocument:
    source_id: str
    role: Role
    title: str
    text: str
    version: str
    effective_from: date
    keywords: tuple[str, ...]
    provenance: str = "demo_fixture"


_DEMO_DATE = date(2026, 11, 9)
_DOCS = (
    KnowledgeDocument(
        "demo-retail-cart", Role.RETAIL, "Учебная корзина",
        "ДЕМО: выберите учебный товар в каталоге, добавьте его в корзину "
        "и подтвердите действие. Реальный заказ не создаётся.",
        "demo-1", _DEMO_DATE, ("корзин", "товар", "покуп"),
    ),
    KnowledgeDocument(
        "demo-retail-booking", Role.RETAIL, "Учебная бронь",
        "ДЕМО: выберите свободное учебное время и подтвердите бронь. "
        "Это не запись в отделение Сбера.",
        "demo-1", _DEMO_DATE, ("брон", "запис", "встреч"),
    ),
    KnowledgeDocument(
        "demo-business-competitors", Role.BUSINESS, "Учебные конкуренты",
        "ДЕМО: сравнивайте цену и маржу с вымышленными конкурентами; "
        "сначала проверьте реальность и актуальность рыночных данных.",
        "demo-1", _DEMO_DATE, ("конкурент", "рынок", "цен"),
    ),
    KnowledgeDocument(
        "demo-business-ads", Role.BUSINESS, "Учебная реклама",
        "ДЕМО: оцените расходы, показы, клики и заказы. Публикация "
        "рекламы возможна только после подтверждения учебного черновика.",
        "demo-1", _DEMO_DATE, ("реклам", "кампан", "клик", "показ"),
    ),
    KnowledgeDocument(
        "demo-business-onboarding", Role.BUSINESS, "Учебный переход к бизнес-каналу",
        "ДЕМО: после перехода из клиентской роли откройте бизнес-канал, "
        "выберите учебную задачу оформления расчётного счёта и уточните "
        "необходимый следующий шаг. Переход передаёт только тип задачи, "
        "а не данные счёта или историю клиента. Реальная заявка не создаётся.",
        "demo-1", _DEMO_DATE,
        ("расчётного счёта", "оформлен", "бизнес-канал", "переход"),
    ),
    KnowledgeDocument(
        "demo-employee-vacation", Role.EMPLOYEE, "Учебный отпуск",
        "ДЕМО: учебный порядок — найдите график отпусков, согласуйте даты "
        "с руководителем и подайте заявку в учебной HR-системе. Это не "
        "внутренний регламент Сбера.",
        "demo-1", _DEMO_DATE, ("отпуск", "отсутств"),
    ),
    KnowledgeDocument(
        "demo-employee-learning", Role.EMPLOYEE, "Учебное обучение",
        "ДЕМО: откройте учебный каталог обучения, выберите курс и отправьте "
        "учебную заявку руководителю. Это учебная инструкция, не внутренний "
        "регламент Сбера.",
        "demo-1", _DEMO_DATE, ("обуч", "курс", "развит"),
    ),
    KnowledgeDocument(
        "demo-employee-it", Role.EMPLOYEE, "Учебный ИТ-доступ",
        "ДЕМО: при проблеме с ИТ-доступом создайте учебное обращение "
        "и укажите систему и симптом. Пароли и коды не передавайте ассистенту.",
        "demo-1", _DEMO_DATE, ("доступ", "парол", "vpn", "ит-"),
    ),
    KnowledgeDocument(
        "demo-employee-expenses", Role.EMPLOYEE, "Учебные расходы",
        "ДЕМО: для вопроса о компенсации расходов создайте учебное "
        "обращение и приложите только разрешённые документы. Это не политика Сбера.",
        "demo-1", _DEMO_DATE, ("расход", "компенсац", "аванс"),
    ),
    KnowledgeDocument(
        "demo-employee-tasks", Role.EMPLOYEE, "Учебные задачи",
        "ДЕМО: задачи и сводка выполнения берутся из учебного реестра. "
        "Назначение задачи требует подтверждения и не меняет системы Сбера.",
        "demo-1", _DEMO_DATE, ("задач", "поручен", "результат", "kpi"),
    ),
    KnowledgeDocument(
        "demo-employee-gifts", Role.EMPLOYEE, "Подарок от поставщика: учебный кейс",
        "ДЕМО учебного банка: если поставщик предлагает подарок, не принимайте "
        "решение автоматически. Зафиксируйте обстоятельства в учебном "
        "обращении к комплаенс-специалисту и дождитесь его решения. "
        "Это не является внутренним регламентом Сбера. Структура кейса "
        "вдохновлена публичным Кодексом этики Сбера и открытой политикой "
        "Банка Англии; пороги стоимости и правила Банка Англии сюда не перенесены.",
        "demo-1", _DEMO_DATE,
        ("подар", "поставщик", "конфликт интерес", "комплаенс"),
    ),
)


class DemoKnowledgeBase:
    """Малый точный поиск по ключевым темам и метаданным источника."""

    def __init__(self, documents: tuple[KnowledgeDocument, ...] = _DOCS):
        self._documents = documents

    def search(
        self, role: Role, query: str, *, today: date | None = None, k: int = 3
    ) -> list[KnowledgeDocument]:
        today = today or date.today()
        lowered = query.lower()
        scored: list[tuple[int, KnowledgeDocument]] = []
        for doc in self._documents:
            if doc.role is not role or doc.effective_from > today:
                continue
            score = sum(keyword in lowered for keyword in doc.keywords)
            if score:
                scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].source_id))
        return [doc for _, doc in scored[:k]]
