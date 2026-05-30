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

![Medication Reminder dashboard](https://raw.githubusercontent.com/magikh0e/ha-medication-reminder-hacs/main/dashboard.png)

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
2. Enter the patient name (e.g. a pet or person), pick the **patient type** (Person / Dog / Cat / ..., which sets the icon), and the **notify target** (the person or group to remind). One patient per entry; add the integration again for more patients.
3. On the entry, click **Configure** to **Add a dose** (pick a time, type the medications). Repeat for each dose. **Remove a dose** or open **Reminder settings** (type, notify target, reset time, nag window/interval) there too.

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

### Status panel (red/green, glanceable)

A simple "all OK / attention needed" panel for the top of a dashboard, driven by
the `needs_attention` sensors. Green when nothing is overdue, red (with who and
what) when something needs investigating. Native card, no HACS needed:

![Attention needed state](dashboard-attention-needed.png)

```yaml
type: markdown
content: |-
  {% set s = states.binary_sensor | selectattr('entity_id','search','_needs_attention') | list %}
  {% set red = s | selectattr('state','eq','on') | list %}
  {% if red | length == 0 %}
  # 🟢 All OK
  {% else %}
  # 🔴 Attention needed
  {% for p in red %}
  - **{{ p.attributes.patient }}**: {{ p.attributes.overdue | join(', ') }}
  {% endfor %}
  {% endif %}
```

Because `binary_sensor.<patient>_needs_attention` is a standard `problem` entity,
you can also drive a light, siren, pager, or notification straight off it.

**Make the panel flash when attention is needed** (needs the HACS
[card-mod](https://github.com/thomasloven/lovelace-card-mod) card). Add this to
the markdown card above:

```yaml
card_mod:
  style: |
    ha-card {
      {% if (states.binary_sensor | selectattr('entity_id','search','_needs_attention') | selectattr('state','eq','on') | list | length) > 0 %}
      animation: mr-flash 1.2s ease-in-out infinite;
      {% endif %}
    }
    @keyframes mr-flash {
      0%, 100% { background-color: var(--card-background-color); }
      50% { background-color: rgba(244, 67, 54, 0.55); }
    }
```

For care settings, a **physical** flash is even better: trigger a lamp or siren
off the `needs_attention` sensor so the alert is visible from across the room.

## How marking works (the contract)

- The integration publishes `switch.*` entities carrying `patient` / `patient_type` / `dose_time` / `medications` / `notify_service` attributes. Per patient it also publishes two binary sensors:
  - `binary_sensor.<patient>_all_doses_given` (patient-type icon) - on when all of that patient's doses are given today, with `total` / `given` / `remaining` / `pending` attributes.
  - `binary_sensor.<patient>_needs_attention` (device class `problem`) - **red when a dose is overdue** (past its time by the nag window and still not given), green when all is well. It re-evaluates on a 60-second timer so it trips on elapsed time alone, and fails safe toward "problem". Attributes: `overdue` / `overdue_count`.
- The companion reminder automation iterates those switches and routes each reminder to its `notify_service` / `nag_minutes` / `nag_interval`, so adding a dose or changing a patient's settings in the UI needs **no** automation edits.
- "Mark given" flips the switch on; the daily reset flips all off at the configured reset time.

## Settings (per patient)

Each patient has its own **Configure, Reminder settings** with:

- **Notify target** - who gets that patient's reminders.
- **Time format** - 12-hour (`2:00 PM`) or 24-hour (`14:00`) in the dose entity names (default 12-hour).
- **Daily reset time** - when the day's doses reset to "not given" (default 00:01).
- **Nag window** - how long to keep reminding after a dose time (default 45 min).
- **Re-nag interval** - how often to re-remind within that window (default 15 min).

The reset time is applied by the integration; the nag window/interval are exposed
as switch attributes that the companion automations read.

## Roadmap

- Optional in-integration notifications/nagging (so YAML companions become optional).
- HACS default-store submission once validated.

## Acknowledgements

The red/green "all OK / attention needed" status panel, the flashing alert, and
the aggregate-status idea were suggested by Home Assistant Community user
**IOT7712**. Thanks for the thoughtful feature requests, especially the focus on
a reliable, glanceable, fail-safe indicator for care settings.

## License

[MIT](LICENSE) © magikh0e
