"""Constants for the Medication Reminder integration."""

import calendar
import re
from datetime import date, timedelta

DOMAIN = "medication_reminder"

# Events fired on the HA bus when a dose is marked given / un-marked.
EVENT_DOSE_GIVEN = f"{DOMAIN}_dose_given"
EVENT_DOSE_UNDONE = f"{DOMAIN}_dose_undone"
EVENT_DOSE_LOGGED = f"{DOMAIN}_dose_logged"  # one as-needed (PRN) dose taken
# Fired when a refill button is pressed; the matching supply restocks to full.
EVENT_SUPPLY_REFILL = f"{DOMAIN}_supply_refill"

# Services.
SERVICE_MARK_GIVEN = "mark_given"  # mark a dose given, optionally at a set time
SERVICE_LOG_DOSE = "log_dose"  # log an as-needed (PRN) dose, optionally at a set time

CONF_PATIENT = "patient"
CONF_PATIENT_TYPE = "patient_type"
CONF_DOSES = "doses"
CONF_TIME = "time"
CONF_MEDS = "meds"
CONF_DAYS = "days"
CONF_NOTIFY = "notify"
CONF_RESET_TIME = "reset_time"
CONF_NAG_MINUTES = "nag_minutes"
CONF_NAG_INTERVAL = "nag_interval"
CONF_TIME_FORMAT = "time_format"

# Per-dose schedule type and its interval / cycle settings.
CONF_SCHEDULE_TYPE = "schedule_type"
CONF_INTERVAL_DAYS = "interval_days"
CONF_ANCHOR_DATE = "anchor_date"
CONF_CYCLE_ON = "cycle_on"
CONF_CYCLE_OFF = "cycle_off"
CONF_MONTH_DAYS = "month_days"

# Over-dose guard for as-needed (PRN) doses: warn when taken too soon or too often.
CONF_MIN_INTERVAL_HOURS = "min_interval_hours"
CONF_MAX_PER_DAY = "max_per_day"
DEFAULT_MIN_INTERVAL_HOURS = 0
DEFAULT_MAX_PER_DAY = 0

# Supply / refill tracking (per medication).
CONF_SUPPLIES = "supplies"
CONF_SUPPLY_MED = "supply_med"
CONF_SUPPLY_UNITS = "supply_units"
CONF_SUPPLY_PER_DOSE = "supply_per_dose"
CONF_SUPPLY_THRESHOLD = "supply_threshold"
CONF_SUPPLY_REFILL_TO = "supply_refill_to"
CONF_SUPPLY_REFILL_ADD = "supply_refill_add"

# Per-medication reference detail (optional), kept separate from the short dose
# name. Keyed by the medication name as it appears in a dose's meds string.
CONF_MEDICATIONS = "medications"
CONF_MED_NAME = "med_name"
CONF_MED_FULL_NAME = "full_name"
CONF_MED_STRENGTH = "strength"
CONF_MED_BRAND = "brand"
CONF_MED_PRESCRIBED_FOR = "prescribed_for"
CONF_MED_DOSAGE = "dosage"

# Weekday codes, indexed by Python datetime.weekday() (Mon=0 .. Sun=6).
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DEFAULT_PATIENT_TYPE = "person"
DEFAULT_DAYS = WEEKDAYS  # every day = daily

# Dose schedule types.
SCHEDULE_WEEKDAYS = "weekdays"  # on chosen days of the week (default)
SCHEDULE_INTERVAL = "interval"  # every N days from an anchor date
SCHEDULE_CYCLE = "cycle"  # X days on / Y days off from an anchor date
SCHEDULE_PRN = "prn"  # as-needed: no schedule, no reminders, log manually when taken
SCHEDULE_MONTHLY = "monthly"  # on chosen day(s) of the month (clamped to last day)
DEFAULT_SCHEDULE_TYPE = SCHEDULE_WEEKDAYS
DEFAULT_INTERVAL_DAYS = 2
DEFAULT_CYCLE_ON = 21
DEFAULT_CYCLE_OFF = 7
DEFAULT_MONTH_DAYS = [1]
DEFAULT_RESET_TIME = "00:01:00"
DEFAULT_NAG_MINUTES = 45
DEFAULT_NAG_INTERVAL = 15
DEFAULT_TIME_FORMAT = "12h"
DEFAULT_SUPPLY_UNITS = 30
DEFAULT_SUPPLY_PER_DOSE = 1
DEFAULT_SUPPLY_THRESHOLD = 10
DEFAULT_SUPPLY_REFILL_TO = 30
DEFAULT_SUPPLY_REFILL_ADD = False

# Icon for the patient-level "all doses given" sensor, by patient type.
PATIENT_ICONS = {
    "person": "mdi:account",
    "dog": "mdi:dog",
    "cat": "mdi:cat",
    "bird": "mdi:bird",
    "rabbit": "mdi:rabbit",
    "other": "mdi:paw",
}


def split_medications(meds):
    """Split a dose 'meds' string into individual medication names.

    A single dose can list several meds at once (e.g. "Keppra & Phenobarbital").
    Separators: &, +, a comma, or a slash surrounded by spaces (" / "). A bare
    slash is kept as part of the name, so combo drugs and fractional doses such
    as "Carbimazol 5mg (1/2)", "TMP/SMX", or "5mg/ml" are not split apart.
    """
    if not meds:
        return []
    return [p.strip() for p in re.split(r"[&,+]|\s+/\s+", str(meds)) if p.strip()]


def meds_contains(meds, med_name):
    """True if `med_name` is one of the medications in a dose's meds string."""
    target = (med_name or "").strip().lower()
    if not target:
        return False
    return any(part.lower() == target for part in split_medications(meds))


def _parse_iso_date(value):
    """Parse an ISO 'YYYY-MM-DD' string to a date, or None if unparseable."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _interval_n(data):
    """The every-N-days interval from a schedule mapping (>= 1)."""
    try:
        n = int(data.get(CONF_INTERVAL_DAYS) or DEFAULT_INTERVAL_DAYS)
    except (TypeError, ValueError):
        n = DEFAULT_INTERVAL_DAYS
    return max(n, 1)


def _cycle_days(data):
    """The (on_days, off_days) for an on/off cycle (on >= 1, off >= 0)."""

    def _n(key, default, low):
        try:
            v = data.get(key)
            v = int(v if v is not None else default)
        except (TypeError, ValueError):
            v = default
        return max(v, low)

    return _n(CONF_CYCLE_ON, DEFAULT_CYCLE_ON, 1), _n(
        CONF_CYCLE_OFF, DEFAULT_CYCLE_OFF, 0
    )


def _month_days(data):
    """The chosen days-of-month (each kept to 1..31). Defaults to the 1st."""
    out = []
    for v in data.get(CONF_MONTH_DAYS) or DEFAULT_MONTH_DAYS:
        try:
            d = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= d <= 31:
            out.append(d)
    return out or list(DEFAULT_MONTH_DAYS)


def _last_day_of_month(on_date):
    """How many days are in on_date's month (28..31)."""
    return calendar.monthrange(on_date.year, on_date.month)[1]


def is_due(data, on_date):
    """Whether a dose is scheduled on `on_date` (a datetime.date).

    `data` is any mapping carrying the schedule keys (a dose dict OR a switch's
    attributes): `schedule_type`, `days`, `interval_days`, `anchor_date`.
    Missing `schedule_type` defaults to the day-of-week behaviour, so existing
    doses keep working unchanged.
    """
    stype = data.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
    if stype == SCHEDULE_PRN:
        # As-needed: never on a schedule, so it is never "due" and never nags.
        # Doses are still logged manually (which decrements supply).
        return False
    if stype == SCHEDULE_INTERVAL:
        n = _interval_n(data)
        anchor = _parse_iso_date(data.get(CONF_ANCHOR_DATE))
        if anchor is None:
            # No anchor: fall back to a fixed reference so it stays deterministic.
            return on_date.toordinal() % n == 0
        if on_date < anchor:
            return False
        return (on_date - anchor).days % n == 0
    if stype == SCHEDULE_CYCLE:
        on_days, off_days = _cycle_days(data)
        period = on_days + off_days
        anchor = _parse_iso_date(data.get(CONF_ANCHOR_DATE))
        if anchor is None:
            return on_date.toordinal() % period < on_days
        if on_date < anchor:
            return False
        return (on_date - anchor).days % period < on_days
    if stype == SCHEDULE_MONTHLY:
        last = _last_day_of_month(on_date)
        # Clamp each chosen day to the month's last day, so a dose set for the
        # 31st still fires in shorter months instead of being skipped.
        due = {min(d, last) for d in _month_days(data)}
        return on_date.day in due
    days = data.get(CONF_DAYS) or WEEKDAYS
    return WEEKDAYS[on_date.weekday()] in days


def doses_per_week(data):
    """Average times per week a dose fires, for the run-out estimate."""
    stype = data.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
    if stype == SCHEDULE_PRN:
        # No schedule, so no predictable weekly cadence to base a run-out on.
        return 0.0
    if stype == SCHEDULE_INTERVAL:
        return 7.0 / _interval_n(data)
    if stype == SCHEDULE_CYCLE:
        on_days, off_days = _cycle_days(data)
        return 7.0 * on_days / (on_days + off_days)
    if stype == SCHEDULE_MONTHLY:
        # len(days) doses per month, averaged over a 12-month / 52-week year.
        return len(_month_days(data)) * 12.0 / 52.0
    days = data.get(CONF_DAYS) or WEEKDAYS
    return float(len(days))


def dose_min_interval_hours(data):
    """The minimum hours between as-needed doses (0 means no limit)."""
    try:
        return max(float(data.get(CONF_MIN_INTERVAL_HOURS) or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def dose_max_per_day(data):
    """The maximum as-needed doses allowed per day (0 means no limit)."""
    try:
        return max(int(data.get(CONF_MAX_PER_DAY) or 0), 0)
    except (TypeError, ValueError):
        return 0


def next_dose_allowed(last_taken, min_interval_hours):
    """When another dose is allowed after `last_taken`, or None.

    None when there is no minimum interval or no recorded last dose.
    """
    if not last_taken or not min_interval_hours:
        return None
    return last_taken + timedelta(hours=min_interval_hours)


def dose_too_soon(last_taken, min_interval_hours, now):
    """Whether taking another dose at `now` is inside the minimum interval."""
    allowed = next_dose_allowed(last_taken, min_interval_hours)
    return bool(allowed and now < allowed)


def dose_over_cap(doses_today, max_per_day):
    """Whether the daily cap has already been reached."""
    return bool(max_per_day and doses_today >= max_per_day)


def medication_summary_line(med):
    """A single human-readable line for a current-medications entry.

    `med` is one dict from current_medications(). Includes only the fields that
    are filled, e.g. "Ibuprofen (Advil) 200mg, for pain, 1 tablet as needed".
    """
    name = med.get("full_name") or med.get("name") or ""
    if med.get("brand"):
        name = f"{name} ({med['brand']})"
    if med.get("strength"):
        name = f"{name} {med['strength']}"
    parts = [name]
    if med.get("prescribed_for"):
        parts.append(f"for {med['prescribed_for']}")
    if med.get("dosage"):
        parts.append(med["dosage"])
    return ", ".join(parts)


def current_medications(doses, details):
    """Every distinct medication across `doses`, enriched with detail records.

    `doses` is the list of dose dicts; `details` is the per-medication detail
    list (each a mapping with `med_name` plus optional fields). Returns a list
    of dicts (name, full_name, strength, brand, prescribed_for, dosage), one per
    medication the patient actually takes, sorted by name.
    """
    by_name = {}
    for d in details or []:
        name = str(d.get(CONF_MED_NAME, "")).strip()
        if name:
            by_name[name.lower()] = d
    seen = {}
    for dose in doses or []:
        for med in split_medications(dose.get(CONF_MEDS)):
            key = med.lower()
            if key in seen:
                continue
            det = by_name.get(key, {})
            seen[key] = {
                "name": med,
                "full_name": str(det.get(CONF_MED_FULL_NAME) or "").strip(),
                "strength": str(det.get(CONF_MED_STRENGTH) or "").strip(),
                "brand": str(det.get(CONF_MED_BRAND) or "").strip(),
                "prescribed_for": str(det.get(CONF_MED_PRESCRIBED_FOR) or "").strip(),
                "dosage": str(det.get(CONF_MED_DOSAGE) or "").strip(),
            }
    return [seen[k] for k in sorted(seen)]
