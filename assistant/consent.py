"""ConsentService: неизменяемый журнал согласий, версии, отзыв, проверка."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import secrets

from .domain import (
    ConsentAction,
    ConsentDocument,
    ConsentRecord,
    ConsentScope,
    Role,
    utcnow,
)

# Реестр действующих юридических документов согласий.
CONSENT_DOCS: dict[ConsentScope, ConsentDocument] = {
    ConsentScope.LLM_PROCESSING: ConsentDocument(
        scope=ConsentScope.LLM_PROCESSING,
        roles=frozenset(Role),
        version=3,
        doc_sha256="a3f1…",
    ),
    ConsentScope.PROFILE_PERSONALIZATION: ConsentDocument(
        scope=ConsentScope.PROFILE_PERSONALIZATION,
        roles=frozenset(Role),
        version=2,
        doc_sha256="b7e2…",
    ),
    ConsentScope.CROSS_RETRIEVAL_RETAIL: ConsentDocument(
        scope=ConsentScope.CROSS_RETRIEVAL_RETAIL,
        roles=frozenset({Role.RETAIL, Role.BUSINESS}),
        version=1,
        doc_sha256="c9d0…",
    ),
    ConsentScope.HR_ANALYTICS: ConsentDocument(
        scope=ConsentScope.HR_ANALYTICS,
        roles=frozenset({Role.EMPLOYEE}),
        version=1,
        doc_sha256="e4f8…",
    ),
}


@dataclass
class ConsentJournal:
    """Append-only журнал согласий. UPDATE запрещён архитектурно.

    Физически журнал хранится в PostgreSQL: таблица consent_journal в отдельной
    схеме consent_journal, режим WORM, что гарантирует append-only записи и
    запрещает замену/удаление фактов.
    """

    _records: list[ConsentRecord]

    def __init__(self) -> None:
        self._records = []
        self._subscribers: list[object] = []  # Kafka listeners (RoleContextManager и др.)

    def append(self, record: ConsentRecord) -> ConsentRecord:
        self._records.append(record)  # type: ignore[arg-type]
        self._publish(record)
        return record

    def subscribe(self, callback) -> None:  # noqa: ANN001
        self._subscribers.append(callback)

    def _publish(self, record: ConsentRecord) -> None:
        # В проде: Kafka topic consent.granted / consent.revoked (см. data_flows.md §5)
        for cb in list(self._subscribers):
            cb(record)

    def active_for(self, subject_hash: str, role: Role, scope: ConsentScope) -> bool:
        """Последняя по времени запись по (hash, role, scope) должна быть granted."""
        latest: ConsentRecord | None = None
        for rec in self._records:
            if (
                rec.subject_hash == subject_hash
                and rec.role is role
                and rec.scope is scope
                and (latest is None or rec.issued_at > latest.issued_at)
            ):
                latest = rec
        return latest is not None and latest.is_active()

    def iter_all(self) -> Iterable[ConsentRecord]:
        return tuple(self._records)


class ConsentService:
    """Публичный фасад согласий для RoleService / API-шлюза."""

    def __init__(self, journal: ConsentJournal | None = None) -> None:
        self._journal = journal or ConsentJournal()

    @property
    def journal(self) -> ConsentJournal:
        return self._journal

    def grant(
        self,
        subject_hash: str,
        role: Role,
        scope: ConsentScope,
        channel: str,
        ip_hint: str | None = None,
    ) -> ConsentRecord:
        doc = self._require_doc(scope, role)
        record = ConsentRecord(
            consent_id=f"cn-{secrets.token_hex(8)}",
            subject_hash=subject_hash,
            scope=scope,
            role=role,
            action=ConsentAction.GRANTED,
            doc_version=doc.version,
            doc_sha256=doc.doc_sha256,
            issued_at=utcnow(),
            channel=channel,
            ip_hint=ip_hint,
        )
        return self._journal.append(record)

    def withdraw(
        self,
        subject_hash: str,
        role: Role,
        scope: ConsentScope,
        channel: str,
    ) -> ConsentRecord:
        if not self._journal.active_for(subject_hash, role, scope):
            raise ConsentNotFound(f"Активного согласия {scope} для {role} нет")
        doc = self._require_doc(scope, role)
        record = ConsentRecord(
            consent_id=f"cn-{secrets.token_hex(8)}",
            subject_hash=subject_hash,
            scope=scope,
            role=role,
            action=ConsentAction.WITHDRAWN,
            doc_version=doc.version,
            doc_sha256=doc.doc_sha256,
            issued_at=utcnow(),
            channel=channel,
        )
        return self._journal.append(record)

    def check_consent(self, subject_hash: str, role: Role, scope: ConsentScope) -> bool:
        return self._journal.active_for(subject_hash, role, scope)

    def available_roles(self, identity, channel_scope: set[str]) -> list[Role]:  # noqa: ANN001
        """Роли, по которым есть хотя бы обязательное согласие LLM-обработки."""
        result: list[Role] = []
        for role in Role:
            # Сотрудническая роль привязана к внутреннему каналу
            if role is Role.EMPLOYEE and "hr_portal" not in channel_scope:
                continue
            if self.check_consent(
                identity.subject_hash(role), role, ConsentScope.LLM_PROCESSING
            ):
                result.append(role)
        return result

    @staticmethod
    def _require_doc(scope: ConsentScope, role: Role) -> ConsentDocument:
        doc = CONSENT_DOCS.get(scope)
        if doc is None or role not in doc.roles:
            raise ConsentDocMiss(
                f"Нет действующего документа согласия {scope} для роли {role}"
            )
        return doc


class ConsentError(Exception):
    pass


class ConsentNotFound(ConsentError):
    pass


class ConsentDocMiss(ConsentError):
    pass
