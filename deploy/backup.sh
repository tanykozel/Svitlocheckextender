#!/usr/bin/env bash
# Daily copy of the encrypted bot state; copies older than 3 days are deleted, so someone who sent
# /stop is gone from every copy within 3 days.
set -euo pipefail
state=/var/lib/svitlo/state/bot.json.enc
backups=/var/lib/svitlo/backup
[ -f "$state" ] || exit 0
cp "$state" "$backups/bot-$(date +%F).json.enc"
find "$backups" -name 'bot-*.json.enc' -mtime +2 -delete
