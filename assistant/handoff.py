"""Учебный одноразовый переход между клиентской и бизнес-ролью.

Передаётся только фиксированное намерение продолжить задачу. Ни память,
ни текст запроса, ни идентификаторы клиента не пересекают границу ролей.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from .consent import ConsentScope
from .domain import Role
from .role_context import RoleContextManager


class HandoffDenied(PermissionError):
    """Переход не разрешён политикой или уже недействителен."""


@dataclass(frozen=True)
class _Pending:
    source: Role
    target: Role
    intent: str
    expires_at: float


class HandoffCoordinator:
    """In-memory симуляция broker; боевой вариант требует общего защищённого store."""

    _INTENTS = frozenset({"continue_application", "open_business_channel"})
    _TTL_SECONDS = 120

    def __init__(self, manager: RoleContextManager) -> None:
        self._manager = manager
        self._pending: dict[str, _Pending] = {}

    def _allowed(self, source: Role, target: Role) -> bool:
        if source is target or {source, target} != {Role.RETAIL, Role.BUSINESS}:
            return False
        return all(
            self._manager.check_consent(role, ConsentScope.LLM_PROCESSING)
            and self._manager.check_consent(role, ConsentScope.CROSS_RETRIEVAL_RETAIL)
            for role in (source, target)
        )

    def request(self, target: Role, *, intent: str, opt_in: bool) -> str:
        source = self._manager.active_role
        if (
            source is None or intent not in self._INTENTS or not opt_in
            or not self._allowed(source, target)
        ):
            raise HandoffDenied("Переход между ролями не разрешён")
        token = secrets.token_urlsafe(24)
        self._pending[token] = _Pending(source, target, intent, time.monotonic() + self._TTL_SECONDS)
        return token

    def claim(self, token: str) -> dict[str, str]:
        pending = self._pending.get(token)
        if (
            pending is None or self._manager.active_role is not pending.target
            or time.monotonic() >= pending.expires_at
            or not self._allowed(pending.source, pending.target)
        ):
            raise HandoffDenied("Переход между ролями недействителен")
        del self._pending[token]
        return {"intent": pending.intent, "source_role": pending.source.value}
