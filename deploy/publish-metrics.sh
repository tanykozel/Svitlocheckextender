#!/usr/bin/env bash
# Adds the bot's finished dashboard windows to the `metrics` branch (numbers only, no personal data).
# A record is deleted only after a successful push, so nothing is lost while GitHub is unreachable.
set -euo pipefail
: "${GITHUB_TOKEN:?set it in /etc/svitlo/github.env}" "${GITHUB_REPOSITORY:?}"
data="${SVITLO_DATA:-/var/lib/svitlo}"
code="${SVITLO_CODE:-/opt/svitlo}"
python="${SVITLO_PYTHON:-/opt/svitlo-venv/bin/python}"
shopt -s nullglob
records=("$data"/metrics/run-*.json)
[ ${#records[@]} -gt 0 ] || exit 0

auth="Authorization: Basic $(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
remote="${METRICS_REMOTE:-https://github.com/${GITHUB_REPOSITORY}.git}"
dash="$data/dash"
rm -rf "$dash" && mkdir -p "$dash"
git -C "$dash" init -q
if git -C "$dash" -c http.extraHeader="$auth" fetch -q --depth 1 "$remote" metrics; then
  for f in history.json daily.json events.json; do
    git -C "$dash" show "FETCH_HEAD:$f" > "$dash/$f" 2>/dev/null || rm -f "$dash/$f"
  done
fi
sha=$(git -c safe.directory="$code" -C "$code" rev-parse HEAD)  # the code is owned by root
cd "$code"
for record in "${records[@]}"; do
  "$python" -m svitlo_notifier metrics-merge --record "$record" --into "$dash" \
    --run-id "server-$(basename "$record" .json)" --event server --outcome success --sha "$sha" --ref main
done
# One commit with the latest data, so the branch never grows.
git -C "$dash" checkout -q -b metrics
git -C "$dash" add -A
git -C "$dash" -c user.name="svitlo-server" -c user.email="svitlo-server@users.noreply.github.com" \
  commit -q -m "Dashboard data"
git -C "$dash" -c http.extraHeader="$auth" push -q --force "$remote" metrics
rm -f "${records[@]}"
