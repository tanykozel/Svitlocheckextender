#!/usr/bin/env bash
# One-time move of the subscribers from GitHub to this server. Run as root after the
# "Export bot state" workflow ran. The file stays encrypted with SVITLO_STATE_KEY the whole way.
set -euo pipefail
set -a; . /etc/svitlo/github.env; set +a
: "${GITHUB_TOKEN:?set it in /etc/svitlo/github.env}" "${GITHUB_REPOSITORY:?}"
target=/var/lib/svitlo/state/bot.json.enc  # encrypted with SVITLO_STATE_KEY
if [ -s "$target" ] && [ "${1:-}" != "--force" ]; then
  echo "$target already exists; run with --force to replace it"; exit 1
fi
api="https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts"
hdr=(-H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json")
read -r id url < <(curl -fsS "${hdr[@]}" "${api}?name=bot-state&per_page=1" |
  python3 -c "import json,sys; a=json.load(sys.stdin)['artifacts']; print(a[0]['id'], a[0]['archive_download_url']) if a else print('', '')")
[ -n "$id" ] || { echo "No 'bot-state' export found: run the Export bot state workflow first"; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -fsSL "${hdr[@]}" -o "$tmp/state.zip" "$url"
unzip -q -o "$tmp/state.zip" -d "$tmp"
install -o svitlo -g svitlo -m 600 "$tmp/bot.json.enc" "$target"
curl -fsS -X DELETE "${hdr[@]}" "${api}/${id}" && echo "Deleted the export from GitHub"
echo "Imported the encrypted bot state to $target"
