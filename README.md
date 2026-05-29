# 💊 ha-medication-reminder

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-config-blue.svg)

Reliable, **data-driven** multi-dose medication reminders for **Home Assistant**,
for pets *and* people in one household. Define a schedule of *who gets what, when*
and you get actionable phone notifications that **nag until marked given**, a
**missed-dose escalation**, and shared *"given or not"* state **synced across every
Home Assistant Companion app**, with logbook accountability for who marked each dose.

No cloud service, no subscription, no external task app. Home Assistant itself
is the sync layer.

## Why

To-do lists and calendar reminders tell you *what* to do, but they don't track
*whether a specific dose was actually given*, don't nag, and don't sync that
"done" state across the people sharing the responsibility. For something as
important as medication, especially time-sensitive meds where a missed dose
matters, you want a reminder that keeps reminding until acknowledged, a clear
shared record of each dose, and an escalation if one is missed.

## Features

- 🗓️ **Data-driven schedule:** one list defines every dose (patient, time, medications, and optionally who to notify). Add a patient or dose by editing the list.
- 👨‍👩‍👧 **Multiple patients:** mix pets and people. Each reminder names the patient and can route to a specific person.
- 🔔 **Actionable reminders:** push notification with a one-tap "✅ Mark given" button.
- 🔁 **Nags until given:** re-reminds every 15 min within a configurable window.
- 👥 **Household-synced state:** mark a dose given on any phone (or the dashboard) and everyone's app updates instantly. The logbook records who did it.
- ⚠️ **Missed-dose escalation:** if a dose isn't given by its window-end, a time-sensitive push goes out plus an optional spoken TTS backstop.
- ♻️ **Restart-proof:** re-evaluates on a timer instead of a fragile long-lived loop, so an HA restart never drops a pending reminder.
- 🧩 **Drop-in package:** ships as a single Home Assistant package file.

## How it works

- A single `doses:` list is your schedule. Each entry has `id`, `patient`, `time`, `meds`, and optional `notify`.
- One `input_boolean.med_<id>` per dose holds *"given today"*. A daily reset clears them all automatically.
- A `time_pattern` automation checks every 15 min and, per dose, sends a reminder while it's within the nag window and not given, then escalates once at the window-end.
- Tapping **Mark given** (from any phone) turns that dose on and clears its notifications everywhere. Because the state lives in HA, every Companion app reflects it immediately.

## The schedule

Edit the `doses:` list in `medication_reminder.yaml`:

```yaml
doses:
  - { id: buddy_6am,  patient: "Buddy", time: "06:00", meds: "Medication A, Medication B, and Medication C" }
  - { id: buddy_2pm,  patient: "Buddy", time: "14:00", meds: "Medication A and Medication C" }
  - { id: buddy_6pm,  patient: "Buddy", time: "18:00", meds: "Medication B" }
  - { id: buddy_10pm, patient: "Buddy", time: "22:00", meds: "Medication A and Medication C" }
  # A second patient (a person), routed to their own phone:
  - { id: mom_8am,    patient: "Mom",   time: "08:00", meds: "Lisinopril", notify: "mobile_app_mom" }
```

| Field | Meaning |
|-------|---------|
| `id` | Unique key. Must match an `input_boolean.med_<id>` |
| `patient` | Who it's for (pet or person), spoken/shown in the reminder |
| `time` | 24-hour `HH:MM`. Keep on `:00/:15/:30/:45` so the first reminder lands on time |
| `meds` | Free text, read out in the reminder |
| `notify` | *(optional)* a specific notify service for this dose. Omit to use the `caretakers` group |

## Adding a dose or patient

Two small edits, both in `medication_reminder.yaml`:

1. Add an entry to the `doses:` list (above).
2. Declare a matching helper: `input_boolean.med_<id>`.

The reset automation, the dashboard auto-entities card, and the reminder logic all pick it up automatically. No other changes.

## Installation

### Option A: Package (recommended)

1. Copy [`medication_reminder.yaml`](medication_reminder.yaml) into a `packages/` folder in your HA config.
2. Enable packages once in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. Edit the `doses:` schedule, declare a matching `input_boolean.med_<id>` per dose, and replace `mobile_app_phone` in the `caretakers` group with your real notify service.
4. Restart Home Assistant.
5. Add the dashboard card from [`lovelace-card.yaml`](lovelace-card.yaml).

### Option B: Manual

If you don't use packages, paste the `input_boolean:` and `notify:` blocks into
`configuration.yaml`, and the three automations into `automations.yaml` (drop the
top-level `automation:` key, keep them as list items). Restart HA.

## Dashboard

The included [`lovelace-card.yaml`](lovelace-card.yaml) uses
[auto-entities](https://github.com/thomasloven/lovelace-auto-entities) (HACS) to
show every `input_boolean.med_*` automatically, so adding a dose makes it appear
with no card edits. A plain `entities` fallback (no HACS) is included in the file.

## Customizing

- **Nag cadence / window:** change `nag_minutes` and the `time_pattern` minutes.
- **Per-patient routing:** give a dose its own `notify:` service.
- **Fixed course** (e.g. a 10-day antibiotic): add a `condition:` gating the reminder automation on a date range.
- **Spoken backstop:** the missed-dose branch includes an optional `tts.speak`. Point it at your speaker/voice satellite or remove it.

## Requirements

- Home Assistant with the **Companion app** (iOS/Android) for actionable notifications.
- *(Optional)* a TTS engine for the spoken missed-dose backstop, and the [auto-entities](https://github.com/thomasloven/lovelace-auto-entities) card for the zero-maintenance dashboard.

## ⚠️ Disclaimer

This is a reminder aid, **not** a medical device and not a substitute for your
own diligence or professional/veterinary guidance. For time-sensitive
medications (e.g. anticonvulsants), confirm dosing schedules with your doctor or
vet. Use at your own risk.

## License

[MIT](LICENSE) © magikh0e
