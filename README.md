# 💊 ha-medication-reminder

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-config-blue.svg)

Reliable, multi-dose medication reminders for **Home Assistant** — for a pet or
a family member. Actionable phone notifications that **nag until marked given**,
a **missed-dose escalation**, and shared *"given or not"* state **synced across
every Home Assistant Companion app**, so anyone in the household can mark a dose
given and everyone sees it — with logbook accountability for who did it.

No cloud service, no subscription, no external task app. Home Assistant itself
is the sync layer.

## Why

To-do lists and calendar reminders tell you *what* to do, but they don't track
*whether a specific dose was actually given*, don't nag, and don't sync that
"done" state across the people sharing the responsibility. For something as
important as medication — especially time-sensitive meds where a missed dose
matters — you want:

- a reminder that keeps reminding until the dose is acknowledged,
- a clear shared record of whether each dose was given today,
- an escalation if a dose is missed entirely.

That's what this does.

## Features

- 🔔 **Actionable reminders** — push notification with a one-tap "✅ Mark given" button.
- 🔁 **Nags until given** — re-reminds every 15 min within a configurable window.
- 👥 **Household-synced state** — mark a dose given on any phone (or the dashboard); everyone's app updates instantly. The logbook records who marked it.
- ⚠️ **Missed-dose escalation** — if a dose isn't given by its window-end, a time-sensitive push goes to everyone plus an optional spoken TTS backstop.
- 💊 **Per-dose medication names** — each reminder states exactly which meds to give for that dose.
- ♻️ **Restart-proof** — the reminder re-evaluates on a timer instead of running a fragile long-lived loop, so an HA restart never drops a pending reminder.
- 🧩 **Drop-in package** — ships as a single Home Assistant package file.

## Example schedule

The included example uses four doses a day, each a different combination of
medications (generic names — replace with your own):

| Time | Medications |
|------|-------------|
| 6:00 AM | Medication A, B, C |
| 2:00 PM | Medication A, C |
| 6:00 PM | Medication B |
| 10:00 PM | Medication A, C |

## How it works

- One `input_boolean` per dose represents *"given today"*. A daily reset clears them at midnight.
- A `time_pattern` automation checks every 15 minutes and sends a reminder for any dose that is past its time, within the nag window, and not yet given.
- Tapping **Mark given** turns that dose's boolean on and clears the notification on all devices. Because the state lives in HA, every Companion app reflects it immediately.
- At each dose's window-end (dose time + nag window), if it's still not given, the missed-dose automation escalates.

## Installation

### Option A — Package (recommended)

1. Copy [`medication_reminder.yaml`](medication_reminder.yaml) into a `packages/` folder in your HA config directory.
2. Enable packages once in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. Edit the file: set your **dose times**, **medication names**, and replace `mobile_app_phone` in the `caretakers` notify group with your phone's real notify service (add more people as desired).
4. Restart Home Assistant.
5. Add the dashboard card from [`lovelace-card.yaml`](lovelace-card.yaml).

### Option B — Manual

If you don't use packages, paste the `input_boolean:` and `notify:` blocks into
your `configuration.yaml`, and the four automations into your `automations.yaml`
(drop the top-level `automation:` key and keep them as list items). Restart HA.

## Customizing

- **Dose times** — edit the `time:` values in the reminder's `doses:` list and the matching `at:` triggers in the missed-dose automation. Keep dose times on `:00/:15/:30/:45` boundaries so the first reminder lands on time, and set each missed-dose time to `dose time + nag_minutes`.
- **Medications per dose** — edit the `meds:` strings (and the `meds_map:` in the missed-dose automation).
- **More / fewer doses** — add or remove an `input_boolean`, a `doses:` entry, a `bool_map:`/`meds_map:` entry, a missed-dose trigger, and a card row.
- **Nag cadence** — change `nag_minutes` and the `time_pattern` minutes.
- **Fixed course** (e.g. a 10-day antibiotic) — add a `condition:` gating the automations on a date range, or an `input_datetime` end date.
- **Spoken backstop** — the missed-dose automation includes an optional `tts.speak`; point it at your speaker/voice satellite or remove it.

## Requirements

- Home Assistant with the **Companion app** (iOS/Android) for actionable notifications.
- A TTS engine if you want the spoken missed-dose backstop (the example uses Home Assistant Cloud).

## ⚠️ Disclaimer

This is a reminder aid, **not** a medical device and not a substitute for your
own diligence or professional/veterinary guidance. For time-sensitive
medications (e.g. anticonvulsants), confirm dosing schedules with your doctor or
vet. Use at your own risk.

## License

[MIT](LICENSE) © magikh0e
