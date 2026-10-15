# Changelog

Releases from **v0.3.7** on are published as [GitHub Releases](https://github.com/tanykozel/Svitlocheckextender/releases).

The versions below were released before the history cleanup of 14.10.2026 (personal data removed from old commits,
spec decision Q3). Their GitHub Releases pointed to commits that no longer exist in the history, so they were removed
and their notes are kept here, linked to the matching commits on `main`.

## v0.3.6: security review fixes, subscriber funnel
14.10.2026 · commit [`d2a6f70`](https://github.com/tanykozel/Svitlocheckextender/commit/d2a6f70f89a4554d28958b12410b62f562679e94) · PR #6

**Security**
- 🔒 Real personal data removed from the public test files (replaced with fake values)
- 🔒 Labels in public logs now need the secret key to compute (they could be reversed before)
- 🔒 Only the 3 newest encrypted state copies are kept, so /stop erases a person within ~30 minutes
- 🔒 Dependencies locked by checksum; GitHub actions pinned to exact commits; dashboard chart library integrity-checked
- 📋 Full review in the spec, section 5a

**Dashboard**
- 👥 New funnel: "Subscribed (address chosen)" vs "Started the bot, no address yet", with conversion share

## v0.3.5: reachable subscribers, reply-time SLA, Releases last
14.10.2026 · commit [`0fbeb65`](https://github.com/tanykozel/Svitlocheckextender/commit/0fbeb6522b76f0a0cd17b31284239065eee1b620) · PRs #4, #5

- 👥 Subscribers on the dashboard = people the current bot (@Svitlo_Lyusia_zt_bot) can reach; others are shown as "haven't pressed Start yet"
- ⏱️ Reply time (SLA): how long messages wait for an answer — share within 5 min, median, p95, longest wait, queue at run start — with a recommendation when the target is missed
- 📋 "Releases & deploys" moved to the end of the dashboard
- 🐞 Fixed: a storage-format change no longer appears as 13 fake schedule changes
- 🎨 Four new Люся avatars (night, winter, powerbank, heart) and the correct bot name in the docs

## v0.3.4: hotfix, keep subscriptions after the bot switch
13.10.2026 · commit [`c5ad6d4`](https://github.com/tanykozel/Svitlocheckextender/commit/c5ad6d486c2c0834a6b41127b4574895df1b885a) · PR #3

- 🛡️ Switching to the new bot no longer removes subscriptions: people who haven't pressed Start in the new bot yet keep their address and start getting alerts as soon as they press Start. Only people who blocked the bot or deleted their account are unsubscribed.

## v0.3.3: Releases & deploys dashboard, /setting command, Release workflow
13.10.2026 · commit [`bc4bcf3`](https://github.com/tanykozel/Svitlocheckextender/commit/bc4bcf3588f7c8cad659b1be61fee94795d512a5) · PRs #1, #2

- 📊 Dashboard → new "Releases & deploys" block: live version, first-run check, deploys per week, change failure rate and time to restore (DORA metrics), plus a dashed line on the charts wherever a new version went live
- ⚙️ Bot: «Коли попереджати» now uses /setting, so Telegram's own Settings option in the bot profile is no longer taken over (/settings still works)
- 🚀 New Release workflow: a version is published in one step from main

## v0.3.2: dashboard, warning time, «Світло Люся»
13.10.2026 · commit [`5a41bf4`](https://github.com/tanykozel/Svitlocheckextender/commit/5a41bf46fb3573ff10077a80a7336bfb476efc0c)

- 📊 Owner dashboard: subscribers, system health with "what to do" hints, request types, gaps between runs
- ⏱️ Context: how often the schedule changes and how much warning each change gives
- 💡 The persona is now «Світло Люся» everywhere (bot, docs, demo video)
- 🔀 main is now production: one branch per change, pull requests, release tags
