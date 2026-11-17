#!/bin/sh
# Stops sworkr on a Mac or Linux. Your data is kept; start.command brings it back.
cd "$(dirname "$0")" || exit 1
docker compose down
echo
echo "sworkr is stopped. Your data is safe. Run start.command to start it again."
