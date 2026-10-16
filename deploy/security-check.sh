#!/usr/bin/env bash
# Read-only security report for the bot server. Run as root:  bash /opt/svitlo/deploy/security-check.sh
# Prints PASS / WARN lines only: never secrets, chat ids or addresses, so the output is safe to share.
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
pass=0; warn=0
ok()   { echo "PASS  $*"; pass=$((pass + 1)); }
bad()  { echo "WARN  $*"; warn=$((warn + 1)); }
check() { if eval "$1" >/dev/null 2>&1; then ok "$2"; else bad "$2${3:+ -> $3}"; fi; }

echo "== Svitlo server security report, $(date '+%F %H:%M %Z'), $(. /etc/os-release; echo "$PRETTY_NAME")"

echo "-- Access"
sshd_cfg=$(sshd -T 2>/dev/null)
check "grep -qx 'passwordauthentication no' <<<\"\$sshd_cfg\"" "SSH: passwords switched off (keys only)"
check "grep -qx 'permitrootlogin without-password' <<<\"\$sshd_cfg\" || grep -qx 'permitrootlogin prohibit-password' <<<\"\$sshd_cfg\"" \
  "SSH: root may log in with a key only"
check "ufw status | grep -q 'Status: active'" "Firewall on"
open_ports=$(ss -Htln | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|::1)' | sed 's/.*://' | sort -u | tr '\n' ' ')
if [ "$(echo $open_ports)" = "22" ]; then ok "Only SSH (port 22) listens to the internet"; else bad "Ports open to the internet: ${open_ports:-none} (expected only 22)"; fi
failed=$(journalctl -u ssh --since -24h 2>/dev/null | grep -cE 'Invalid user|Failed (password|publickey)')
ok "Refused SSH login attempts in 24 h: ${failed:-0} (normal on the internet; passwords are off)"

echo "-- Updates"
check "grep -q 'Unattended-Upgrade \"1\"' /etc/apt/apt.conf.d/20auto-upgrades" "Automatic security updates on"
pending=$(apt list --upgradable 2>/dev/null | grep -c security)
if [ "${pending:-0}" -eq 0 ]; then ok "No security updates waiting"; else bad "$pending security update(s) waiting (installed automatically overnight)"; fi
if [ -f /var/run/reboot-required ]; then bad "A reboot is pending (done automatically at 04:30)"; else ok "No reboot pending"; fi

echo "-- Secrets"
check "[ \"\$(stat -c '%a %U' /etc/svitlo)\" = '700 root' ]" "/etc/svitlo readable by root only"
for f in /etc/svitlo/bot.env /etc/svitlo/github.env; do
  check "[ \"\$(stat -c '%a %U' $f)\" = '600 root' ]" "$(basename $f): root only (600)"
done
check "grep -qE '^SVITLO_STATE_KEY=.{32,}' /etc/svitlo/bot.env" "State key set and long enough"

echo "-- Subscriber data (encrypted at rest)"
data=/var/lib/svitlo
check "[ \"\$(stat -c '%a %U' $data)\" = '700 svitlo' ]" "Data folder: bot user only (700)"
check "[ ! -e $data/state/bot.json ]" "No unencrypted state file"
check "head -c 6 $data/state/bot.json.enc | grep -q '^gAAAAA'" "State file is encrypted (Fernet: AES + HMAC)"
plain=$(find $data/state $data/backup -type f ! -name '*.enc' 2>/dev/null | wc -l)
if [ "$plain" -eq 0 ]; then ok "Every saved copy is encrypted"; else bad "$plain unencrypted file(s) in state/backup"; fi
for b in $data/backup/*.enc; do [ -e "$b" ] || continue; head -c 6 "$b" | grep -q '^gAAAAA' || bad "Backup not encrypted: $(basename "$b")"; done
copies=$(find $data/backup -name '*.enc' 2>/dev/null | wc -l)
if [ "$copies" -le 3 ]; then ok "Backups kept: $copies (max 3 days)"; else bad "Backups kept: $copies (expected at most 3)"; fi

echo "-- Logs and dashboard numbers (no personal data)"
# chat#… labels are keyed hashes (masked ids), so they are left out of the search
logs=$(journalctl -u svitlo-bot -u svitlo-metrics -o cat --since -7d 2>/dev/null | sed -E 's/chat#[0-9a-f]+//g')
ids=$(grep -cE '(^|[^0-9:.-])[0-9]{6,12}([^0-9:.-]|$)' <<<"$logs")
addr=$(grep -ciE 'вул\.|вулиця|street [0-9]' <<<"$logs")
if [ "$ids" -eq 0 ]; then ok "No chat-id-like numbers in 7 days of bot logs"; else bad "$ids log line(s) contain long numbers: check with journalctl -u svitlo-bot"; fi
if [ "$addr" -eq 0 ]; then ok "No addresses in 7 days of bot logs"; else bad "$addr log line(s) mention a street"; fi
if grep -rqE '"(subs|label|house|street_id|chat|free_texts)"' $data/metrics $data/dash 2>/dev/null; then
  bad "Dashboard files contain personal fields"; else ok "Dashboard files hold numbers only"; fi

echo "-- Bot service"
check "systemctl is-active -q svitlo-bot" "Bot running"
check "[ \"\$(systemctl show -p User --value svitlo-bot)\" = svitlo ]" "Bot runs as its own user, not root"
exposure=$(systemd-analyze security svitlo-bot --no-pager 2>/dev/null | tail -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
if [ -n "$exposure" ] && awk "BEGIN{exit !($exposure < 5)}"; then ok "Service sandbox exposure score $exposure (lower is safer; < 5 = good)"
else bad "Service sandbox exposure score ${exposure:-unknown} (expected < 5)"; fi
for t in svitlo-update svitlo-metrics svitlo-backup; do check "systemctl is-active -q $t.timer" "$t timer active"; done

echo "== Result: $pass PASS, $warn WARN"
