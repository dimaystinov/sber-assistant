#!/bin/sh
set -eu
launchctl remove local.yandex-isolated-vnc >/dev/null 2>&1 || true
docker container rm -f yandex-isolated >/dev/null 2>&1 || true
docker container rm -f yandex-egress >/dev/null 2>&1 || true
echo 'Яндекс.Браузер остановлен.'
