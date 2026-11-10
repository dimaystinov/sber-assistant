"""Детерминированные денежные расчёты; модель не вычисляет суммы."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, Field


class CashGapInput(BaseModel):
    """Структурированные входные данные для расчёта кассового разрыва."""

    kind: Literal["cash_gap"]
    amount_due: Decimal = Field(ge=0)
    available: Decimal = Field(ge=0)
    days_until_due: int = Field(ge=1, le=366)


def _money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, fraction = f"{rounded:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return grouped if fraction == "00" else f"{grouped},{fraction}"


def cash_gap_answer(data: CashGapInput) -> str:
    """Рассчитывает дефицит и безопасный следующий шаг без LLM."""
    gap = max(Decimal("0"), data.amount_due - data.available)
    daily = gap / Decimal(data.days_until_due)
    return (
        "По указанным структурным данным: обязательство "
        f"{_money(data.amount_due)} ₽ через {data.days_until_due} дней, "
        f"доступно {_money(data.available)} ₽. "
        f"Текущий дефицит — {_money(gap)} ₽. "
        f"Для покрытия без иных источников нужно в среднем {_money(daily)} ₽ "
        "поступлений в день. Это не прогноз: будущие поступления и другие "
        "обязательства не учтены. Следующий шаг — сверить календарь платежей "
        "и ожидаемых поступлений, затем обсудить с поставщиком допустимую "
        "отсрочку или частичную оплату. Условия финансирования проверяйте "
        "отдельно."
    )
