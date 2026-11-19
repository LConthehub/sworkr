#!/bin/sh
# Linux: starts sworkr. Run ./start.sh in this folder.
cd "$(dirname "$0")" || exit 1
docker compose up -d && echo "sworkr is starting: open http://localhost:8008 in a minute."
