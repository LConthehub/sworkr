#!/bin/bash
# Stops sworkr. Your records stay. (Never add -v: that would delete them.)
cd "$(dirname "$0")"
docker compose down && echo "sworkr is stopped."
read -r -p "Press Return to close."
