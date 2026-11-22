#!/bin/bash
# Starts sworkr and opens it in your browser. Double-click this file (the first time: right-click, Open).
# If Docker Desktop is installed but closed, this opens it and waits for it.
# "Update sworkr" runs this file with the word update, which gets the newest version first.
cd "$(dirname "$0")" || exit 1
# A double-clicked file doesn't always know where Docker lives, so say where it usually is.
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:/Applications/Docker.app/Contents/Resources/bin"

stop_here() { echo; read -r -p "Press Return to close." _; exit "$1"; }

if ! docker info >/dev/null 2>&1; then
  if [ -d /Applications/Docker.app ] || [ -d "$HOME/Applications/Docker.app" ]; then
    echo "Opening Docker Desktop. The first time, it may ask you something: answer it, then come back here."
    open -a Docker
    echo "Waiting for Docker to be ready. This can take a minute or two..."
    tries=0
    until docker info >/dev/null 2>&1; do
      tries=$((tries + 1))
      if [ "$tries" -ge 80 ]; then
        echo "Docker still isn't ready after 4 minutes."
        echo "Look at Docker Desktop: when it says Engine running, double-click this file again."
        stop_here 1
      fi
      sleep 3
    done
  elif command -v docker >/dev/null 2>&1; then
    echo "Docker isn't running. Start it, then double-click this file again."
    stop_here 1
  else
    echo "Docker Desktop isn't installed yet. It's the free program sworkr runs inside."
    echo "Your browser will open its download page. Install it, open it once, then double-click this file again."
    open "https://www.docker.com/products/docker-desktop/"
    stop_here 1
  fi
fi

if [ "$1" = "update" ]; then
  echo "Getting the newest sworkr..."
  if ! docker compose pull; then
    echo "Couldn't download the update. Check your internet connection and try again."
    echo "sworkr wasn't changed, and your records are safe."
    stop_here 1
  fi
else
  echo "Starting sworkr. The first time it downloads it, which takes a few minutes..."
fi
if ! docker compose up -d; then
  echo "sworkr couldn't start. The message above says why."
  echo "Help: sworkr.com/docs/troubleshooting.html"
  stop_here 1
fi

echo "Waiting for sworkr to answer..."
tries=0
until curl -s -o /dev/null --max-time 3 http://localhost:8008/api/health; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "It's taking longer than usual. If the page doesn't load, wait a minute and refresh it."
    break
  fi
  sleep 2
done
open http://localhost:8008
echo
echo "sworkr is running at http://localhost:8008"
echo "It keeps running in the background, and starts by itself whenever Docker Desktop starts."
if [ "$1" = "update" ]; then
  echo "Up to date. Your records were kept, and a copy was saved before any upgrade."
fi
echo "You can close this window."
