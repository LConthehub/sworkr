#!/bin/bash
# Gets the newest sworkr and restarts it. Your records stay.
cd "$(dirname "$0")"
docker compose pull && docker compose up -d && echo "Done. sworkr is up to date. Your records were kept."
read -r -p "Press Return to close."
