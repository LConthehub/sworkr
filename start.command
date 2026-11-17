#!/bin/sh
# Starts sworkr on a Mac (double-click) or Linux (run: sh start.command). Needs Docker Desktop to be running.
cd "$(dirname "$0")" || exit 1

if ! docker info >/dev/null 2>&1; then
    echo
    echo "Docker Desktop isn't running."
    echo "Open Docker Desktop, wait until it says \"Engine running\", then try again."
    echo "Don't have it yet? Get it from https://www.docker.com/products/docker-desktop/"
    echo
    exit 1
fi

echo "Starting sworkr. The first time takes a few minutes while it downloads what it needs..."
if ! docker compose up -d --build; then
    echo
    echo "sworkr couldn't start. The lines above say why."
    exit 1
fi

echo
echo "sworkr is running at http://localhost:8008"
echo "It keeps running in the background, and starts again by itself when Docker Desktop starts."
echo "To stop it, run stop.command."
command -v open >/dev/null 2>&1 && open http://localhost:8008
