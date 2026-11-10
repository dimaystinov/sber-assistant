# Учебная симуляция сервисов Сбера через MCP

**Дата исследования:** 10 ноября 2026 года. Проект не вызывает промышленный или тестовый контур Сбера. Ниже — локальные MCP-двойники на вымышленных данных; их ответы и упрощённые схемы **не совместимы один к одному** с контрактами Sber API.

## Что подтверждено официальной документацией

[Sber API](https://developers.sber.ru/docs/ru/sber-api/start/overview) разделяет доступные операции по наборам и закрепляет их в договоре. В [песочнице](https://developers.sber.ru/docs/ru/sber-api/start/sandbox) реальные данные не затрагиваются; она предназначена для функционального тестирования, **не для нагрузки**. Для подключения нужны настройки в кабинете, TLS-сертификат и access token. Публичный [каталог MCP](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-payment) показывает пять сервисов:

| Официальный MCP-сервис | Документированный scope | Что симулируется локально |
|---|---|---|
| [Информация о клиенте](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-client-info) | `MCP_COMMON`, `MCP_CLIENT_INFO` | `accounts.get_list`, `client_info.get_requisites`, `client_info.get_card_index` |
| [Выписка](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-statement) | `MCP_COMMON`, `MCP_STATEMENT` | `statement.get_summary`, `statement.get_rur_transactions`, `statement.get_rur_increment` |
| [Рублёвый платёж](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-payment) | `MCP_COMMON`, `MCP_PAYMENT` | `correspondent_rur.get`, `rur_payment.get_state`, `rur_payment.get_credit_info`, создание **только учебного черновика** `rur_payment.create_invoice` после подтверждения |
| [Инкассация](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-encashment) | `MCP_COMMON`, `MCP_ENCASHMENT` | `encashment.get_contracts_list`, `encashment.get_objects_list_by_contract` |
| [Депозиты и НСО](https://developers.sber.ru/docs/ru/sber-api/mcp/mcp-placement) | `MCP_COMMON`, `MCP_COMMERCIAL_OFFERS` | `deposit.get_commercial_offers`, `minimum_balance.get_commercial_offers` |

Официальная инструкция по платежному MCP различает **черновик** и **исполненный платёж**: созданный без подписи документ остаётся черновиком и требует подписания в СберБизнес. Поэтому локальный `create_invoice` возвращает `CREATED`, `signed=false`, `executed=false`; инструмент не доступен из общего endpoint чтения. Подтверждение в нашем интерфейсе разрешает лишь создание учебного черновика и **не имитирует электронную подпись**. Реальный `externalId` должен быть уникальным UUID; в симуляции используется явно маркированный `demo-*`, чтобы не спутать его с банковским документом. Реальная схема платежа содержит больше обязательных реквизитов и КЭП, чем учебная форма.

## Дополнительные, вымышленные MCP-адаптеры

Открытая [страница API SberCRM](https://sbercrm.com/api) подтверждает возможность интеграции по запросу, но не раскрывает использованные здесь имена MCP-tools. Внутренних HR, ИТ и регламентных API Сбера у проекта нет. Поэтому следующие инструменты являются **нашими контрактами симуляции**, не сервисами банка:

| Двойник | Роль | Учебные инструменты |
|---|---|---|
| `identity` | Любая активная роль | `identity.me`: показывает только демо-идентичность и активную роль |
| `crm` | Предприниматель | `crm.leads.get`, `crm.opportunities.get` |
| `hr` | Сотрудник | `hr.leave_balance.get`, `hr.training_catalog.get` |
| `it` | Сотрудник | `it.tickets.get` |
| `policy` | Сотрудник | `policy.search`: учебный документ с `approved=false`; не действующий регламент Сбера |

## Контур исполнения и проверки

`/v1/demo/sber-mcp/call` допускает только read-only имена из серверного allowlist. Gateway проверяет активную роль, согласие, назначенный scope, владельца счёта/договора и схему ответа **до выдачи данных**. При неизвестном инструменте, чужом счёте или недостаточном scope возвращается отказ. Текст модели не может расширить scope. Платёжный маршрут отдельный: `/v1/demo/sber-mcp/payments/prepare` создаёт черновик подтверждения с точным payload, `/confirm` проверяет субъект, сессию, одноразовый токен и время действия; только после этого вызывается локальный MCP `rur_payment.create_invoice`. Повторное подтверждение запрещено. Не происходит списания денег и подключения к СберБизнес.

В [симуляторе](../evals/simulate_service_matrix.py) каждый эпизод получает отдельного учебного субъекта и состояние. Положительные случаи проверяют ответ каждого сервиса; отрицательные — чужую роль, отсутствие scope, чужой счёт, отрицательную сумму, неверный токен, повторный вызов и отзыв согласия. Результат сохраняется в [`service-matrix.json`](../evals/results/service-matrix.json). Проверки не охватывают все банковские состояния, временные гонки, весь состав обязательных полей официального API и реальные отказы сети. Утверждение «без ошибок» из них не следует.

## Воспроизведение

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m evals.simulate_service_matrix --per-role 1200 --seed 20261110 --output evals/results/service-matrix.json
```

Для следующего этапа нужен авторизованный доступ к **официальной песочнице Sber API** и тесты по опубликованным схемам каждого метода. Параметры подключения пользователь не предоставлял, поэтому запросов к `fintech-test.sberbank.ru` не выполнялось. Даже после проверки в песочнице нагрузку следует тестировать на собственных двойниках, поскольку публичная документация прямо исключает нагрузочное тестирование банковской песочницы.
