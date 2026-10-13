# Product spec: advance outage alerts for Svitlochek users

| | |
|---|---|
| Status | v0.1 implemented (MVP); live API not yet verified from a Ukrainian network |
| Owner | Tetiana Kozel |
| Last updated | 2026-10-13 |

## 1. Problem statement

Households in Zhytomyr oblast check the official **Svitlochek** app (Zhytomyroblenergo) to see
their hourly outage schedule. The app shows the schedule **only when opened**. It does not notify
users that power will go off soon or come back, and it does not tell them when the schedule changes.
People therefore miss the window to charge devices, finish a wash or start cooking, and they keep
re-opening the app to check for changes.

**Hypothesis:** if users get a push notification ~30 minutes before each scheduled change, and
whenever the schedule is published or changed, they will stop polling the app manually and
will be ready for each outage more often.

## 2. Users

| Persona | Need |
|---|---|
| Household member (primary) | "Tell me 30 min before light goes off or comes back, without me opening an app." |
| Remote family member | Gets alerts for parents' address without living there (multiple labels/instances). |
| Small business / home office | Plans work around outages; cares about schedule **changes** most. |

## 3. Scope

**In scope (MVP):** one address (queue) per running instance; push via ntfy and/or Telegram;
alerts for off / possible off / on; "schedule published / changed" alerts; address-to-queue lookup;
no ZTOE account.

**Out of scope (not now):** a mobile app UI; multi-user sign-up; emergency (unscheduled) outage
detection; other oblenergos; payments or meter readings.

## 4. User stories and acceptance criteria

**US-1 Find my queue**
As a household member, I want to find my черга/підчерга by address so that alerts match my house.
- *Given* I run `lookup` and drill down district → city → street, *when* I list addresses,
  *then* each house shows its queue as `черга X.Y`.

**US-2 Warning before power goes off** (Must)
As a household member, I want a push N minutes before a scheduled outage so that I can prepare.
- *Given* lead = 30 min and an outage at 08:00, *when* the check runs at any time 07:30–07:59,
  *then* one push says power goes off at 08:00 and until when.
- *Given* the alert was already sent, *when* the check runs again, *then* no duplicate is sent.
- *Given* the check runs at 07:00 or after 08:00, *then* no alert for that outage is sent.

**US-3 Warning before power comes back** (Must)
- *Given* an outage ends at 12:00, *when* the check runs 11:30–11:59, *then* one push says power returns at 12:00.

**US-4 Possible outages** (Should)
- *Given* a yellow ("можливе") slot, *then* a 🟡 alert is sent, unless the user set `--no-possible`.
- *Given* outage → possible → available, *then* no "possible off" alert is sent mid-outage.

**US-5 Schedule published or changed** (Should)
- *Given* the first run, *then* the current schedule is stored as a baseline and no alert is sent.
- *Given* tomorrow's schedule appears, *then* one "📅 Графік на DD.MM опубліковано" push lists its outage windows.
- *Given* an existing day's schedule changes, *then* one "змінено" push lists the new windows,
  and upcoming off/on alerts follow the new times.

**US-6 Choose channel** (Must)
- *Given* `NTFY_TOPIC` is set, *then* alerts arrive as phone push via the ntfy app, with no account needed.
- *Given* Telegram bot credentials are set, *then* alerts also arrive in Telegram.
- *Given* neither is set, *then* the run stops with a clear configuration error.

## 5. Non-functional requirements

- Timezone: all times are Europe/Kyiv, regardless of where the job runs.
- Runs unattended every 5–10 min; one run takes < 5 s; standard library only.
- Secrets (bot token, topic) live in env vars / repository secrets, never in code or logs.
- Polite to ZTOE: 1 request per run, identifying User-Agent.

## 6. Success metrics

- ≥ 95% of scheduled transitions produce an alert at least 15 minutes before the change.
- 0 duplicate alerts per transition.
- Qualitative: the user no longer opens Svitlochek just to check for changes.

## 7. Risks, assumptions, open questions

| # | Item | Type | Mitigation / next step |
|---|---|---|---|
| R1 | ZTOE endpoints are undocumented and may change | Risk | Isolated in `api.py`; contract taken from SvitloYE (MIT). Ask ZTOE about an official feed. |
| R2 | Live API not yet tested: the build environment cannot reach ztoe.com.ua | Risk | First run `status` from a Ukrainian network and compare with Svitlochek. |
| R3 | ztoe.com.ua may block non-Ukrainian IPs (GitHub Actions) | Risk | Run on a home PC / Raspberry Pi / UA VPS. |
| R4 | GitHub scheduled runs can be delayed | Risk | Lead ≥ 30 min; state ensures late runs still alert once. |
| R5 | Emergency outages are not in the schedule | Limitation | Out of scope. A future option is a "power sensor" approach like SvitloBot. |
| A1 | Slot colours: red = outage, yellow = possible, white/green = power | Assumption | Verify against the live API (R2). |
| Q1 | Is bezsvitla.com.ua a better or extra source? | Open | Third-party aggregator; could not be reviewed from the build environment. Keep ZTOE as the primary source. |
| Q2 | Should one instance serve several addresses? | Open | Next iteration if needed. |
