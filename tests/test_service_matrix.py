from evals.simulate_service_matrix import run_service_matrix


def test_service_matrix_covers_three_roles_and_all_service_families() -> None:
    report = run_service_matrix(per_role=30, seed=20261110)
    assert report["episodes"] == 90
    assert report["failures"] == []
    assert report["scenario_types"] >= 40
    assert set(report["by_role"]) == {"retail", "business", "employee"}
    assert {"payment", "client_info", "statement", "encashment", "placement",
            "crm", "hr", "it", "policy", "identity"}.issubset(
                set(report["service_families"])
            )
