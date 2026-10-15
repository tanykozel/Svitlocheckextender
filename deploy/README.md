# Always-on server (v0.4)

The bot runs non-stop on a small Linux server instead of short GitHub Actions runs:

| | GitHub Actions (before) | Server (now) |
|---|---|---|
| Reply to a message | when the next run starts: 10–50 min | ~1 second |
| Alerts | when the next run starts, sometimes late | checked every minute, never later than the chosen warning time |
| Cost | free | ~€4–5 a month |

What runs on the server:
- `svitlo-bot`: the bot. Restarts by itself if it stops, and starts again after a reboot.
- `svitlo-update` (every 5 min): deploys the latest `main`, so a merged PR goes live within ~5 min.
- `svitlo-metrics` (every 5 min): publishes the dashboard numbers. These are numbers only, with no personal data.
- `svitlo-backup` (daily at 03:30): keeps an encrypted copy of the bot state for 3 days.

Security set up by `setup.sh`:
- Firewall: only SSH can come in.
- SSH: keys only, no passwords.
- Automatic security updates, with a reboot at 04:30 if one needs it.
- The bot runs as its own user, and can only write its own folder.
- Secrets live in root-only files under `/etc/svitlo`.

## What you need

1. **A server:** for example Hetzner Cloud.
   - Plan: the smallest **shared x86 (Intel/AMD)** plan. Not Arm ("CAX"): the pinned packages are x86 builds.
   - Location: an EU one (Germany or Finland).
   - Image: **Ubuntu 24.04**.
2. **An SSH key**, added when you create the server. On Windows, open PowerShell:
   ```
   ssh-keygen -t ed25519
   type $env:USERPROFILE\.ssh\id_ed25519.pub
   ```
   Paste the printed line into "SSH keys" when you create the server.
3. **A GitHub fine-grained token:** GitHub → Settings → Developer settings → Fine-grained tokens.
   - Repository: only this one.
   - Permissions: **Contents: Read and write** and **Actions: Read and write**.
   - Expiry: 1 year.
4. **Optional:** a free check at [healthchecks.io](https://healthchecks.io). Period 5 min, grace 5 min. It emails you if the bot stops.

## Set up (about 30 minutes)

1. **Log in** from PowerShell: `ssh root@<server IP>`
2. **Install everything:**
   ```
   curl -fsSL https://raw.githubusercontent.com/tanykozel/Svitlocheckextender/main/deploy/setup.sh | bash
   ```
3. **Fill in the secrets.** Type them on the server only, never in a chat:
   ```
   nano /etc/svitlo/bot.env      # TELEGRAM_BOT_TOKEN, SVITLO_STATE_KEY (same as the GitHub secrets), health URL
   nano /etc/svitlo/github.env   # GITHUB_TOKEN from step 3 above
   ```
   In nano: Ctrl+O, then Enter to save, then Ctrl+X to exit.

## Switch over (about 10 minutes, a few minutes without alerts)

1. **Stop the GitHub bot.** GitHub → Settings → Secrets and variables → Actions → **Variables** → New variable: `BOT_HOST` = `server`.
   Then wait until no "Outage alerts" run is still running (Actions tab).
2. **Export the subscribers.** Actions → **Export bot state** → Run workflow. The file stays encrypted.
3. **On the server:**
   ```
   bash /opt/svitlo/deploy/import-state.sh
   systemctl enable --now svitlo-bot
   journalctl -fu svitlo-bot          # Ctrl+C to stop watching
   ```
   You should see `serving @Svitlo_Lyusia_zt_bot`.
4. **Test:** send `/status` to the bot. The answer should arrive within seconds.
5. **Dashboard:** within ~15 min, "Bot status" shows **Running** again, with runs every 10 min.

## Everyday

| Task | Command (on the server) |
|---|---|
| Is it running? | `systemctl status svitlo-bot` |
| Live log | `journalctl -fu svitlo-bot` |
| Last deploys | `journalctl -u svitlo-update -n 20` |
| Restart | `systemctl restart svitlo-bot` |

## Going back to GitHub (rollback)

1. On the server: `systemctl disable --now svitlo-bot`.
2. On GitHub: delete the `BOT_HOST` variable.

Note: subscription changes made while the server ran are not in GitHub's copy. People who subscribed in that time would need to send /start again.
