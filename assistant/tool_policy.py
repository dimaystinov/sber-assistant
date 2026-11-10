"""Инструменты не вызываются без явного разрешения приложения."""
from __future__ import annotations

from collections.abc import Mapping

from .domain import Role


READ_ONLY_TOOLS: dict[str, frozenset[Role]] = {
    "read_verified_document": frozenset(Role),
    "read_account_balance": frozenset({Role.RETAIL}),
}


def authorize_tool(name: str, role: Role, grants: Mapping[str, bool]) -> bool:
    """Запрет по умолчанию; модель пока не получает инструменты."""
    return (
        role in READ_ONLY_TOOLS.get(name, frozenset())
        and grants.get(name) is True
    )
