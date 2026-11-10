"""Инварианты воспроизводимой симуляции трёх ролевых контуров."""

from evals.simulate_deployment import run_large_simulation, run_simulation


def test_simulation_runs_all_roles_and_safety_cases() -> None:
    report = run_simulation(repetitions=2, seed=7)

    assert report["seed"] == 7
    assert report["repetitions"] == 2
    assert report["episodes"] == 44
    assert report["scenario_types"] == 22
    assert report["failures"] == []
    assert set(report["by_role"]) == {"retail", "business", "employee"}
    assert report["by_family"]["action"]["passed"] == 10
    assert report["by_family"]["attack"]["passed"] == 12


def test_simulation_is_reproducible() -> None:
    first = run_simulation(repetitions=1, seed=19)
    second = run_simulation(repetitions=1, seed=19)
    assert first["cases"] == second["cases"]


def test_large_simulation_has_distinct_episodes_per_role() -> None:
    report = run_large_simulation(per_role=13, seed=31)

    assert report["episodes"] == 39
    assert {role: row["total"] for role, row in report["by_role"].items()} == {
        "retail": 13, "business": 13, "employee": 13,
    }
    assert len({row["input_key"] for row in report["cases"]}) == 39
    assert report["failures"] == []


def test_large_simulation_can_run_with_mcp_broker() -> None:
    report = run_large_simulation(per_role=8, seed=31, mcp=True)
    assert report["harness"] == "in_process_mcp"
    assert report["episodes"] == 24
    assert report["failures"] == []
