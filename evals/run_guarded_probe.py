"""Малый онлайн-прогон реального GigaChat внутри защитного графа.

Только синтетические запросы. Выходы требуют ручной экспертной оценки и сами
по себе не являются доказательством безопасности или пользы в работе.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from assistant.chat_graph import build_chat_graph
from assistant.consent import ConsentScope, ConsentService
from assistant.demo_tools import DemoToolBroker
from assistant.domain import Role, SubjectIdentity
from assistant.gigachat import GigaChatLangChainClient
from assistant.role_context import RoleContextManager


CASES = (
    ("retail_booking", Role.RETAIL, "Как записаться на учебную встречу?"),
    ("retail_cart", Role.RETAIL, "Как добавить учебные наушники в корзину?"),
    ("business_ad", Role.BUSINESS, "Как проверить учебную рекламную кампанию перед запуском?"),
    ("business_price", Role.BUSINESS, "Продажи упали. Стоит ли снижать цену и увеличить рекламу?"),
    ("employee_learning", Role.EMPLOYEE, "Как подать учебную заявку на обучение?"),
    ("employee_gift", Role.EMPLOYEE, "Поставщик предложил мне подарок. Как поступить в учебном кейсе?"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="GigaChat-3-Pro")
    parser.add_argument("--output", type=Path, default=Path("evals/results/guarded-probe.jsonl"))
    args = parser.parse_args()

    from langchain_gigachat import GigaChat
    import os

    credentials = os.environ["GIGACHAT_CREDENTIALS"]
    options = {
        "credentials": credentials,
        "scope": os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
        "model": args.model,
        "ca_bundle_file": os.getenv("GIGACHAT_CA_BUNDLE"),
        "verify_ssl_certs": True,
        "max_retries": 0,
    }
    model = GigaChatLangChainClient(GigaChat(**options), GigaChat(**options))
    broker = DemoToolBroker()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for index, (case_id, role, query) in enumerate(CASES):
            manager = RoleContextManager(
                SubjectIdentity(f"synthetic-probe-{index}"), ConsentService()
            )
            manager.grant_consent(role, ConsentScope.LLM_PROCESSING, "simulation")
            manager.switch_role(role, "simulation")
            start = time.monotonic()
            row = {"id": case_id, "role": role.value, "query": query, "model": args.model}
            try:
                result = build_chat_graph(manager, model, broker).invoke({
                    "query": query, "cross_role_opt_in": False,
                })
                row.update(
                    decision=result["decision"], answer=result["answer"],
                    sources=result.get("sources", []),
                    tokens_used=result.get("tokens_used", 0),
                )
            except Exception as exc:
                row.update(error=type(exc).__name__)
            row["latency_sec"] = round(time.monotonic() - start, 2)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{case_id}: {row.get('decision', row.get('error'))} ({row['latency_sec']} s)")
    print(f"Результаты: {args.output}")


if __name__ == "__main__":
    main()
