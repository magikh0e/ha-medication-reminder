# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
