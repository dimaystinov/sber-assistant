# Публикация сайта проекта

**Основной адрес:** https://sber.dimaystinov.duckdns.org/  
**Презентация:** https://sber.dimaystinov.duckdns.org/deck/  
**PDF:** https://sber.dimaystinov.duckdns.org/case.pdf
**GitHub Pages:** https://dimaystinov.github.io/sber-assistant/

На сервере `ok` Nginx отдаёт только статические файлы из `/var/www/sber-assistant-site`. Сертификат Let's Encrypt выпущен для `sber.dimaystinov.duckdns.org`; HTTP перенаправляется на HTTPS. Конфигурация хранится в [`deploy/nginx-sber-site.conf`](../deploy/nginx-sber-site.conf). Другие сайты на сервере используют отдельные виртуальные хосты.

Статический пакет собирается из `site/index.html`, `presentation/animated.html`, изображений в `presentation/assets/` и итогового PDF. Он не содержит `.env`, токенов и кода backend. Ссылка «Запустить локально» ведёт к инструкции в README. Настоящий интерактивный ассистент не размещён публично: текущий demo API использует одного учебного субъекта и не предназначен для общего доступа многих посетителей.

В репозитории также есть [workflow GitHub Pages](../.github/workflows/pages.yml), публикующий тот же пакет при изменении сайта, презентации или PDF. Источник **GitHub Actions** включён 11 ноября 2026 года; повторный запуск [workflow](https://github.com/dimaystinov/sber-assistant/actions/runs/42904499974) завершился успешно. Проверка публикации: запросы к `/`, `/deck/`, `/case.pdf` и изображениям должны возвращать HTTP 200; браузерная консоль должна быть без ошибок.

Для обновления серверной копии после изменения исходников нужно пересобрать публичный каталог и синхронизировать его с `ok:/var/www/sber-assistant-site/`, затем проверить перечисленные URL. Приватные файлы проекта нельзя копировать в веб-корень.
