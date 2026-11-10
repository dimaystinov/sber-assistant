"""RoleContextManager — управление сменой ролей с изоляцией контекста и согласий."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .consent import ConsentService, ConsentScope, CONSENT_DOCS
from .context_store import RedisSessionStore, Session, VectorStore
from .domain import (
    NAMESPACES,
    REVOKED_DELETION_SLA_SECONDS,
    ConsentAction,
    ConsentRecord,
    Role,
    SubjectIdentity,
    utcnow,
)


@dataclass(frozen=True)
class RoleSwitchDenied(Exception):
    """Отказ в переключении роли (исключение + машина причин)."""

    reason: str
    required_scope: ConsentScope | None = None
    doc_version_required: int | None = None

    def __post_init__(self) -> None:
        super().__init__(self.reason)


@dataclass
class RoleContext:
    """Результат успешного переключения роли / продолжает активную сессию."""

    session: Session
    switched_now: bool
    available_scopes: tuple[ConsentScope, ...]


class RoleContextManager:
    """Контракт уровня сервиса (FastAPI FastAPI DI):

    - __init__ принимает identity — обезличенный субъект (SubjectIdentity),
      ConsentService (журнал WORM), RedisSessionStore, VectorStore;
    - switch_role() ЗАПРЕЩАЕТ переход без активного согласия LLM-обработки
      и всегда открывает НОВУЮ сессию в другом namespace;
    - get_context() возвращает контекст ИЗ ОДНОГО namespace (плюс обезличенные
      «мостики» из других ролей только при двойном согласии cross_retrieval);
    - check_consent() — первичная проверка до любого обращения к LLM/БД.
    """

    def __init__(
        self,
        identity: SubjectIdentity,
        consent_service: ConsentService,
        redis_store: RedisSessionStore | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._identity = identity
        self._consents = consent_service
        self._redis = redis_store or RedisSessionStore()
        self._vectors = vector_store or VectorStore()
        self._active_role: Role | None = None
        # Подписка на отзыв (Kafka consent.revoked в проде)
        self._consents.journal.subscribe(self._on_consent_event)

    # ---------- публичный API ----------

    @property
    def active_role(self) -> Role | None:
        return self._active_role

    def check_consent(
        self, role: Role, scope: ConsentScope = ConsentScope.LLM_PROCESSING
    ) -> bool:
        return self._consents.check_consent(
            self._identity.subject_hash(role), role, scope
        )

    def switch_role(
        self, target: Role, channel: str = "unknown", ip_hint: str | None = None
    ) -> RoleContext:
        """Переключение роли одного физлица: клиент → предприниматель → сотрудник.

        Гарантии:
        1. Нет согласия LLM-обработки в новой роли → отказ (RoleSwitchDenied);
        2. Текущая сессия уничтожается (не переиспользуется, не «тянется» в другую роль);
        3. Новая сессия живёт в namespace целевой роли — по ключу subject_hash(target);
        4. Факт переключения фиксируется в audit-канале.
        """
        if target is self._active_role and self._current_is_alive():
            # Смена на ту же роль — не новые согласия, продолжаем сессию
            return self._context_of(self._current_session(), switched_now=False)

        required = ConsentScope.LLM_PROCESSING
        if not self.check_consent(target, required):
            if not self._identity_has_subject(target):
                raise RoleSwitchDenied(
                    reason=f"Субъект в роли {target.value} отсутствует — сначала onboarding",
                    required_scope=required,
                    doc_version_required=self._doc_version(required),
                )
            raise RoleSwitchDenied(
                reason=f"Согласие {required.value} для роли {target.value} не активно",
                required_scope=required,
                doc_version_required=self._doc_version(required),
            )

        if self._active_role is not None:
            self._redis.drop(self._active_role, self._current_hash(self._active_role))

        session = self._redis.create(target, self._current_hash(target))
        self._active_role = target
        self._audit("role_switch", role=target, channel=channel, ip_hint=ip_hint,
                    detail={"session": session.session_id})
        return self._context_of(session, switched_now=True)

    def get_context(self, query: str, k: int = 3,
                    cross_role_opt_in: bool = False) -> dict:
        """Возврат контекста ТОЛЬКО активной роли.

        При активном двойном согласии cross_retrieval и ОБЕИХ активных ролях
        (retail+business) может примешать ОБЕЗЛИЧЕННЫЕ факты из второй роли —
        только факты/числа, без текстов переписки и без PII.
        """
        if self._active_role is None:
            raise PermissionError("Активная роль не выбрана — сначала switch_role()")
        session = self._current_session()
        own = self._vectors.retrieve(self._active_role, session.subject_hash, query, k=k)
        cross: list[dict] = []
        if (
            cross_role_opt_in
            and
            self._active_role in (Role.RETAIL, Role.BUSINESS)
            and self.check_consent(self._active_role, ConsentScope.CROSS_RETRIEVAL_RETAIL)
            and (
                other := Role.BUSINESS if self._active_role is Role.RETAIL else Role.RETAIL
            )
            and other not in [self._active_role]
            and self.check_consent(other, ConsentScope.LLM_PROCESSING)
            and self.check_consent(other, ConsentScope.CROSS_RETRIEVAL_RETAIL)
        ):
            cross = self._retrieve_cross(other, query, k=1)
        return {
            "role": self._active_role.value,
            "namespace": session.namespace,
            "session_id": session.session_id,
            "own_context": [{"id": d["id"], "text": d["text"]} for d in own],
            "cross_context_anonymized": [
                {"summary": d["text"]} for d in cross
            ],  # обезличено, только суть
        }

    def remember(self, text: str, meta: Mapping | None = None) -> str:
        if self._active_role is None:
            raise PermissionError("Нет активной роли")
        session = self._current_session()
        self._redis.add_message(session, "user", text)
        return self._vectors.upsert(
            self._active_role, session.subject_hash, text, dict(meta or {})
        )

    def grant_consent(self, role: Role, scope: ConsentScope, channel: str) -> str:
        record = self._consents.grant(
            self._current_hash(role), role, scope, channel=channel
        )
        self._audit("consent_granted", role=role, channel=channel)
        return record.consent_id

    def withdraw_consent(
        self, role: Role, scope: ConsentScope, channel: str,
        consent_id: str | None = None,
    ) -> None:
        if consent_id is not None:
            matching = [
                item for item in self._consents.journal.iter_all()
                if item.subject_hash == self._current_hash(role)
                and item.role is role and item.scope is scope
            ]
            if (
                not matching or matching[-1].consent_id != consent_id
                or matching[-1].action is not ConsentAction.GRANTED
            ):
                raise ValueError("Согласие с таким идентификатором не активно")
        record = self._consents.withdraw(
            self._current_hash(role), role, scope, channel=channel
        )
        # Синхронный след не нужен — ConsentJournal сам публикует событие в
        # подписчиков, включая роль RedisSessionStore и VectorStore (удаление ≤24 ч).
        self._audit("consent_withdrawn", role=role, channel=channel,
                    detail={"consent_id": record.consent_id})

    # ---------- Реакция на Kafka consent.revoked / consent.granted ----------

    def _on_consent_event(self, record: ConsentRecord) -> None:
        if record.action is ConsentAction.WITHDRAWN:
            # Инвалидация всех Redis-сессий этой роли немедленно
            self._redis.drop_all_for(record.subject_hash, record.role)
            # В проде — асинхронная очередь удалений с SLA ≤24 ч (REVOKED_DELETION_SLA)
            self._vectors.delete_subject(record.role, record.subject_hash)
            if self._active_role is record.role:
                self._active_role = None

    # ---------- служебные ----------

    def _current_hash(self, role: Role) -> str:
        return self._identity.subject_hash(role)

    def _identity_has_subject(self, role: Role) -> bool:
        # В проде: наличие строки в profiles.<role>_ns; здесь — истинно по умолчанию
        return True

    def _current_is_alive(self) -> bool:
        assert self._active_role is not None
        return (
            self._redis.get_alive(self._active_role, self._current_hash(self._active_role))
            is not None
        )

    def _current_session(self) -> Session:
        assert self._active_role is not None
        session = self._redis.get_alive(self._active_role, self._current_hash(self._active_role))
        if session is None:  # TTL истёк — переоткрытие той же роли
            session = self._redis.create(self._active_role, self._current_hash(self._active_role))
        return session

    def _context_of(self, session: Session, *, switched_now: bool) -> RoleContext:
        role = session.role
        scopes = tuple(
            scope
            for scope in CONSENT_DOCS
            if role in CONSENT_DOCS[scope].roles
            and self._consents.check_consent(session.subject_hash, role, scope)
        )
        return RoleContext(
            session=session, switched_now=switched_now, available_scopes=scopes
        )

    def _retrieve_cross(self, other_role: Role, query: str, k: int) -> list[dict]:
        # Только обезличенные факты; полное cross-чтение запрещено даже при
        # активных согласиях обеих ролей (передаются только итоги/метрики).
        raw = self._vectors.retrieve(other_role, self._current_hash(other_role), query, k=k)
        self._audit("cross_retrieval", role=self._active_role, channel="dialog",
                    detail={"other_role": other_role.value, "k": len(raw)})
        sanitized: list[dict] = []
        for d in raw:
            # Исходный текст никогда не пересекает границу роли. Публиковать
            # агрегат может только доверенный конвейер подготовки данных.
            meta = d.get("meta", {})
            if meta.get("cross_shareable_verified") is not True:
                continue
            summary = meta.get("cross_shareable_summary")
            if isinstance(summary, str) and summary.strip():
                sanitized.append({"text": summary.strip()})
        return sanitized

    @staticmethod
    def _doc_version(scope: ConsentScope) -> int | None:
        doc = CONSENT_DOCS.get(scope)
        return doc.version if doc else None

    def _audit(self, event: str, *, role: Role, channel: str,
               ip_hint: str | None = None, detail: dict | None = None) -> None:
        # Прод: Kafka → SIEM/AuditService (незаменимый журнал, retention ≥5 лет)
        _ = (event, utcnow().isoformat(), role.value, channel, ip_hint or "", detail or {})


__all__ = [
    "RoleContextManager",
    "RoleContext",
    "RoleSwitchDenied",
    "NAMESPACES",
    "REVOKED_DELETION_SLA_SECONDS",
]
