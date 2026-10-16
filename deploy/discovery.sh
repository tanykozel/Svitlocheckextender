#!/usr/bin/env bash
# Owner only: what people wrote to the bot in their own words and it did not understand (discovery).
# Texts are anonymous (no chat id) and masked (digits -> #). Run as root:  bash /opt/svitlo/deploy/discovery.sh
# Do not paste the output anywhere public: people may still have typed something personal.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
set -a; . /etc/svitlo/bot.env; set +a
cd /opt/svitlo
exec runuser -u svitlo --preserve-environment -- /opt/svitlo-venv/bin/python -m svitlo_notifier discovery \
  --state /var/lib/svitlo/state/bot.json "$@"
