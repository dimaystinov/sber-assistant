"""Хранение контекста: Redis-сессии + pgvector retrieval (namespace-per-role).

Прототип работает на встроенных in-memory реализациях (без внешних сервисов),
но повторяет контракт боевых хранилищ: Redis (сессии, TTL) и PostgreSQL/pgvector
(семантический контекст по схемам retail_ns / biz_ns / emp_ns с RLS).
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from .domain import NAMESPACES, Role, SESSION_TTL_SECONDS


@dataclass
class Session:
    session_id: str
    role: Role
    subject_hash: str
    namespace: str
    created_at: float
    expires_at: float
    history: list[dict] = field(default_factory=list)

    @property
    def is_alive(self) -> bool:
        return time.time() < self.expires_at


class RedisSessionStore:
    """Замена боевого Redis Cluster так же по контракту: ключи с TTL.

    Ключ: session:{role}:{subject_hash} — при смене роли ключ другой,
    сессия создаётся заново (см. data_flows.md §3).
    """

    def __init__(self) -> None:
        self._data: dict[str, Session] = {}
        self._ttl: dict[str, float] = {}
        # Подписчики на инвалидации (consent.revoked)
        self._revoked_subs: list = []

    def _key(self, role: Role, subject_hash: str) -> str:
        return f"session:{role.value}:{subject_hash}"

    def get_alive(self, role: Role, subject_hash: str) -> Session | None:
        key = self._key(role, subject_hash)
        session = self._data.get(key)
        if session is None or not session.is_alive:
            self._data.pop(key, None)
            self._ttl.pop(key, None)
            return None
        return session

    def create(self, role: Role, subject_hash: str) -> Session:
        key = self._key(role, subject_hash)
        # Правило: одна живая сессия на (роль, субъект). Всё остальное — устаревший хвост.
        self._data.pop(key, None)
        now = time.time()
        session = Session(
            session_id=f"sess-{secrets.token_hex(10)}",
            role=role,
            subject_hash=subject_hash,
            namespace=NAMESPACES[role],
            created_at=now,
            expires_at=now + SESSION_TTL_SECONDS,
        )
        self._data[key] = session
        self._ttl[key] = SESSION_TTL_SECONDS
        return session

    def drop(self, role: Role, subject_hash: str) -> None:
        key = self._key(role, subject_hash)
        self._data.pop(key, None)
        self._ttl.pop(key, None)

    def drop_all_for(self, subject_hash: str, role: Role | None = None) -> int:
        """Инвалидация по факту отзыва согласия (Kafka consent.revoked)."""
        dropped = 0
        for key in list(self._data):
            sess = self._data[key]
            if sess.subject_hash == subject_hash and (role is None or sess.role is role):
                self._data.pop(key, None)
                self._ttl.pop(key, None)
                dropped += 1
        return dropped

    def add_message(self, session: Session, speaker: str, text: str) -> None:
        session.history.append({"speaker": speaker, "text": text})

    def ttl_of(self, role: Role, subject_hash: str) -> int:
        key = self._key(role, subject_hash)
        return int(self._ttl.get(key, 0))


class VectorStore:
    """Псевдо-реализация pgvector-поиска по namespace.

    Боевой аналог: таблицы <namespace>.chunks, колонка embedding
    vector(1024) с индексом HNSW, политика RLS по subject_hash и
    привилегии на схему у отдельной сервисной роли СУБД. JOIN между
    схемами запрещён правами, а не кодом.
    """

    def __init__(self) -> None:
        self._docs: dict[str, list[dict]] = {ns: [] for ns in NAMESPACES.values()}

    def upsert(self, role: Role, subject_hash: str, text: str, meta: dict | None = None) -> str:
        doc_id = f"doc-{secrets.token_hex(6)}"
        self._docs[NAMESPACES[role]].append(
            {"id": doc_id, "subject_hash": subject_hash, "text": text,
             "meta": meta or {}, "ts": time.time()}
        )
        return doc_id

    def delete_subject(self, role: Role, subject_hash: str) -> int:
        """Физ. удаление по отзыву согласия (SLA ≤24 ч)."""
        ns = NAMESPACES[role]
        before = len(self._docs[ns])
        self._docs[ns] = [d for d in self._docs[ns] if d["subject_hash"] != subject_hash]
        return before - len(self._docs[ns])

    def retrieve(self, role: Role, subject_hash: str, query: str, k: int = 3) -> list[dict]:
        """Доступ ТОЛЬКО к namespace активной роли и только своим данным.

        В проде запрос идёт через connection, у которого SET ROLE
        assistant_<role> с RLS-политикой subject_hash = current_setting('app.subj').
        """
        ns = NAMESPACES[role]
        scored: list[tuple[float, dict]] = []
        q = set(query.lower().split())
        for doc in self._docs[ns]:
            if doc["subject_hash"] != subject_hash:
                continue  # чужие данные не видимы даже в своём namespace
            words = set(doc["text"].lower().split())
            overlap = len(q & words) / (len(q) or 1)
            if overlap > 0:
                scored.append((overlap, doc))
        scored.sort(key=lambda p: -p[0])
        return [doc for _, doc in scored[:k]]
