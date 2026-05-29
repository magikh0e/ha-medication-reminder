# 💊 Medication Reminder (Home Assistant integration)

![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)
![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)
![Status: alpha](https://img.shields.io/badge/status-alpha-red.svg)

A Home Assistant custom integration for tracking medication doses, for pets *and*
people. Add patients and their dose schedule **in the UI**; the integration
auto-creates a switch per dose (on = given today) and resets them daily. Pair it
with the included companion automations for actionable, nagging, missed-dose
reminders synced across every Companion app.

This is the UI-driven sibling of the YAML package at
[ha-medication-reminder](https://github.com/magikh0e/ha-medication-reminder).
Prefer pure YAML? Use that one. Want point-and-click dose management with
auto-created entities? Use this.

> ⚠️ **Alpha software.** This is new and not yet widely tested. Validate it on
> your own Home Assistant before relying on it, and keep a backup reminder method
> until you trust it. It is a reminder aid, **not** a medical device. Confirm
> dosing schedules with your doctor or vet.

## What it does

- 🖱️ **UI configuration:** add a patient, choose who to notify, then add doses (a time + the medications) from Settings. No YAML for the schedule.
- 👥 **Per-patient notify target:** pick the person or group to remind for each patient in the UI (e.g. one dog's reminders to you, another's to a partner).
- 🔀 **Auto-created entities:** each dose becomes a `switch` (on = given today), grouped under a device per patient.
- ♻️ **Daily reset:** every dose flips back to "not given" at 00:01.
- 💾 **Restart-safe:** dose state survives Home Assistant restarts.
- 🔔 **Reminders via companion automations:** the included `companion-automations.yaml` reads the dose switches and sends actionable, nagging, missed-dose notifications (this v0.1 keeps notifications in YAML so you reuse proven logic).

## Why entities + YAML (not all-in-one, yet)

v0.1 deliberately keeps the *notification* logic in battle-tested YAML
automations and lets the integration own the *config UI* and *entities*. That
gives you the big win (no more hand-declared helpers, UI-managed schedule)
without putting medication-critical notification code into brand-new, untested
territory. A future version may move reminders into the integration itself.

## Installation

### 1. Install the integration (HACS custom repository)

1. HACS, top-right menu, **Custom repositories**.
2. Add `https://github.com/magikh0e/ha-medication-reminder-hacs` as an **Integration**.
3. Install **Medication Reminder**, then restart Home Assistant.

(Or copy `custom_components/medication_reminder/` into your HA `config/custom_components/` and restart.)

### 2. Add patients and doses

1. **Settings, Devices & Services, Add Integration, Medication Reminder.**
2. Enter the patient name (e.g. a pet or person) and pick the **notify target** (the person or group to remind). One patient per entry; add the integration again for more patients.
3. On the entry, click **Configure** to **Add a dose** (pick a time, type the medications). Repeat for each dose. **Remove a dose** or **Change notify target** there too.

Each dose appears as `switch.<patient>_<time>` with attributes `patient`,
`dose_time`, `medications`, and `notify_service`.

### 3. Add the companion automations

1. Copy the two automations from [`companion-automations.yaml`](companion-automations.yaml) into your `automations.yaml`.
2. Reload automations.

Each patient's reminders go to the **notify target you chose in the UI** (read
from the switch's `notify_service` attribute). The `default_notify` value in the
automation (`caretakers`) is only a fallback if a switch has no target set; if
you want a fallback group, define it, for example:
```yaml
notify:
  - platform: group
    name: caretakers
    services:
      - service: mobile_app_your_phone
```

They send a reminder when a dose is due and not given, nag every 15 minutes for
45 minutes, then escalate once as a time-sensitive "missed" alert. Tapping
**Mark given** turns the dose's switch on and clears the notification.

### 4. Dashboard (optional)

Any entities card works. Zero-maintenance version with
[auto-entities](https://github.com/thomasloven/lovelace-auto-entities) (HACS):

```yaml
type: custom:auto-entities
card:
  type: entities
  title: 💊 Medication
filter:
  include:
    - entity_id: "switch.*"
      attributes:
        medications: "*"
      secondary_info: last-changed
sort:
  method: friendly_name
```

## How marking works (the contract)

- The integration publishes `switch.*` entities carrying `patient` / `dose_time` / `medications` / `notify_service` attributes.
- The companion reminder automation iterates those switches and routes each reminder to its `notify_service`, so adding a dose or changing the notify target in the UI needs **no** automation edits.
- "Mark given" flips the switch on; the daily reset flips all off at 00:01.

## Roadmap

- Optional in-integration notifications/nagging (so YAML companions become optional).
- Configurable reset time and nag window in the UI.
- A per-patient "all doses given today" sensor.
- HACS default-store submission once validated.

## License

[MIT](LICENSE) © magikh0e
