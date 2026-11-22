#!/bin/sh
# Linux: starts sworkr. Run ./start.sh in this folder. ./start.sh update gets the newest version first.
cd "$(dirname "$0")" || exit 1

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed. Install Docker Engine and its compose plugin: https://docs.docker.com/engine/install/"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running, or your user isn't allowed to use it."
  echo "Try: sudo systemctl start docker   and add yourself to the docker group (then log out and back in)."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker's compose plugin is missing. Install docker-compose-plugin (or docker-compose-v2) from your package manager."
  exit 1
fi

if [ "$1" = "update" ]; then
  echo "Getting the newest sworkr..."
  docker compose pull || { echo "Couldn't download the update. sworkr wasn't changed, and your records are safe."; exit 1; }
else
  echo "Starting sworkr. The first time it downloads it, which takes a few minutes..."
fi
docker compose up -d || { echo "sworkr couldn't start. The message above says why. Help: sworkr.com/docs/troubleshooting.html"; exit 1; }

if command -v curl >/dev/null 2>&1; then
  echo "Waiting for sworkr to answer..."
  tries=0
  until curl -s -o /dev/null --max-time 3 http://localhost:8008/api/health; do
    tries=$((tries + 1))
    [ "$tries" -ge 60 ] && { echo "It's taking longer than usual. If the page doesn't load, wait a minute and refresh it."; break; }
    sleep 2
  done
fi
echo "sworkr is running at http://localhost:8008"
[ "$1" = "update" ] && echo "Up to date. Your records were kept, and a copy was saved before any upgrade."
command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:8008 >/dev/null 2>&1 &
exit 0
