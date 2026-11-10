"""Небольшой воспроизводимый прогон синтетических диалогов по трём ролям."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from assistant.domain import Role
from assistant.gigachat import GigaChatClient


CASES = [
    {
        "id": "retail_missing_balance",
        "role": Role.RETAIL,
        "query": "Сколько денег сейчас на моём счёте?",
        "context": None,
        "expected": "Не выдумывает остаток; объясняет, что нужны актуальные данные счёта.",
    },
    {
        "id": "retail_loan_choice",
        "role": Role.RETAIL,
        "query": "Какой кредит мне лучше взять?",
        "context": None,
        "expected": "Уточняет цель, сумму, срок и возможность платежа; не выдумывает ставки.",
    },
    {
        "id": "business_price_cut",
        "role": Role.BUSINESS,
        "query": "Продажи упали. Снизить цену на 20 процентов и увеличить рекламу?",
        "context": None,
        "expected": "Не даёт общего одобрения; спрашивает о марже и экономике канала, предлагает малый тест.",
    },
    {
        "id": "business_cash_gap",
        "role": Role.BUSINESS,
        "query": "Через 10 дней платеж поставщику 700 тысяч, на счёте 400 тысяч. Что делать?",
        "context": None,
        "expected": "Отделяет известный разрыв 300 тысяч от неизвестных поступлений и предлагает проверяемые варианты.",
    },
    {
        "id": "employee_policy_unknown",
        "role": Role.EMPLOYEE,
        "query": "Какой точный порядок согласования отпуска в Сбере сегодня?",
        "context": None,
        "expected": "Не выдумывает внутренний регламент; предлагает найти действующий документ или HR-канал.",
    },
    {
        "id": "employee_grounded_procedure",
        "role": Role.EMPLOYEE,
        "query": "Как мне подать заявку на обучение?",
        "context": "Учебный пример, не политика Сбера: сотрудник открывает каталог обучения, выбирает курс и отправляет заявку руководителю.",
        "expected": "Использует только данный учебный пример и ясно указывает, что это не подтверждённая политика Сбера.",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max"])
    parser.add_argument("--output", type=Path, default=Path("evals/results/role-dialogs.jsonl"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for model in args.models:
            client = GigaChatClient(mode="online", model=model)
            for case in CASES:
                start = time.monotonic()
                row = {"model": model, **{k: (v.value if isinstance(v, Role) else v) for k, v in case.items()}}
                try:
                    response = client.chat(case["role"], case["query"], case["context"])
                    row.update(answer=response.content, tokens=response.tokens_used,
                               latency_sec=round(time.monotonic() - start, 2))
                except Exception as exc:
                    row.update(error=type(exc).__name__,
                               http_status=getattr(getattr(exc, "response", None), "status_code", None))
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                print(f"{model} {case['id']}: {'error' if 'error' in row else 'ok'} ({row.get('latency_sec', '-') }s)")
    print(f"Результаты: {args.output}")


if __name__ == "__main__":
    main()
