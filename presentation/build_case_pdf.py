"""Build the 15-slide championship PDF from checked scenario calculations."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from evals.case_economics import SCENARIOS, calculate


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/universal-assistant-case-2026.pdf"
W, H = 960, 540
INK = colors.HexColor("#08261F")
FOREST = colors.HexColor("#061D19")
GREEN = colors.HexColor("#0BB86B")
LIME = colors.HexColor("#9AF7B5")
PAPER = colors.HexColor("#F6FBF7")
MUTED = colors.HexColor("#60776D")
CYAN = colors.HexColor("#4BDcff")
VIOLET = colors.HexColor("#9367F5")
RED = colors.HexColor("#BE4D50")


def register_fonts() -> None:
    candidates = [
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
         Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("Deck", str(regular)))
            pdfmetrics.registerFont(TTFont("DeckBold", str(bold)))
            return
    raise FileNotFoundError("Install Arial or DejaVu Sans TTF to build the PDF")


def text(c: Canvas, x: float, top: float, value: str, size: int = 18,
         color: colors.Color = INK, bold: bool = False) -> None:
    c.setFillColor(color)
    c.setFont("DeckBold" if bold else "Deck", size)
    c.drawString(x, H - top - size, value)


def para(c: Canvas, x: float, top: float, value: str, width: float,
         size: int = 19, leading: int | None = None,
         color: colors.Color = INK, bold: bool = False) -> float:
    font = "DeckBold" if bold else "Deck"
    leading = leading or int(size * 1.38)
    y = top
    for part in value.split("\n"):
        for line in simpleSplit(part, font, size, width) or [""]:
            text(c, x, y, line, size, color, bold)
            y += leading
    return y


def box(c: Canvas, x: float, top: float, width: float, height: float,
        fill: colors.Color, radius: int = 18) -> None:
    c.setFillColor(fill)
    c.roundRect(x, H - top - height, width, height, radius, fill=1, stroke=0)


def line(c: Canvas, x1: float, top1: float, x2: float, top2: float,
         color: colors.Color = GREEN, width: float = 2) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x1, H - top1, x2, H - top2)


def base(c: Canvas, number: int, label: str, dark: bool = False) -> None:
    c.setFillColor(FOREST if dark else PAPER)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    text(c, 56, 26, label.upper(), 11, LIME if dark else GREEN, True)
    text(c, 860, 26, f"{number:02d} / 15", 11, LIME if dark else MUTED, True)
    line(c, 56, 507, 904, 507, colors.HexColor("#31544A") if dark else colors.HexColor("#CDE4D5"), 1)
    text(c, 56, 514, "AI FOR BUSINESS CUP ’26  ·  НЕЗАВИСИМЫЙ ПРОЕКТ", 9,
         colors.HexColor("#B6D8CA") if dark else MUTED)


def heading(c: Canvas, value: str, dark: bool = False, size: int = 36) -> None:
    para(c, 56, 70, value, 842, size, int(size * 1.12),
         colors.white if dark else INK, True)


def card(c: Canvas, x: float, top: float, width: float, height: float,
         eyebrow: str, body: str, dark: bool = False) -> None:
    box(c, x, top, width, height,
        colors.HexColor("#103D35") if dark else colors.white)
    text(c, x + 20, top + 18, eyebrow.upper(), 12, LIME if dark else GREEN, True)
    para(c, x + 20, top + 48, body, width - 40, 18, 25,
         colors.white if dark else INK)


def note(c: Canvas, value: str, dark: bool = False) -> None:
    para(c, 56, 469, value, 840, 11, 14,
         colors.HexColor("#A9C6BA") if dark else MUTED)


def money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.1"))
    rendered = f"{abs(rounded):,.1f}".replace(",", " ").replace(".", ",")
    if rendered.endswith(",0"):
        rendered = rendered[:-2]
    return ("−" if rounded < 0 else "+" if rounded > 0 else "") + rendered


def build() -> Path:
    register_fonts()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(OUTPUT), pagesize=(W, H), pageCompression=1)
    c.setTitle("Универсальный помощник — AI for Business Cup ’26")
    c.setAuthor("Независимый проект для кейс-чемпионата")
    base_rows = calculate(SCENARIOS["base"])
    totals = {name: sum(row.net_effect_mrub for row in calculate(scenario))
              for name, scenario in SCENARIOS.items()}

    # 1 — cover
    c.drawImage(ImageReader(str(ROOT / "presentation/assets/neon-ribbon.png")),
                0, 0, width=W, height=H, mask="auto")
    c.saveState()
    c.setFillAlpha(.82)
    c.setFillColor(FOREST)
    c.rect(0, 0, 610, H, fill=1, stroke=0)
    c.restoreState()
    text(c, 56, 38, "AI FOR BUSINESS CUP ’26  /  КЕЙС СБЕРА", 13, LIME, True)
    para(c, 56, 124, "Один человек.\nТри роли.\nОдно ядро.", 650, 48, 58,
         colors.white, True)
    para(c, 58, 344, "Универсальный помощник с\nконтролируемым мостом согласий",
         530, 23, 31, colors.HexColor("#D8F9E8"))
    text(c, 58, 494, "Предложение для 2027–2029 · сценарная экономика, не прогноз Сбера", 12,
         colors.HexColor("#B9DCCE"))
    c.showPage()

    # 2 — diagnosis
    base(c, 2, "Диагностика")
    heading(c, "Три помощника теряют контекст одного человека")
    card(c, 56, 177, 263, 222, "Клиент", "ГигаЧат в СберБанк Онлайн. История связана со Сбер ID.")
    card(c, 348, 177, 263, 222, "Предприниматель", "Giga-ассистент в СберБизнесе. Отдельный вход и новая история.")
    card(c, 640, 177, 263, 222, "Сотрудник", "«Пульс» и внутренние системы. Иной круг прав и целей обработки.")
    note(c, "Проблема кейса: повторный ввод, несвязанные доступы и потеря доверия. Масштаб потерь ещё не измерен. Источник: кейс, стр. 3–5.")
    c.showPage()

    # 3 — cases
    base(c, 3, "Сквозные сценарии")
    heading(c, "Универсальность нужна в конкретных переходах")
    card(c, 56, 165, 400, 116, "01 · Самозанятый → ИП", "Демо переносит только тип задачи. Факты потребуют согласованной карты данных и прав.")
    card(c, 485, 165, 418, 116, "02 · Бизнес → личная роль", "Одноразовый сигнал продолжает путь без раскрытия истории и счёта.")
    card(c, 56, 302, 847, 114, "03 · Сотрудник", "Общее ядро даёт поиск и действия в рабочем контуре; HR-данные не идут в коммерческую роль.")
    note(c, "Учебный переход доступен в HTTP и UI. Передача банковских фактов остаётся целевым этапом после правовой проверки.")
    c.showPage()

    # 4 — business initiative
    base(c, 4, "Бизнес-инициатива · единый профиль")
    heading(c, "Профиль связывает роли, но хранит данные раздельно")
    for x, label, sub in ((56, "Сбер ID", "Частная роль"),
                          (355, "СберБизнес ID", "Бизнес-роль"),
                          (654, "Рабочий вход", "Сотрудник")):
        card(c, x, 172, 250, 119, label, sub)
    line(c, 180, 316, 780, 316, GREEN, 3)
    box(c, 278, 332, 404, 84, colors.HexColor("#DFFBED"))
    text(c, 303, 345, "МОСТ ИДЕНТИЧНОСТЕЙ И СОГЛАСИЙ", 13, GREEN, True)
    para(c, 303, 370, "Связка → право → минимальный факт → отзыв", 350, 18)
    note(c, "Связка аккаунтов и проверка полномочий в прототипе не интегрированы с системами Сбера; здесь показана целевая архитектура.")
    c.showPage()

    # 5 — consent
    base(c, 5, "Правила переноса")
    heading(c, "Согласие задаётся для цели, источника и получателя")
    steps = [
        ("1", "Подтвердить", "личность и обе роли"),
        ("2", "Показать", "какой сигнал и зачем"),
        ("3", "Разрешить", "в обеих ролях и на запрос"),
        ("4", "Отозвать", "и удалить производное"),
    ]
    for i, (number, label, desc) in enumerate(steps):
        x = 56 + i * 218
        box(c, x, 174, 193, 210, colors.white)
        text(c, x + 18, 188, number, 39, GREEN, True)
        text(c, x + 18, 253, label, 18, INK, True)
        para(c, x + 18, 284, desc, 160, 16, 22)
    note(c, "В демо проверяются оба cross-role согласия и opt-in запроса; переносится только намерение. Юридическая форма требует владельца процесса.")
    c.showPage()

    # 6 — common core
    base(c, 6, "Технологическая инициатива · общее ядро")
    heading(c, "Три канала используют один управляемый контур")
    for x, label in ((56, "СберБанк Онлайн"), (355, "СберБизнес"), (654, "Портал сотрудника")):
        box(c, x, 164, 250, 64, colors.white)
        text(c, x + 18, 182, label, 17, INK, True)
        line(c, x + 125, 228, x + 125, 260, GREEN)
    box(c, 56, 260, 847, 84, colors.HexColor("#DFFBED"))
    text(c, 80, 277, "ОБЩЕЕ ЯДРО", 13, GREEN, True)
    para(c, 80, 300, "маршрутизация GigaChat · ролевой RAG · критик · broker инструментов", 800, 20)
    for x, label in ((56, "Розничные знания"), (355, "Бизнес-данные"), (654, "Рабочие регламенты")):
        line(c, x + 125, 344, x + 125, 367, GREEN)
        box(c, x, 367, 250, 60, colors.white)
        text(c, x + 17, 385, label, 16, INK, True)
    note(c, "В текущем коде MCP и данные учебные; адаптеры трёх реальных каналов — часть дорожной карты.")
    c.showPage()

    # 7 — safety
    base(c, 7, "Безопасность и доверие", dark=True)
    heading(c, "Модель предлагает; сервер проверяет и ограничивает", dark=True)
    for i, (label, body) in enumerate((
        ("Роль и право", "Проверка до поиска и действия"),
        ("Источник", "Версия, доступ, доказательство"),
        ("Расчёт", "Типизированный код и Decimal"),
        ("Критик", "Независимая проверка черновика"),
        ("Действие", "Подтверждение и конечное состояние"),
    )):
        x = 56 + i * 172
        box(c, x, 169, 155, 218, colors.HexColor("#103D35"))
        text(c, x + 13, 184, f"0{i+1}", 12, CYAN, True)
        para(c, x + 13, 221, label, 127, 18, 22, colors.white, True)
        para(c, x + 13, 270, body, 127, 14, 20, colors.HexColor("#C9E8DA"))
    note(c, "Критик не гарантирует безошибочность. Принципы кейса: Secure, Explainable, Reliable, Responsible, Fair AI.", True)
    c.showPage()

    # 8 — proof and limits
    base(c, 8, "Что проверено")
    heading(c, "Прототип проверяет границы, не банковский эффект")
    card(c, 56, 162, 263, 199, "Код", "105 автоматических тестов; HTTP-переход, изоляция ролей, источники и расчёт проверяются отдельно.")
    card(c, 348, 162, 263, 199, "Симуляция", "Два массива по 3 600 учебных эпизодов. Сценарии параметризованы, модель часто заменена заглушкой.")
    card(c, 640, 162, 263, 199, "Реальный банк", "Песочница Sber API пока не подключена. Внутренних регламентов и полевых метрик нет.")
    note(c, "Число тестов зафиксировано при сборке PDF; проверяется повторным запуском pytest. Источник результатов: репозиторий проекта.")
    c.showPage()

    # 9 — metrics
    base(c, 9, "Как измерять пользу")
    heading(c, "Пилот сравнивает новый путь с действующими помощниками")
    card(c, 56, 165, 263, 220, "Для человека", "Время до результата; повторный ввод; завершение задачи без исправления.")
    card(c, 348, 165, 263, 220, "Для Сбера", "Избежанные обращения; реализуемая стоимость; стоимость на задачу.")
    card(c, 640, 165, 263, 220, "Для доверия", "Опт-ин и отзыв; критические ошибки; доля эскалаций; разрезы по ролям.")
    note(c, "Оценка — по контрольной группе и конечному состоянию задачи; исходные метрики у Сбера требуется получить до пилота.")
    c.showPage()

    # 10 — assumptions
    base(c, 10, "Экономика · допущения")
    heading(c, "Размер пересечения ролей неизвестен")
    text(c, 56, 156, "БАЗОВЫЙ СЦЕНАРИЙ · ПЛАНОВЫЕ ДОПУЩЕНИЯ, НЕ ПРОГНОЗ", 13, GREEN, True)
    assumptions = [
        ("Люди со связкой, тыс.", "100 / 500 / 1 200"),
        ("Сквозные задачи на человека", "4 / 6 / 8"),
        ("Избежано повторных обращений", "25% задач"),
        ("Эффективная ценность обращения", "120 руб."),
        ("Инференс и поиск на задачу", "5 руб."),
        ("Выигрыш человека", "3 мин / задачу"),
    ]
    for i, (key, value) in enumerate(assumptions):
        top = 193 + i * 41
        if i % 2 == 0:
            box(c, 56, top - 2, 847, 39, colors.white, 9)
        text(c, 72, top + 7, key, 17)
        text(c, 642, top + 7, value, 17, INK, True)
    note(c, "110,7 млн частных клиентов и 3,5 млн компаний из кейса — разные базы, не число людей с несколькими ролями. Источник: кейс, стр. 6–7.")
    c.showPage()

    # 11 — costs
    base(c, 11, "Стоимость 2027–2029")
    heading(c, "Стоимость включает интеграции, эксплуатацию и контроль")
    labels = ("Разработка и интеграции", "Платформа", "ИБ, право и оценка", "Инференс и поиск", "ИТОГО")
    values = [
        [row.build_mrub for row in base_rows],
        [row.platform_ops_mrub for row in base_rows],
        [row.governance_mrub for row in base_rows],
        [row.inference_mrub for row in base_rows],
        [row.total_cost_mrub for row in base_rows],
    ]
    text(c, 56, 158, "БАЗОВЫЙ СЦЕНАРИЙ, МЛН РУБ.", 13, GREEN, True)
    for j, year in enumerate((2027, 2028, 2029)):
        text(c, 560 + j * 112, 158, str(year), 15, INK, True)
    for i, label in enumerate(labels):
        top = 198 + i * 45
        box(c, 56, top - 5, 847, 40, colors.HexColor("#DFFBED") if i == 4 else colors.white, 8)
        text(c, 70, top + 3, label, 17, INK, i == 4)
        for j, value in enumerate(values[i]):
            text(c, 560 + j * 112, top + 3, money(value).lstrip("+"), 17, INK, i == 4)
    note(c, "Все ставки — допущения команды; смета, цена GigaChat и требования к инфраструктуре должны быть проверены с владельцами Сбера.")
    c.showPage()

    # 12 — base effect
    base(c, 12, "Эффект 2027–2029", dark=True)
    heading(c, "Базовый сценарий выходит в плюс только к 2029 году", dark=True)
    text(c, 56, 159, "СЦЕНАРНЫЕ ДОПУЩЕНИЯ · МЛН РУБ. · НЕ ФАКТИЧЕСКИЙ ЭФФЕКТ", 12, LIME, True)
    for i, row in enumerate(base_rows):
        top = 200 + i * 80
        text(c, 57, top, str(row.year), 26, colors.white, True)
        text(c, 240, top + 2, f"Эффект {money(row.gross_effect_mrub).lstrip('+')}", 18, LIME)
        text(c, 445, top + 2, f"Стоимость {money(row.total_cost_mrub).lstrip('+')}", 18,
             colors.HexColor("#C3D5CC"))
        text(c, 735, top - 4, money(row.net_effect_mrub), 30,
             LIME if row.net_effect_mrub > 0 else colors.HexColor("#FFAA9D"), True)
        line(c, 56, top + 53, 903, top + 53, colors.HexColor("#31544A"), 1)
    text(c, 56, 446, "ИТОГО ЗА 3 ГОДА", 16, colors.white, True)
    text(c, 740, 440, "+30", 32, LIME, True)
    note(c, "Время человека: 20 / 150 / 480 тыс. часов по годам; оно не включено в рублёвый эффект. Расчёт: evals/case_economics.py.", True)
    c.showPage()

    # 13 — sensitivity
    base(c, 13, "Чувствительность")
    heading(c, "Положительный итог зависит от охвата и реальной экономии")
    text(c, 56, 158, "ЧИСТЫЙ ЭФФЕКТ ЗА 2027–2029, МЛН РУБ.", 13, GREEN, True)
    for i, (name, label) in enumerate((("low", "Низкий"), ("base", "Базовый"),
                                       ("high", "Высокий"))):
        top = 207 + i * 88
        value = totals[name]
        text(c, 56, top + 5, label, 21, INK, True)
        box(c, 260, top, min(540, 34 + float(abs(value)) * .75), 39,
            RED if value < 0 else GREEN, 9)
        text(c, 805, top + 4, money(value), 23, RED if value < 0 else GREEN, True)
    box(c, 56, 429, 847, 35, colors.HexColor("#DFFBED"), 8)
    text(c, 70, 435, "Порог 2029: 500 тыс. людей со связкой в базовых удельных допущениях", 15, INK, True)
    note(c, "Если стоимость обращения не высвобождается, экономический эффект падает. Нельзя выдавать базовый сценарий за прогноз Сбера.")
    c.showPage()

    # 14 — roadmap
    base(c, 14, "Дорожная карта")
    heading(c, "Масштабирование зависит от доказанного результата")
    card(c, 56, 168, 263, 247, "2027 · Право и пилот", "Связка ID, карта данных, baseline и малый пилот трёх каналов. Gate: законность потока и отсутствие критических действий.")
    card(c, 348, 168, 263, 247, "2028 · Расширение", "Утверждённые знания, read-only инструменты и контрольная группа. Gate: качество, эффект и работающий отзыв согласия.")
    card(c, 640, 168, 263, 247, "2029 · Масштаб", "Только сценарии с положительным эффектом и управляемым риском. Gate: независимый аудит и экономика на реальных данных.")
    note(c, "Владельцы: розница и МСБ совместно с HR/ИТ, ИБ, правовой функцией и владельцами процессов. Подробности: docs/ECONOMICS-ROADMAP-2027-2029.md.")
    c.showPage()

    # 15 — decision
    base(c, 15, "Решение", dark=True)
    heading(c, "Начать с измеримого пилота общего ядра", dark=True, size=43)
    para(c, 56, 195,
         "1. Утвердить 2–3 сквозных сценария и карту согласий.\n"
         "2. Измерить пересечение ролей и стоимость текущих обращений.\n"
         "3. Проверить безопасность, полезность и эффект до масштаба.",
         820, 24, 48, colors.white)
    line(c, 56, 392, 903, 392, LIME, 2)
    para(c, 56, 411, "Источник задания: AI for Business Cup ’26, кейс Сбера, v3, стр. 3–8.\n"
         "Модель, допущения, код и тесты: github.com/dimaystinov/sber-assistant",
         820, 13, 20, colors.HexColor("#B9DCCE"))
    c.showPage()

    c.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
