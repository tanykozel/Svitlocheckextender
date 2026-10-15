#!/usr/bin/env bash
# One-time setup of the always-on bot on a fresh Ubuntu server (24.04 or newer, x86_64). Run as root:
#   curl -fsSL https://raw.githubusercontent.com/tanykozel/Svitlocheckextender/main/deploy/setup.sh | bash
# Safe to run again: it only adds what is missing and refreshes the service files.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo -i)"; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "Needs an x86_64 server (the pinned packages are x86_64 builds)"; exit 1; }
REPO="${REPO:-tanykozel/Svitlocheckextender}"
export DEBIAN_FRONTEND=noninteractive

echo "== Packages and automatic security updates"
apt-get update -q
apt-get install -yq git python3-venv unzip curl ufw unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
cat > /etc/apt/apt.conf.d/52svitlo-reboot <<'CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
CONF
timedatectl set-timezone Europe/Kyiv

echo "== Firewall (only SSH in) and SSH keys only"
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null
cat > /etc/ssh/sshd_config.d/50-svitlo.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
systemctl reload ssh || true  # takes effect at the next SSH start otherwise

echo "== Service user, code and Python packages"
id svitlo >/dev/null 2>&1 || useradd --system --home-dir /var/lib/svitlo --shell /usr/sbin/nologin svitlo
install -d -o svitlo -g svitlo -m 700 /var/lib/svitlo /var/lib/svitlo/state /var/lib/svitlo/metrics \
  /var/lib/svitlo/dash /var/lib/svitlo/backup
if [ -d /opt/svitlo/.git ]; then  # running setup again: take the latest main
  git -C /opt/svitlo fetch -q origin main && git -C /opt/svitlo reset -q --hard origin/main
else
  git clone -q "https://github.com/${REPO}.git" /opt/svitlo
fi
[ -x /opt/svitlo-venv/bin/python ] || python3 -m venv /opt/svitlo-venv
/opt/svitlo-venv/bin/pip install -q --require-hashes -r /opt/svitlo/requirements-bot.txt

echo "== Secrets files (root only)"
install -d -m 700 /etc/svitlo
[ -f /etc/svitlo/bot.env ] || install -m 600 /opt/svitlo/deploy/bot.env.example /etc/svitlo/bot.env
[ -f /etc/svitlo/github.env ] || install -m 600 /opt/svitlo/deploy/github.env.example /etc/svitlo/github.env

echo "== Services"
install -m 644 /opt/svitlo/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now svitlo-update.timer svitlo-metrics.timer svitlo-backup.timer

cat <<'NEXT'

Done. Next (see deploy/README.md):
  1. nano /etc/svitlo/bot.env      -> bot token and state key
  2. nano /etc/svitlo/github.env   -> GitHub token for the dashboard
  3. bash /opt/svitlo/deploy/import-state.sh   (after "Export bot state" ran on GitHub)
  4. systemctl enable --now svitlo-bot && journalctl -fu svitlo-bot
NEXT
