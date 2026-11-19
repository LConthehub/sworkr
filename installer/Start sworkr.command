#!/bin/bash
# Starts sworkr and opens it in your browser. Double-click this file (the first time: right-click, Open).
cd "$(dirname "$0")"
if ! docker info >/dev/null 2>&1; then
  echo
  echo "Docker isn't running yet."
  echo "Open Docker Desktop, wait until it says Engine running, then double-click this file again."
  read -r -p "Press Return to close."
  exit 1
fi
echo "Starting sworkr. The first time it downloads it, which takes a few minutes..."
if ! docker compose up -d; then
  echo "Something went wrong. The message above says what. sworkr.com/docs/troubleshooting.html can help."
  read -r -p "Press Return to close."
  exit 1
fi
sleep 5
open http://localhost:8008
