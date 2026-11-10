"""Доменные типы: роли, согласия, анонимизированный субъект."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Final


class Role(str, Enum):
    """Три роли одного физического лица."""

    RETAIL = "retail"        # клиент СберБанка
    BUSINESS = "business"    # предприниматель (СберБизнес)
    EMPLOYEE = "employee"    # сотрудник Сбера


class ConsentScope(str, Enum):
    """Смысловые срезы согласия — не один общий флаг."""

    LLM_PROCESSING = "llm_processing"          # обработка переписки моделью
    PROFILE_PERSONALIZATION = "personalization"  # теги-профиль, рекомендации
    CROSS_RETRIEVAL_RETAIL = "cross_retrieval.retail_biz"  # связывание ролей
    HR_ANALYTICS = "hr_analytics"              # только для роли employee


class ConsentAction(str, Enum):
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


NAMESPACES: Final[dict[Role, str]] = {
    Role.RETAIL: "retail_ns",
    Role.BUSINESS: "biz_ns",
    Role.EMPLOYEE: "emp_ns",
}

SESSION_TTL_SECONDS: Final[int] = 15 * 60          # 15 минут
REVOKED_DELETION_SLA_SECONDS: Final[int] = 24 * 3600  # ≤24 ч физ. удаление


@dataclass(frozen=True)
class ConsentDocument:
    """Юридический документ-основание согласия (версионируется)."""

    scope: ConsentScope
    roles: frozenset[Role]
    version: int
    doc_sha256: str


@dataclass(frozen=True)
class ConsentRecord:
    """Неизменяемая запись журнала согласий (WORM: только INSERT, никогда UPDATE)."""

    consent_id: str
    subject_hash: str           # обезличенный hash субъекта В РАМКЕ роли
    scope: ConsentScope
    role: Role
    action: ConsentAction
    doc_version: int
    doc_sha256: str
    issued_at: datetime
    channel: str                # sberbank_online | sbi_business | hr_portal
    ip_hint: str | None = None

    def is_active(self, now: datetime | None = None) -> bool:
        return self.action is ConsentAction.GRANTED


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SubjectIdentity:
    """Обезличенный субъект без сквозного идентификатора.

    Сквозной ID намеренно отсутствует: для каждой роли выводится свой
    детерминированный HMAC-SHA256(sber_id || role_salt). Обратное
    восстановление sber_id возможно только при доступе к master_key в KMS
    (отдельный доверенный сервис, каждое использование — в аудит).
    """

    __slots__ = ("_master_key", "_sber_id", "_cache")

    def __init__(self, sber_id: str, master_key: bytes | None = None) -> None:
        # В проде master_key выдаёт KMS разово на процесс; здесь — для прототипа.
        self._master_key = master_key or secrets.token_bytes(32)
        self._sber_id = sber_id
        self._cache: dict[Role, str] = {}

    def subject_hash(self, role: Role) -> str:
        if role not in self._cache:
            salt = f"role-salt:{role.value}".encode()
            self._cache[role] = hmac.new(
                self._master_key, self._sber_id.encode() + salt, hashlib.sha256
            ).hexdigest()
        return self._cache[role]

    def hashes(self) -> dict[Role, str]:
        return {role: self.subject_hash(role) for role in Role}
