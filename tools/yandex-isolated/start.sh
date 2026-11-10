#!/bin/sh
set -eu

export HOME=/home/browser
export DISPLAY=:99
mkdir -p -m 0700 /home/browser/Downloads

Xvfb :99 -screen 0 1366x768x24 -nolisten tcp -noreset &
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if xdpyinfo -display :99 >/dev/null 2>&1; then break; fi
  sleep 0.2
done
xdpyinfo -display :99 >/dev/null

fluxbox -display :99 >/dev/null 2>&1 &
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if [ -f /tmp/vnc.pass ]; then break; fi
  sleep 0.5
done
[ -f /tmp/vnc.pass ]
x11vnc -display :99 -localhost -rfbport 5900 \
  -forever -shared -noxdamage -rfbauth /tmp/vnc.pass -quiet >/dev/null 2>&1 &

exec /opt/yandex/browser/yandex-browser \
  --user-data-dir=/home/browser/profile \
  --no-sandbox \
  --proxy-server=http://172.30.240.3:3128 \
  --proxy-bypass-list='<-loopback>' \
  --disable-quic \
  --no-first-run --no-default-browser-check \
  --disable-background-networking --disable-sync \
  --disable-component-update --disable-breakpad \
  --disable-extensions --disable-gpu about:blank
