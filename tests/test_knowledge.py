"""Поиск только по разрешённой, актуальной базе знаний своей роли."""

from assistant.domain import Role
from assistant.knowledge import DemoKnowledgeBase


def test_employee_topics_have_cited_demo_documents() -> None:
    knowledge = DemoKnowledgeBase()
    for query in ("Как оформить отпуск?", "Нужно обучение", "Нет ИТ-доступа"):
        hits = knowledge.search(Role.EMPLOYEE, query)
        assert hits
        assert hits[0].role is Role.EMPLOYEE
        assert hits[0].source_id.startswith("demo-")
        assert hits[0].version
        assert "ДЕМО" in hits[0].text


def test_role_isolation_and_unknown_question() -> None:
    knowledge = DemoKnowledgeBase()
    assert knowledge.search(Role.RETAIL, "Как оформить отпуск?") == []
    assert knowledge.search(Role.EMPLOYEE, "квантовый ускоритель") == []


def test_business_and_retail_have_separate_knowledge() -> None:
    knowledge = DemoKnowledgeBase()
    assert knowledge.search(Role.BUSINESS, "анализ конкурентов")
    assert knowledge.search(Role.RETAIL, "добавить товар в корзину")
    assert knowledge.search(Role.RETAIL, "анализ конкурентов") == []


def test_employee_gift_case_is_explicitly_fictional() -> None:
    hit = DemoKnowledgeBase().search(Role.EMPLOYEE, "Поставщик предложил подарок")
    assert hit
    assert hit[0].source_id == "demo-employee-gifts"
    assert "учебного банка" in hit[0].text.lower()
    assert "не является внутренним регламентом Сбера" in hit[0].text
