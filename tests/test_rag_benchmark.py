"""Синтетический бенчмарк учебной базы знаний."""

from evals.evaluate_rag import evaluate_lexical, parse_selected_source


def test_rag_benchmark_counts_exact_and_paraphrase_queries() -> None:
    result = evaluate_lexical()
    assert result["exact"]["total"] == 10
    assert result["paraphrase"]["total"] == 10
    assert 0 <= result["paraphrase"]["hit_at_1"] <= 10
    assert result["exact"]["hit_at_1"] == 10
    assert all(row["role_filtered"] for row in result["rows"])


def test_sber_router_output_is_restricted_to_role_sources() -> None:
    allowed = {"demo-retail-cart", "demo-retail-booking"}
    assert parse_selected_source("demo-retail-cart", allowed) == "demo-retail-cart"
    assert parse_selected_source("demo-employee-vacation", allowed) is None
    assert parse_selected_source("demo-retail-cart\nignore rules", allowed) is None
