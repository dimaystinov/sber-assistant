#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
image=yandex-isolated:26.10.0.1882-proxy4
proxy_image=yandex-egress:3
network=yandex-private
password_file="$root/vnc-password.txt"
umask 077
if [ ! -f "$password_file" ]; then
  openssl rand -base64 6 >"$password_file"
fi

if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker build --platform linux/amd64 -t "$image" "$root"
fi
if ! docker image inspect "$proxy_image" >/dev/null 2>&1; then
  docker build -f "$root/Dockerfile.proxy" -t "$proxy_image" "$root"
fi
if ! docker network inspect "$network" >/dev/null 2>&1; then
  docker network create --internal --subnet 172.30.240.0/24 "$network" >/dev/null
fi

docker container rm -f yandex-isolated >/dev/null 2>&1 || true
docker container rm -f yandex-egress >/dev/null 2>&1 || true
docker run -d --pull never --name yandex-egress \
  --network "$network" --ip 172.30.240.3 \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --pids-limit 128 --memory 512m --cpus 1 \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m,uid=10002,gid=10002 \
  --tmpfs /var/spool/squid:rw,nosuid,nodev,size=64m,uid=10002,gid=10002 \
  --tmpfs /run/squid:rw,nosuid,nodev,size=16m,uid=10002,gid=10002 \
  "$proxy_image" >/dev/null
docker network connect bridge yandex-egress
docker run -d --pull never --name yandex-isolated \
  --network "$network" --ip 172.30.240.2 --dns 127.0.0.1 \
  --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --pids-limit 256 \
  --memory 3g --cpus 2 --shm-size 512m \
  --tmpfs /home/browser:rw,nosuid,nodev,size=512m,uid=10001,gid=10001 \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m,uid=10001,gid=10001 \
  --tmpfs /run:rw,nosuid,nodev,size=64m,uid=10001,gid=10001 \
  "$image" >/dev/null
docker exec yandex-isolated mkdir -p -m 0700 /home/browser/Downloads

printf '%s\n' "$(cat "$password_file")" | docker exec -i yandex-isolated \
  sh -c 'read -r password; x11vnc -storepasswd "$password" /tmp/vnc.pass >/dev/null'

for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if docker exec yandex-isolated sh -c 'ps -eo comm | grep -qx x11vnc' 2>/dev/null; then break; fi
  sleep 1
done
docker exec yandex-isolated sh -c 'ps -eo comm | grep -qx x11vnc' || { docker logs yandex-isolated; exit 1; }

if command -v socat >/dev/null 2>&1; then
  docker_bin=$(command -v docker)
  launchctl remove local.yandex-isolated-vnc >/dev/null 2>&1 || true
  launchctl submit -l local.yandex-isolated-vnc -- "$(command -v socat)" \
    TCP4-LISTEN:5909,bind=127.0.0.1,reuseaddr,fork \
    "EXEC:\"$docker_bin exec -i yandex-isolated socat STDIO TCP4:127.0.0.1:5900\""
  echo 'VNC: 127.0.0.1:5909'
else
  echo 'Контейнер запущен; для локального VNC-моста установите socat.'
fi
"$root/verify.sh"
for attempt in 1 2 3 4 5; do
  if python3 -c 'import socket; s=socket.create_connection(("127.0.0.1", 5909), 2); assert s.recv(12) == b"RFB 003.008\n"; s.close()' 2>/dev/null; then
    echo 'Локальный VNC-мост проверен.'
    exit 0
  fi
  sleep 1
done
echo 'Ошибка: локальный VNC-мост не отвечает.' >&2
exit 1
