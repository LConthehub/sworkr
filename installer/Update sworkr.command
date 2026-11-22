#!/bin/bash
# Gets the newest sworkr and restarts it. Your records stay. Double-click this file.
exec /bin/bash "$(dirname "$0")/Start sworkr.command" update
