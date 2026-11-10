# Инструкция для Windows: как открыть архив и запустить проект

## Путь к архиву

```
sber-assistant.zip  (~32 КБ, 17 файлов)
```

## ШАГ 1 — Скачать архив на компьютер с Windows

Кликните по файлу `sber-assistant.zip` в панели файлов (справа) → кнопка «Скачать» / Download.
Либо: правый клик → Save as. Сохраните, например, в `C:\Users\<Имя>\Downloads\`.

## ШАГ 2 — Распаковать (5 секунд)

Вариант А (стандартный Проводник):
1. Кликните правой кнопкой мыши по `sber-assistant.zip`.
2. Выберите **«Извлечь всё…» (Extract All…)**.
3. Укажите папку, например `C:\Projects\sber-assistant` → Извлечь.

Вариант Б (если стоит 7-Zip / WinRAR):
правый клик → «Извлечь в sber-assistant\».

Просмотр zip-архивов **встроен в Windows 10/11**, никаких программ докачивать не нужно — правый клик по файлу в Проводнике → «Извлечь всё».

## ШАГ 3 — Что внутри (структура)

```
sber-assistant/
├── README.md              ← обзор проекта и команды запуска
├── c4_container.md        ← ARTEFACT 1: C4-архитектура (контейнеры + ADR)
├── data_flows.md          ← ARTEFACT 2: потоки данных + согласия (5 диаграмм)
├── reg_matrix.md          ← ARTEFACT 4: матрица 152-ФЗ / банковская тайна / ТК РФ
├── requirements.txt       ← зависимости Python
├── pytest.ini             ← конфиг тестов
├── assistant/             ← ПАПКА КОДА (ARTEFACT 3)
│   ├── domain.py          ← типы: Role, ConsentScope, ConsentRecord
│   ├── consent.py         ← ConsentService + WORM-журнал
│   ├── context_store.py   ← Redis-сессии + pgvector retrieval
│   ├── role_context.py    ← ГЛАВНОЕ: RoleContextManager
│   ├── gigachat.py        ← обёртка GigaChat API
│   ├── api.py             ← FastAPI-эндпоинты
│   └── __init__.py
└── tests/
    ├── test_role_context.py ← 6 тестов
    └── demo.py              ← сквозной демо-сценарий
```

## ШАГ 4 — Запустить прототип на Windows (3 варианта)

### Вариант 1: без установки anything (смотреть результат сразу)
1. Установите Python 3.11+ с https://www.python.org/downloads/ (при установке отметьте галочку **«Add python.exe to PATH»**).
2. Откройте **Командную строку** (Win+R → cmd → Enter) или PowerShell.
3. Выполните:
```bat
cd C:\Projects\sber-assistant
python -m pip install -r requirements.txt
pytest -q
python -m tests.demo
```

`pytest -q` покажет `6 passed` — проверки изоляции работают.
`python -m tests.demo` — сквозной сценарий (онбординг → смена роли → cross-retrieval → отзыв согласия).

### Вариант 2: запустить API-сервер и открыть в браузере
```bat
cd C:\Projects\sber-assistant
python -m pip install -r requirements.txt
uvicorn assistant.api:app --reload
```
Затем в браузере откройте: http://127.0.0.1:8000/docs — откроется интерактивная Swagger-панель
со всеми эндпоинтами (chat, role/switch, consents) и кнопкой «Try it out».

### Вариант 3: ничего не запускать, только читать
Логи можно не воспроизводить — проект полностью документирован:
открыть `c4_container.md`, `data_flows.md`, `reg_matrix.md` в обычном Блокноте (Notepad,) или в VS Code.
Mermaid-диаграммы — текстовый формат; визуально их смотрят:
- на https://mermaid.live — вставить код из файла (блок ```mermaid), либо
- в VS Code с плагином «Markdown Preview Mermaid Support», либо
- в GitHub/GitLab — рендерят Mermaid автоматически при просмотре .md файла.

## Частые вопросы Windows

«`python` не является внутренней или внешней командой» → Python не установлен или не отмечен PATH → переустановите с галочкой «Add python.exe to PATH».

«`pytest` не установлен» → выполните `python -m pip install pytest`, или запускайте как `python -m pytest -q`.

Антивирус ругается на .py-файлы → это текстовые файлы кода (безопасно); открывайте их в Блокноте, чтобы убедиться.

## Передача дальше (в почту / мессенджер / 1С / документооборот)

- В ZIP можно просто вложить как обычный файл-вложение письма (Gmail/Outlook примут без вопросов).
- Если нужен документ «как для юристов» — читать `reg_matrix.md` и `c4_container.md`.
- Если нужен документ «как сбер-IB» (информационная безопасность) — читать `data_flows.md`.

## Выходные артефакты (все 4)

| # | Файл | Что внутри |
|---|------|-----------|
| 1 | `c4_container.md` | C4-архитектура контейнеров (Mermaid) + 5 ADR |
| 2 | `data_flows.md` | 5 Mermaid-диаграмм потоков с consent-логикой |
| 3 | `assistant/` + `tests/` | Python-прототип RoleContextManager (6/6 тестов) |
| 4 | `reg_matrix.md` | Матрица соответствия 152-ФЗ / банковская тайна / ТК РФ |
