# Схема потоков данных с учётом согласий

## 1. Поток «Первый вход + выдача согласий» (onboarding)

```mermaid
sequenceDiagram
    autonumber
    actor U as Физлицо (3 роли)
    participant GW as API-шлюз
    participant RC as RoleService
    participant CS as ConsentService
    participant KMS as KMS / HSM
    participant PG as PostgreSQL<br/>(consent_journal WORM)

    U->>GW: Вход через SberID
    GW->>RC: authenticate(sber_id, ip, device_fp)
    RC->>KMS: derive subject_hash[retail, biz, emp]
    KMS-->>RC: 3 разных HMAC-хэша (несвязываемых)
    RC->>CS: getConsents(multirole) ?
    CS->>PG: SELECT consent_journal WHERE status=active
    alt согласий нет
        CS-->>U: Экран согласий (по роли):<br/>retail: «обработка переписки…»<br/>biz: «аналитика по оборотам…»<br/>emp: «Вопросы по career/HR…»
        U->>CS: accept(scope=v3, doc_hash=…)
        CS->>PG: INSERT (immutable, NOT update):<br/>{act_granted=True, md5(doc), ts, ip, ua, channel}
    end
    CS-->>RC: available_roles = {retail, biz?, emp?}
    Note over U,CS: Без активного согласия роль вообще не создаётся —<br/>не «скрытая», а отсутствие записи о хэше
```

## 2. Поток «Обычный диалог внутри одной роли»

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant GW as API-шлюз
    participant RC as RoleService
    participant CH as DialogService
    participant GC as GigaChat API<br/>(приватный контур)
    participant PG as PostgreSQL+pgvector<br/>retail_ns|biz_ns|emp_ns
    participant RD as Redis

    U->>GW: POST /v1/chat {message}
    GW->>RC: validate token → active_role=retail
    RC->>RD: check TTL session_retail:<hash>?
    RD-->>RC: exists, TTL 15 мин
    RC->>RC: check_consent(role=retail, scope=«LLM-обработка переписки»)
    alt consent=revoked
        RC-->>U: 403 «Роль приостановлена, продлите согласие»
    else consent=active
        RC-->>CH: allow, env={subject_hash, role, ns=retail}
        CH->>GC: POST /chat/completions{system_prompt(role), message}
        GC-->>CH: tokens + замысел tool_use.run()
        CH->>PG: vector similarity search (на retail_ns, RLS роль=retail)
        CH->>RD: push история: session_retail:{hash} (TTL 15 мин)
        CH-->>U: Ответ
    end
```

## 3. Поток «Переключение роли» (самый критичный)

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant GW as API-шлюз
    participant RC as RoleService
    participant RD as Redis
    participant CH as DialogService
    participant PG as PostgreSQL

    U->>GW: POST /v1/role/switch {target=biz}
    GW->>RC: switch_role(current=retail, target=biz)
    RC->>RC: check_consent(biz) — есть ли документ?
    RC->>RD: FLUSH session_retail:{hash_rp}<br/>(НЕ переиспользуем сессию!)
    RC->>PG: SELECT NOT EXISTS сквозного профиля для hash_biz
    RC-->>CH: new_session(env={subject_hash=hash_biz, role=biz, ns=biz_ns})
    CH->>CH: init system_prompt(biz-спецпромпт)
    RC-->>U: session_new + контекст «с нуля»<br/>(о предыдущей роли только visible meta-tag,<br/>без содержимого переписки)
```

**Ключевое правило:** переключение роли = открытие **нового** диалога. Прошлый контекст недоступен напрямую; пользователь должен явно попросить «учти мой клиентский контекст».

## 4. Поток «Сквозной контекст через согласие» (opt-in cross-retrieval)

```mermaid
sequenceDiagram
    autonumber
    actor U as Предприниматель
    participant RC as RoleService
    participant CH as DialogService
    participant PG as PostgreSQL (обе схемы)
    participant AUD as AuditService

    U->>RC: «Проанализируй мой клиентский оборот как клиентское поведение»
    RC->>RC: Требуется cross-role_access : need consent(retail) AND consent(biz) AND явный opt-in текущего запроса
    alt opt-in дан
        RC->>AUD: log(cross_retrieval, from=biz, to=retail, ts, purpose_text)
        CH->>PG: query retail_ns (READ-ONLY роль, специализ-scoped индекс)
        CH->>CH: Обезличивание: strip кластеры, ёмкости, названия торговых точек<br/>(только числовые паттерны)
        CH->>CH: Синтез ответа для biz-роли
        CH-->>U: Ответ
    else opt-in не дан
        RC-->>U: «Кросс-анализ требует вашего явного согласия на связывание ролей. Показать экран?»
    end
```

## 5. Поток «Отзыв согласия» (уничтожение контекста)

```mermaid
sequenceDiagram
    autonumber
    actor U as Пользователь
    participant CS as ConsentService
    participant K as Kafka: consent.revoked
    participant RC as RoleService
    participant PG as PostgreSQL
    participant S3 as S3-архив

    U->>CS: POST /v1/consents/{id}/withdraw
    CS->>CS: state=revoked, невосстановимо для этой версии (ver=v3)
    CS->>PG: INSERT журнал о факте отзыва, подписанный KMS
    CS-->>K: publish consent.revoked {role, scope, subject_hash}
    K-->>RC: listener: инвалидирует все Redis-сессии этой роли
    RC->>PG: DELETE FROM retail_ns.chunks WHERE subject_hash=?<br/> AND retention_expired — физ. удаление за 24 ч
    RC-->>S3: delete_marker для неистёкших объектов (soft-delete 30 дней по закону)
    Note over U,PG: Пересогласование создаёт НОВУЮ версию vN+1,<br/>старые embeddings уже уничтожены и не восстанавливаются
```

## 6. Сводная таблица потоков → обязательств

| Поток | 152-ФЗ | Банковская тайна (ст.26 ФЗ-395-1) | ТК РФ (гл.14) | Механизм в архитектуре |
|---|---|---|---|---|
| 1 — Онбординг | ч.1 ст.9 (согласие до обработки) | — | ст.86–90 | ConsentService с WORM-журналом, версии документов |
| 2 — Диалог | ст.10.1 (обезлич. для автоматизации) | п.3 (кто имеет доступ) | ст.88 (доступ ограничен) | RLS по схемам, изоляция pgvector |
| 3 — Смена роли | ст.18.5 (персонализация по согласию) | — | — | Новая сессия, отсутствие сквозного ID |
| 4 — Cross-retrieve | ч.2 ст.9 (конкретные цели) | тайна операций (ст.26 п.1) | — | Двойное согласие + opt-in + обезличивание |
| 5 — Отзыв | ч.2 ст.9 (право отзыва) | — | ст.89 (право на сохранение в порядке) | Асинхронное уничтожение ≤24 ч, асимметричное удаление |
