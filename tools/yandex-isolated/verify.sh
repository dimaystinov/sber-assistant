#!/bin/sh
set -eu
config=$(docker inspect yandex-isolated --format '{{json .HostConfig}}')
printf '%s' "$config" | jq -e '.NetworkMode == "yandex-private" and .ReadonlyRootfs == true and .CapDrop == ["ALL"] and (.SecurityOpt | index("no-new-privileges:true")) != null and (.Binds == null or .Binds == []) and (.Mounts | length == 0)' >/dev/null
docker network inspect yandex-private --format '{{.Internal}}' | grep -qx true
docker inspect yandex-isolated --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' | grep -qx yandex-private
docker inspect yandex-isolated --format '{{.Config.User}}' | grep -qx '10001:10001'
docker exec yandex-isolated sh -c '! grep -q "^00000000" /proc/net/route'
if docker exec yandex-isolated wget -q -T 3 -O /dev/null http://1.1.1.1 2>/dev/null; then
  echo 'Ошибка: браузер получил прямой доступ к внешней сети.' >&2
  exit 1
fi
docker exec yandex-isolated sh -c 'ps -eo comm | grep -qx x11vnc'
docker inspect yandex-egress --format '{{.State.Running}}' | grep -qx true
docker exec -e https_proxy=http://172.30.240.3:3128 yandex-isolated \
  wget -q -T 10 -O /dev/null https://developers.sber.ru/docs/ru/sber-api/start/sandbox
docker exec -e https_proxy=http://172.30.240.3:3128 yandex-isolated \
  wget -q -T 10 -O /dev/null https://sbi.sberbank.ru:9443/
blocked=$(docker exec -e https_proxy=http://172.30.240.3:3128 yandex-isolated \
  wget -S -T 5 -O /dev/null https://api.browser.yandex.ru 2>&1 || true)
printf '%s' "$blocked" | grep -q 'Proxy tunneling failed: Forbidden'
echo 'Проверено: нет прямого выхода в сеть, монтирований и привилегий; Сбер доступен, домены Яндекса блокируются.'
