"""Illustrative 2027–2029 incremental economics for the championship case.

These are planning assumptions, not Sber forecasts or measured bank effects.
Only cross-role tasks incremental to existing assistants are counted.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


YEARS = (2027, 2028, 2029)
MILLION = Decimal("1000000")


@dataclass(frozen=True)
class Scenario:
    name: str
    linked_people: tuple[int, int, int]
    cross_role_tasks_per_person: tuple[int, int, int]
    avoided_contact_share: Decimal
    effective_value_per_avoided_contact_rub: Decimal
    minutes_saved_per_task: Decimal
    inference_cost_per_task_rub: Decimal
    build_mrub: tuple[Decimal, Decimal, Decimal]
    platform_ops_mrub: tuple[Decimal, Decimal, Decimal]
    governance_mrub: tuple[Decimal, Decimal, Decimal]


@dataclass(frozen=True)
class YearResult:
    year: int
    linked_people: int
    cross_role_tasks: int
    avoided_contacts: Decimal
    gross_effect_mrub: Decimal
    build_mrub: Decimal
    platform_ops_mrub: Decimal
    inference_mrub: Decimal
    governance_mrub: Decimal
    total_cost_mrub: Decimal
    net_effect_mrub: Decimal
    person_hours_saved: Decimal


def _scenario(name: str, people: tuple[int, int, int], tasks: tuple[int, int, int],
              avoidance: str, value: str, minutes: str) -> Scenario:
    return Scenario(
        name=name,
        linked_people=people,
        cross_role_tasks_per_person=tasks,
        avoided_contact_share=Decimal(avoidance),
        effective_value_per_avoided_contact_rub=Decimal(value),
        minutes_saved_per_task=Decimal(minutes),
        inference_cost_per_task_rub=Decimal("5"),
        build_mrub=(Decimal("70"), Decimal("40"), Decimal("10")),
        platform_ops_mrub=(Decimal("20"), Decimal("40"), Decimal("70")),
        governance_mrub=(Decimal("10"), Decimal("15"), Decimal("20")),
    )


SCENARIOS = {
    "low": _scenario("low", (50_000, 250_000, 600_000), (3, 4, 5),
                     "0.15", "100", "2"),
    "base": _scenario("base", (100_000, 500_000, 1_200_000), (4, 6, 8),
                      "0.25", "120", "3"),
    "high": _scenario("high", (150_000, 700_000, 1_600_000), (5, 7, 9),
                      "0.30", "150", "4"),
}


def calculate(scenario: Scenario) -> list[YearResult]:
    """Calculate incremental bank cash effect and separate human time benefit."""
    if not Decimal("0") <= scenario.avoided_contact_share <= Decimal("1"):
        raise ValueError("Avoided-contact share must be within [0, 1]")
    if any(value < 0 for value in (
        scenario.effective_value_per_avoided_contact_rub,
        scenario.minutes_saved_per_task,
        scenario.inference_cost_per_task_rub,
    )):
        raise ValueError("Unit assumptions cannot be negative")
    columns = (
        scenario.linked_people, scenario.cross_role_tasks_per_person,
        scenario.build_mrub, scenario.platform_ops_mrub, scenario.governance_mrub,
    )
    if any(len(column) != len(YEARS) for column in columns):
        raise ValueError("Each yearly input must cover 2027, 2028, and 2029")
    if any(value < 0 for column in columns for value in column):
        raise ValueError("Yearly inputs cannot be negative")

    results = []
    for index, year in enumerate(YEARS):
        people = scenario.linked_people[index]
        task_count = people * scenario.cross_role_tasks_per_person[index]
        avoided = Decimal(task_count) * scenario.avoided_contact_share
        gross = avoided * scenario.effective_value_per_avoided_contact_rub / MILLION
        inference = Decimal(task_count) * scenario.inference_cost_per_task_rub / MILLION
        build = scenario.build_mrub[index]
        platform = scenario.platform_ops_mrub[index]
        governance = scenario.governance_mrub[index]
        cost = build + platform + governance + inference
        hours = Decimal(task_count) * scenario.minutes_saved_per_task / Decimal("60")
        results.append(YearResult(
            year, people, task_count, avoided, gross, build, platform,
            inference, governance, cost, gross - cost, hours,
        ))
    return results


def to_dict(row: YearResult) -> dict[str, int | str]:
    """Preserve money precision in machine-readable results."""
    return {
        "year": row.year,
        "linked_people": row.linked_people,
        "cross_role_tasks": row.cross_role_tasks,
        "avoided_contacts": str(row.avoided_contacts),
        "gross_effect_mrub": str(row.gross_effect_mrub),
        "build_mrub": str(row.build_mrub),
        "platform_ops_mrub": str(row.platform_ops_mrub),
        "inference_mrub": str(row.inference_mrub),
        "governance_mrub": str(row.governance_mrub),
        "total_cost_mrub": str(row.total_cost_mrub),
        "net_effect_mrub": str(row.net_effect_mrub),
        "person_hours_saved": str(row.person_hours_saved),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    payload = {
        "status": "illustrative_scenarios_not_sber_forecasts",
        "baseline": "existing_role_assistants",
        "unit": "million_rub",
        "scenarios": {
            name: {
                "assumptions": {
                    "linked_people": scenario.linked_people,
                    "cross_role_tasks_per_person": scenario.cross_role_tasks_per_person,
                    "avoided_contact_share": str(scenario.avoided_contact_share),
                    "effective_value_per_avoided_contact_rub": str(
                        scenario.effective_value_per_avoided_contact_rub
                    ),
                    "minutes_saved_per_task": str(scenario.minutes_saved_per_task),
                    "inference_cost_per_task_rub": str(scenario.inference_cost_per_task_rub),
                    "build_mrub": [str(x) for x in scenario.build_mrub],
                    "platform_ops_mrub": [str(x) for x in scenario.platform_ops_mrub],
                    "governance_mrub": [str(x) for x in scenario.governance_mrub],
                },
                "years": [to_dict(row) for row in calculate(scenario)],
            }
            for name, scenario in SCENARIOS.items()
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
