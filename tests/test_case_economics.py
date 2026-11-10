"""The championship model must be reproducible and explicit about assumptions."""

from decimal import Decimal

import pytest

from evals.case_economics import SCENARIOS, calculate, to_dict


def test_base_case_yearly_and_cumulative_effect() -> None:
    rows = calculate(SCENARIOS["base"])
    assert [row.year for row in rows] == [2027, 2028, 2029]
    assert [row.gross_effect_mrub for row in rows] == [
        Decimal("12"), Decimal("90"), Decimal("288")
    ]
    assert [row.total_cost_mrub for row in rows] == [
        Decimal("102"), Decimal("110"), Decimal("148")
    ]
    assert [row.net_effect_mrub for row in rows] == [
        Decimal("-90"), Decimal("-20"), Decimal("140")
    ]
    assert sum(row.net_effect_mrub for row in rows) == Decimal("30")


def test_person_time_is_separate_from_bank_cash_effect() -> None:
    rows = calculate(SCENARIOS["base"])
    assert [row.person_hours_saved for row in rows] == [
        Decimal("20000"), Decimal("150000"), Decimal("480000")
    ]
    assert rows[0].gross_effect_mrub == Decimal("12")
    assert to_dict(rows[0])["person_hours_saved"] == "20000"
    assert to_dict(calculate(SCENARIOS["high"])[1])["person_hours_saved"] == (
        "326666.6666666666666666666667"
    )


def test_scenario_sensitivity_changes_conclusion() -> None:
    low = sum(row.net_effect_mrub for row in calculate(SCENARIOS["low"]))
    base = sum(row.net_effect_mrub for row in calculate(SCENARIOS["base"]))
    high = sum(row.net_effect_mrub for row in calculate(SCENARIOS["high"]))
    assert low < 0 < base < high


def test_invalid_share_is_rejected() -> None:
    from dataclasses import replace

    with pytest.raises(ValueError):
        calculate(replace(SCENARIOS["base"], avoided_contact_share=Decimal("1.1")))
