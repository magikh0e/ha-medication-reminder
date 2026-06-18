# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.22.1] - 2026-06-17
### Changed
- Grouped the Configure menu into submenus to keep it short: **Doses** (add / edit / remove), **Supplies** (track / remove), **Medication details** (add / edit / remove), and **Reminder settings**. Each action is one tap deeper, but the top menu is now four items instead of nine.

## [0.22.0] - 2026-06-17
### Added
- Edit medication detail. **Configure** has a new **Edit medication detail** step: pick a medication that already has detail, change anything on a form pre-filled with its current values, and save to update it (no re-typing). Pairs with the existing Add and Remove medication detail steps.

## [0.21.1] - 2026-06-17
### Changed
- Polished the Configure menu: retitled "Manage doses" to "Manage medications" (it also covers supplies, medication detail, and reminder settings), and shortened the supply options to "Track a supply" and "Remove a supply".

## [0.21.0] - 2026-06-16
### Added
- Edit a dose in place. **Configure** has a new **Edit a dose** step: pick a dose, change anything on a form pre-filled with its current values, and save to replace it (no remove-and-re-add, no retyping). Editing only the schedule keeps the same entity and its history; changing the time or medications starts a fresh entity, and the old one is pruned so it does not linger as unavailable. (Requested by GitHub user weswark.)

## [0.20.2] - 2026-06-16
### Fixed
- A dose marked given could revert to "not given" after an ungraceful Home Assistant shutdown (crash, OOM-kill, power loss, hard reboot) shortly after it was marked, a double-dose risk. The give-time was only flushed to disk by Home Assistant's periodic restore dump (about every 15 minutes) and on a graceful stop. It is now written to a dedicated store on every mark, un-mark, and daily reset, so the given state survives ungraceful shutdowns too. Doses already marked given are migrated to the store on upgrade, and the store is removed when a patient is deleted.

## [0.20.1] - 2026-06-16
### Added
- Un-mark alert: an optional companion automation and blueprint (`unmark_alert.yaml`) that notifies caretakers when a dose that was marked given is un-marked (flipped back to not given), so an accidental tap by another caretaker is visible instead of silent. Fires on the `medication_reminder_dose_undone` event; the daily reset does not trigger it.

### Changed
- Medication detail now picks the medication from a dropdown of the ones already used in the patient's doses, instead of a free-text field, so detail can only attach to a real medication and cannot be misspelled into an orphaned duplicate. If a patient has no doses yet, the step explains to add one first.
- Supply tracking likewise picks the medication from a dropdown of the doses, so a tracked supply always matches a dose and decrements, instead of a free-typed name that could silently never decrement and trip the Repairs warning. (Prompted by GitHub issue #5.)

## [0.20.0] - 2026-06-16
### Added
- Per-medication detail. In **Configure** you can now add reference info for a medication, kept separate from the short dose name: a full name, strength (e.g. "5mg"), brand, the condition it was prescribed for, and a dosage summary (e.g. "2 tablets twice a day"). A new `sensor.<patient>_medications` lists every medication the patient takes (gathered from their doses), enriched with that detail; its state is the count of distinct medications, and its `medications` and `summary` attributes give a ready-to-share "current medications" list to hand a vet or doctor. (Suggested by GitHub user VGrol.)

## [0.19.0] - 2026-06-15
### Added
- Over-dose guard for as-needed (PRN) doses. When you add a PRN dose you can set a **minimum number of hours between doses** and a **maximum number of doses per day** (0 for either means no limit). With at least one set, the dose gains a `binary_sensor.<patient>_<med>_dose_guard` (device class `problem`) that turns on when taking another dose right now would be too soon (within the interval since the last log) or would exceed the daily cap. It only warns, never blocks, and exposes `too_soon`, `over_cap`, `next_allowed`, `doses_today`, and `remaining_today` attributes for dashboards and automations. This is the "no less than 4 hours apart" pain-med case. (Idea from community member IOT7712.)

## [0.18.5] - 2026-06-15
### Fixed
- README screenshots render correctly on the HACS info page again. Repository housekeeping moved the images into an `images/` folder; the previous release's README still pointed at the old paths, so this release ships the updated README with absolute image URLs. No change to the integration itself.

## [0.18.4] - 2026-06-15
### Changed
- Renamed the repository from `ha-medication-reminder-hacs` to `ha-medication-reminder` (the HACS default store does not allow "HACS" in repository names). Updated the documentation and issue-tracker URLs, README links and images, and blueprint source URLs. The integration domain (`medication_reminder`) and your existing setup are unchanged; HACS follows the rename automatically.

## [0.18.3] - 2026-06-15
### Changed
- Dropped the alpha label now that the integration has been through real-world user testing. The README and repository description no longer mark it as alpha. The safety guidance stays: it is a reminder aid, not a medical device, so confirm dosing with your doctor or vet.

## [0.18.2] - 2026-06-15
### Added
- Brand icon bundled with the integration (`custom_components/medication_reminder/brand/icon.png` and `icon@2x.png`), so the Medication Reminder logo shows on the HACS card and in Settings, Devices & Services. Home Assistant 2026.3 and later loads brand images directly from the integration, so no entry in the home-assistant/brands repository is needed; on older versions there is no change.

## [0.18.1] - 2026-06-14
### Fixed
- A tracked supply whose medication name contains a slash (combo drugs and fractional doses such as `Carbimazol 5mg (1/2)`, `TMP/SMX`, or `Lisinopril/HCTZ`) no longer warns "no matching dose" and now decrements correctly. Medication strings are split into separate meds only on `&`, `+`, a comma, or a slash with spaces around it; a bare slash is kept as part of the name. (Reported by a community member.)
### Changed
- Dashboards: the schedule overview now lists each patient's timed doses first (sorted by time) and groups as-needed (PRN) doses at the bottom of their block, instead of the as-needed ones floating to the top. Re-copy `lovelace-card.yaml` or `lovelace-card-2col.yaml` to pick this up. (Suggested by a community member.)

## [0.18.0] - 2026-06-10
### Added
- As-needed (PRN) doses now track **how many were taken today**. Each PRN dose gains a `sensor.<patient>_<med>_doses_today` count that increments on every Log dose press (or `log_dose` call) and resets at the patient's daily reset time, restart-safe, so you can answer "how many doses of this have I had today?" at a glance. The bundled dashboards' "As needed (PRN)" card now shows it next to the Log dose button and last-taken time (re-copy the dashboard to pick it up). (Suggested by a community member.)
### Fixed
- Dashboards: the status banner no longer throws a template error when another integration also exposes a `*_needs_attention` sensor (e.g. a plant monitor). The medication banner now only counts sensors that carry a `patient` attribute. Re-copy `lovelace-card.yaml` or `lovelace-card-2col.yaml` to pick this up.

## [0.17.0] - 2026-06-10
### Added
- As-needed (PRN) doses now record **when they were last taken**. Each PRN dose gains a `sensor.<patient>_<med>_last_taken` (device class `timestamp`) that updates every time the dose is logged and survives restarts, so you can see how long it has been since the last one.
- New **`medication_reminder.log_dose` service** to log a PRN dose at a specified time. Target a "Log dose" button and pass an optional `taken_at`; with no time it records "now" (the same as tapping the button). This is the "Specify Time" counterpart for PRN meds, matching `mark_given` for scheduled doses. Logging via the service decrements the supply and updates the "last taken" sensor just like a button tap.
- The bundled dashboards' "As needed (PRN)" card now shows each med's "last taken" time alongside its Log dose button. Re-copy the dashboard to pick this up.
### Notes
- This is the groundwork for a PRN over-dose guard (warn when a med is logged again sooner than a set interval, e.g. a pain med taken no less than 4 hours apart); the warning automation builds on the new "last taken" sensor next.

## [0.16.0] - 2026-06-09
### Added
- New **`medication_reminder.mark_given` service** to record a dose taken at a specified time. Target a dose switch and pass an optional `given_at`; with no time it records "now" (the same as tapping the switch). This is the "Specify Time" counterpart to the one-tap "Take Now", e.g. logging at 9:00 that a dose was actually taken at 8:00. Correcting the time on a dose already marked given updates the timestamp without re-warning or re-decrementing supply, and the early-dose warning now reflects the recorded give-time.
### Changed
- Bundled dashboards: the today-summary lines (overdue, upcoming, and "already given") now lead with the medication and only show the patient name in multi-patient households, so a single-patient setup reads "Macrogol at 21:42" instead of "Bossie Macrogol at 21:42". Re-copy the dashboard to pick this up.

## [0.15.1] - 2026-06-09
### Changed
- As-needed (PRN) display polish: a PRN dose is now named by its medication (e.g. "Ibuprofen (as needed)") instead of a meaningless time, and the schedule-overview no longer shows a placeholder 00:00 for it. Re-copy the bundled dashboard to pick up the schedule-overview change.

## [0.15.0] - 2026-06-09
### Added
- New **monthly (day-of-month)** dose schedule type: a dose fires on one or more chosen days of the month (e.g. the 1st, or the 1st and 15th). A chosen day past a given month's length (the 31st in February) clamps to that month's last day, so a monthly dose is never silently skipped. It works with the next-dose sensor, calendar, supply run-out estimate, and dashboards like the other schedule types.

## [0.14.0] - 2026-06-09
### Added
- New **"As needed (PRN)"** dose schedule type, for medications taken only when needed (pain meds, rescue inhalers, etc.). A PRN dose never reminds, nags, or shows as overdue, and stays off the next-dose sensor and calendar.
- A **"Log dose" button** on each PRN dose. Pressing it records one dose and decrements that medication's tracked supply, with no once-per-day limit, so meds taken several times a day are each counted and refill / run-out tracking stays accurate. (PRN doses have no schedule, so the daily on/off switch does not count them.)
- The bundled dashboards (`lovelace-card.yaml` and `lovelace-card-2col.yaml`) gain an **"As needed (PRN)"** card holding the Log dose buttons, and label PRN meds as "As needed" in the schedule overview.

## [0.13.1] - 2026-06-02
### Added
- Inline hint on the dose "Medications" field, explaining the separators (&, +, /, or a comma) used to track each medication individually.
### Changed
- All entities now use `has_entity_name`. Each entity's name is composed from its patient device (e.g. "Kaupo Needs attention") rather than repeating the patient in the name string. Friendly names display the same as before and existing entity IDs are unchanged; new installs get slightly cleaner entity IDs.
### Documentation
- New "Safety & fail-safes" section in the README summarizing the integration's safety behaviour (fail-safe overdue detection, missed-dose escalation, the early-dose warning, reversible marking, restart-safe state, supply run-out protection, the Repairs misconfiguration check, and off-day alarm suppression), plus a "Fail-safe by design" highlight. No functional change.

## [0.13.0] - 2026-06-02
### Added
- Next-dose sensor per patient (`sensor.<patient>_next_dose`, device class `timestamp`): the time of the soonest upcoming dose, computed from each dose's schedule (any schedule type). Handy for dashboards and "remind me before" automations; its attributes include the medications for that dose.
- Medication calendar per patient (`calendar.<patient>_medication`): a read-only calendar with one event per due dose, which makes the every-N-days and on/off-cycle schedules easy to see laid out over the weeks.
- Downloadable diagnostics for a patient entry (config plus the current state of every entity it created), to make supporting issues easier.
- Repairs warning when a tracked supply's medication matches no dose, so it would never decrement. It appears under Settings, Repairs and clears itself once you fix the spelling or remove the supply.

## [0.12.0] - 2026-06-01
### Added
- On/off cycle schedules (e.g. 21 days on / 7 days off), for cyclic regimens like oral contraceptives or cyclic HRT. When adding a dose, choose schedule type "On/off cycle", set the days on and days off, and a start date; the dose is due through the on-stretch and skipped through the off-stretch, repeating. Exposed on each dose switch as `cycle_on` / `cycle_off`, and honoured by the status sensors, supply run-out estimate, companion automations, and dashboard via the shared `is_due` rule.
- One-tap refill button per tracked supply (`button.<patient>_<med>_refill`). Pressing it restocks that medication to its configured refill amount instead of editing the number by hand. It fires a `medication_reminder_supply_refill` event that the supply number listens for.
- Test suite and CI. A `tests/` directory with pytest unit tests for the schedule logic (day-of-week, every-N-days, on/off cycle, and run-out cadence), plus GitHub Actions workflows running pytest and hassfest on every push and pull request.

## [0.11.2] - 2026-06-01
### Fixed
- Doses marked given before 0.11.1 (which have no stored give-time) no longer drift to the restart time on every reboot. On restore, a given dose with no recorded `given_at` now adopts its last known change time and keeps it, so the dashboard's "Already given at ..." freezes instead of changing each restart. Doses marked given from 0.11.1 onward already keep their exact give-time.

## [0.11.1] - 2026-06-01
### Fixed
- The dashboard's "Already given at ..." time no longer resets after a Home Assistant restart. Each dose now records a `given_at` timestamp when it is marked given and persists it across restarts (the on/off state was already restart-safe; only the displayed give-time was resetting to the startup time). The dashboard reads `given_at`, falling back to `last_changed` for doses that were already given before upgrading.

## [0.11.0] - 2026-06-01
### Added
- Every-N-days dose schedules (e.g. every other day, every third day). When adding a dose you can now choose the schedule type "Every N days" with an interval and a start date; the dose is due on the start date and every N days after. Day-of-week scheduling is still the default, and existing doses are unchanged (they default to the day-of-week behaviour). Each dose switch now also carries `schedule_type`, `interval_days`, `anchor_date`, and a computed `scheduled_today` attribute, and a single `is_due` rule decides "due today" for the status sensors, the supply run-out estimate, the companion automations, and the dashboard. Suggested by a community member.

## [0.10.0] - 2026-06-01
### Added
- Early-dose warning, a soft over-dose guard. The dose switch now fires a `medication_reminder_dose_given` event when a dose is marked given, carrying `patient`, `dose_time`, `medications`, `days`, `notify_service`, `scheduled_today`, and `minutes_early`. The new `med_early_given` companion automation listens for it and notifies the caretaker when a dose is marked given well before its scheduled time (default 30 minutes early; set `early_grace_minutes: 0` to warn on any early marking). It warns rather than blocks, so you keep control, and the warning carries two action buttons (Companion app): "undo" un-marks the dose if it was a mistake, "intended" dismisses. Un-marking a dose (the undo, or a manual toggle-off) now restores that dose's supply count via a new `medication_reminder_dose_undone` event; the daily reset does not restore, since a given dose was actually taken. Idea from community member IOT7712.
- Importable blueprints for every companion automation (reminders and missed-dose escalation, mark given from notification, low-supply refill, early-dose warning), under `blueprints/automation/medication_reminder/`. Add them with a one-click import and update them by re-importing, instead of copy-pasting YAML. Copying `companion-automations.yaml` still works as the alternative.

## [0.9.0] - 2026-05-31
### Added
- Supply and refill tracking, per medication. In Configure you can now "Track a medication supply" with the units on hand, units consumed per dose, a low-stock threshold, and a refill amount. Each tracked medication gets a settable `number` entity that decrements when a dose containing that medication is marked given today (once per dose per day, restart-safe, and never on the daily reset). It exposes `doses_left` and an `est_runout_date` computed from the schedule. A per-patient "supplies low" `binary_sensor` (device class `problem`) goes red when any supply reaches its threshold, and a new companion automation sends a refill reminder. Idea from Home Assistant Community member Tadies, who built it on a dashboard with counter helpers.

## [0.8.0] - 2026-05-30
### Added
- Day-of-week scheduling per dose. When adding a dose you can pick which days it applies to (Monday through Sunday); defaults to every day. A dose is only reminded, counted as pending, or flagged overdue on its scheduled days. Exposed as a `days` attribute, which the companion automations and the status sensors respect. Existing doses default to every day, so nothing changes for them.

## [0.7.0] - 2026-05-30
### Added
- Time format option (12-hour or 24-hour) in Reminder settings. Dose entity names show the time in the chosen format (e.g. `2:00 PM` or `14:00`). Exposed as a `time_format` attribute. Defaults to 12-hour, so existing setups are unchanged.

## [0.6.0] - 2026-05-30
### Added
- Per-patient "needs attention" sensor (`binary_sensor`, device class `problem`): red when a dose is overdue (past its time by the nag window and still not given), green when all is well. It re-evaluates on a 60-second timer so it trips on elapsed time alone, with no interaction, and fails safe toward "problem" rather than a false "all clear". Drives a simple red/green status panel and any light, siren, or notification you wire to it.

## [0.5.0] - 2026-05-30
### Added
- Patient type (Person, Dog, Cat, Bird, Rabbit, Other), chosen in the config flow and editable in Reminder settings. It sets the icon on the patient's "all doses given" sensor and is exposed as a `patient_type` attribute. Dose switches keep the pill icon.

## [0.4.0] - 2026-05-30
### Added
- Per-patient `binary_sensor` that is on when all of that patient's doses are given today, with `total`, `given`, `remaining`, and `pending` attributes. Useful for automations and dashboards.

## [0.3.0] - 2026-05-30
### Added
- Per-patient reminder settings in the UI (Configure, Reminder settings): daily reset time, nag window, and re-nag interval. These are exposed as switch attributes (`nag_minutes`, `nag_interval`) that the companion automations read, so changes take effect with no YAML edits.

## [0.2.2] - 2026-05-30
### Changed
- Dose entity names now show the medications inline, e.g. `Buddy 2:00 PM (Trazodone)`, so the toggle list matches the summary card.

## [0.2.1] - 2026-05-30
### Changed
- Dose entity names now display the time in 12-hour format (e.g. `2:00 PM` instead of `14:00`).

## [0.2.0] - 2026-05-29
### Added
- Per-patient notify target, selectable in the config flow and editable via the options flow.
- `notify_service` attribute on each dose switch, so the companion automations route reminders to the right person or group per patient.

## [0.1.0] - 2026-05-29
### Added
- Initial alpha release.
- UI config flow: add a patient, then add or remove doses (time + medications).
- One switch per dose (on = given today), grouped under a device per patient.
- Daily reset of all doses at 00:01; given/not-given state survives restarts.
- Companion automations for actionable, nagging, missed-dose reminders.
- Bundled dashboard card (12-hour summary + auto-entities).
