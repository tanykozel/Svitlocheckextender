#!/usr/bin/env bash
# Continuous deployment: a merge into main goes live within ~5 minutes, like the GitHub runs did.
set -euo pipefail
cd /opt/svitlo
git fetch -q origin main
[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] || exit 0
git reset -q --hard origin/main
/opt/svitlo-venv/bin/pip install -q --require-hashes -r requirements-bot.txt
install -m 644 deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
if systemctl is-enabled -q svitlo-bot; then systemctl restart svitlo-bot; fi
echo "deployed $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
