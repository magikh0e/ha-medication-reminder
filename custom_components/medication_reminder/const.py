"""Constants for the Medication Reminder integration."""

import calendar
import re
from datetime import date, timedelta

DOMAIN = "medication_reminder"

# Events fired on the HA bus when a dose is marked given / un-marked.
EVENT_DOSE_GIVEN = f"{DOMAIN}_dose_given"
EVENT_DOSE_UNDONE = f"{DOMAIN}_dose_undone"
EVENT_DOSE_LOGGED = f"{DOMAIN}_dose_logged"  # one as-needed (PRN) dose taken
# Fired when a dose is skipped for the day (not taken, supply untouched).
EVENT_DOSE_SKIPPED = f"{DOMAIN}_dose_skipped"
# Fired when a dose reminder is snoozed ("remind me later").
EVENT_DOSE_SNOOZED = f"{DOMAIN}_dose_snoozed"
# Fired when a refill button is pressed; the matching supply restocks to full.
EVENT_SUPPLY_REFILL = f"{DOMAIN}_supply_refill"

# Services.
SERVICE_MARK_GIVEN = "mark_given"  # mark a dose given, optionally at a set time
SERVICE_LOG_DOSE = "log_dose"  # log an as-needed (PRN) dose, optionally at a set time
SERVICE_SKIP_TODAY = "skip_today"  # skip a dose for the day (not taken, no decrement)
SERVICE_SNOOZE = "snooze"  # defer a dose's reminder for a delay ("remind me later")

CONF_PATIENT = "patient"
CONF_PATIENT_TYPE = "patient_type"
CONF_DOSES = "doses"
CONF_TIME = "time"
# Add-dose form only: optional extra times to create the same dose at, in one go
# (not stored on a dose; each time becomes its own dose).
CONF_EXTRA_TIMES = "additional_times"
CONF_MEDS = "meds"
CONF_DAYS = "days"
CONF_NOTIFY = "notify"
CONF_RESET_TIME = "reset_time"
CONF_NAG_MINUTES = "nag_minutes"
CONF_NAG_INTERVAL = "nag_interval"
CONF_TIME_FORMAT = "time_format"
CONF_SKIP_BUTTONS = "skip_buttons"  # opt-in per-med skip buttons for grouped doses
CONF_PLAN_VIEW = (
    "plan_view"  # opt-in per-patient pill-box plan (offset number + sensor)
)
CONF_PAUSE_SWITCHES = (
    "pause_switches"  # opt-in per-dose pause toggle (suspend a med until resumed)
)
CONF_STREAK = "streak"  # opt-in per-patient adherence streak sensor

# Per-dose schedule type and its interval / cycle settings.
CONF_SCHEDULE_TYPE = "schedule_type"
CONF_INTERVAL_DAYS = "interval_days"
CONF_ANCHOR_DATE = "anchor_date"
CONF_END_DATE = "end_date"  # optional stop date: no reminders after it
CONF_CYCLE_ON = "cycle_on"
CONF_CYCLE_OFF = "cycle_off"
CONF_MONTH_DAYS = "month_days"

# Over-dose guard for as-needed (PRN) doses: warn when taken too soon or too often.
CONF_MIN_INTERVAL_HOURS = "min_interval_hours"
CONF_MAX_PER_DAY = "max_per_day"
DEFAULT_MIN_INTERVAL_HOURS = 0
DEFAULT_MAX_PER_DAY = 0

# Optional per-dose consumption override: units this specific dose takes from the
# medication's supply. 0 = use the supply's default "units consumed per dose".
CONF_DOSE_UNITS = "dose_units"
DEFAULT_DOSE_UNITS = 0.0
# Opt-in: ask for the amount actually taken when marking this dose given (for a
# med whose dose varies, e.g. adjusted from a reading). Adds a per-dose amount
# number the mark honours. Off = always decrement the configured amount.
CONF_ASK_UNITS = "ask_units"
DEFAULT_ASK_UNITS = False

# Supply / refill tracking (per medication).
CONF_SUPPLIES = "supplies"
CONF_SUPPLY_MED = "supply_med"
CONF_SUPPLY_UNITS = "supply_units"
CONF_SUPPLY_UNIT = "supply_unit"  # display unit/form (e.g. tablets, drops); "" = none
CONF_SUPPLY_PER_DOSE = "supply_per_dose"
CONF_SUPPLY_THRESHOLD = "supply_threshold"
CONF_SUPPLY_REFILL_TO = "supply_refill_to"
CONF_SUPPLY_REFILL_ADD = "supply_refill_add"
CONF_SUPPLY_COST = "supply_cost"  # cost per unit; 0 = untracked
CONF_SUPPLY_REFILLS = "supply_refills"  # prescription refills remaining; 0 = untracked

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
DEFAULT_SKIP_BUTTONS = False
DEFAULT_PLAN_VIEW = False
DEFAULT_PAUSE_SWITCHES = False
DEFAULT_STREAK = False
DEFAULT_SNOOZE_MINUTES = 30
DEFAULT_SUPPLY_UNITS = 30
DEFAULT_SUPPLY_UNIT = ""  # no unit label by default (bare number)
DEFAULT_SUPPLY_PER_DOSE = 1

# Common medication units/forms offered for a supply (a custom value is allowed).
# Used only as a display unit on the supply and amount entities.
SUPPLY_UNITS = ["tablets", "capsules", "drops", "ml", "bottles", "syringes", "pens"]

# Per-day outcome codes for the adherence streak (see streak_stats / classify_day).
OUTCOME_TAKEN = "taken"  # every dose due that day was given
OUTCOME_SKIPPED = "skipped"  # all due doses handled, but at least one was skipped
OUTCOME_MISSED = "missed"  # a due dose was neither given nor skipped
OUTCOME_NONE = "none"  # no doses were due that day (neutral, does not break a streak)
STREAK_WINDOW_DAYS = 30  # trailing window for the adherence percentage
DEFAULT_SUPPLY_THRESHOLD = 10
DEFAULT_SUPPLY_REFILL_TO = 30
DEFAULT_SUPPLY_REFILL_ADD = False
DEFAULT_SUPPLY_COST = 0.0
DEFAULT_SUPPLY_REFILLS = 0

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


def clamp_snooze_minutes(value, default=DEFAULT_SNOOZE_MINUTES):
    """A valid snooze delay in minutes: a positive int, capped at a day.

    Falls back to ``default`` for a missing or unparseable value, and to 1 for a
    zero/negative one, so a snooze always defers by at least a minute.
    """
    if value is None:
        return default
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(minutes, 1440))


def dose_handled(state, skipped_today):
    """A dose is handled for the day when it is given or skipped for today.

    The status sensors and dashboards treat a skipped dose like a given one, as
    done for the day: not pending, not overdue. Shared so "given or skipped" has
    a single definition.
    """
    return state == "on" or bool(skipped_today)


def classify_day(scheduled, handled):
    """The adherence outcome for a day.

    `scheduled` is the set of dose keys due that day; `handled` maps a handled
    dose key to "given" or "skipped". Returns one of OUTCOME_NONE (nothing due),
    OUTCOME_MISSED (a due dose was neither given nor skipped), OUTCOME_SKIPPED
    (all due doses handled but at least one was skipped), or OUTCOME_TAKEN (all
    due doses given). A partial dose counts as given, since the dose itself was
    taken.
    """
    if not scheduled:
        return OUTCOME_NONE
    any_skipped = False
    for key in scheduled:
        state = handled.get(key)
        if state is None:
            return OUTCOME_MISSED
        if state == "skipped":
            any_skipped = True
    return OUTCOME_SKIPPED if any_skipped else OUTCOME_TAKEN


def streak_stats(outcomes, today, window=STREAK_WINDOW_DAYS):
    """Adherence figures from a {date-ISO: outcome} log of completed days.

    `today` (a date or ISO string) is the in-progress day and is excluded. The
    streak counts consecutive completed days, most recent first, that were taken
    or skipped; a "none" day (nothing due) is neutral and skipped over, while a
    "missed" day or a gap (a date with no record, e.g. Home Assistant was off)
    ends it. Adherence is taken / (taken + skipped + missed) over the trailing
    `window` days, so a skipped day keeps the streak but lowers adherence.

    Returns current_streak, longest_streak, last_missed (ISO or None), and
    adherence (0-100 int, or None when no days in the window had doses due).
    """
    log: dict[date, str] = {}
    for key, value in (outcomes or {}).items():
        try:
            log[date.fromisoformat(str(key)[:10])] = value
        except (ValueError, TypeError):
            continue
    if isinstance(today, str):
        today = date.fromisoformat(today[:10])

    earliest = min(log) if log else today
    current = 0
    day = today - timedelta(days=1)
    while day >= earliest:
        outcome = log.get(day)
        if outcome is None or outcome == OUTCOME_MISSED:
            break
        if outcome in (OUTCOME_TAKEN, OUTCOME_SKIPPED):
            current += 1
        day -= timedelta(days=1)

    longest = run = 0
    prev = None
    for day in sorted(log):
        if prev is not None and (day - prev).days != 1:
            run = 0  # a gap in the record breaks continuity
        outcome = log[day]
        if outcome == OUTCOME_MISSED:
            run = 0
        elif outcome in (OUTCOME_TAKEN, OUTCOME_SKIPPED):
            run += 1
            longest = max(longest, run)
        prev = day
    longest = max(longest, current)

    missed = [day for day, outcome in log.items() if outcome == OUTCOME_MISSED]
    last_missed = max(missed).isoformat() if missed else None

    start = today - timedelta(days=window)
    taken = skipped = missed_n = 0
    for day, outcome in log.items():
        if start <= day < today:
            if outcome == OUTCOME_TAKEN:
                taken += 1
            elif outcome == OUTCOME_SKIPPED:
                skipped += 1
            elif outcome == OUTCOME_MISSED:
                missed_n += 1
    denom = taken + skipped + missed_n
    adherence = round(100 * taken / denom) if denom else None

    return {
        "current_streak": current,
        "longest_streak": longest,
        "last_missed": last_missed,
        "adherence": adherence,
    }


def partial_skip_meds(meds, schedule_type):
    """Meds eligible for a per-med "skip" button on a grouped dose.

    Empty unless the dose is scheduled (not PRN) and lists two or more meds: a
    single-med dose has nothing to partially skip, and a PRN dose is logged per
    med already. Backs the opt-in partial-dose skip buttons.
    """
    if (schedule_type or "") == SCHEDULE_PRN:
        return []
    meds_list = split_medications(meds)
    return meds_list if len(meds_list) >= 2 else []


def meds_contains(meds, med_name):
    """True if `med_name` is one of the medications in a dose's meds string."""
    target = (med_name or "").strip().lower()
    if not target:
        return False
    return any(part.lower() == target for part in split_medications(meds))


def normalize_skipped(value):
    """Clean a "skipped medications" input into a list of medication names.

    Accepts a list of names or a single string (split on the same separators as
    a dose's meds). Blank entries are dropped. Used by partial dose marking,
    where a dose is marked given but one or more of its meds were not taken.
    """
    if not value:
        return []
    items = split_medications(value) if isinstance(value, str) else value
    result = []
    for item in items:
        name = str(item).strip()
        if name:
            result.append(name)
    return result


def med_skipped(skipped, med_name):
    """True if `med_name` is in a dose's skipped-medications list."""
    return any(meds_contains(entry, med_name) for entry in normalize_skipped(skipped))


def supply_unit_for(meds, supplies):
    """The display unit of the first tracked supply whose medication appears in
    `meds` (a dose's medications string), or '' if none has a unit set. Lets a
    dose's amount field show the same unit as its medication's stock."""
    for supply in supplies or []:
        med = str(supply.get(CONF_SUPPLY_MED, "")).strip()
        if med and meds_contains(meds, med):
            unit = str(supply.get(CONF_SUPPLY_UNIT, "") or "").strip()
            if unit:
                return unit
    return ""


def normalize_time(value):
    """Parse a time to 'HH:MM' (24-hour), or None if it is not a valid time.

    Accepts 'HH:MM', 'H:MM', 'HH:MM:SS' (seconds dropped), and '.' as the
    hour/minute separator. Used to clean a user-entered time.
    """
    parts = re.split(r"[:.]", str(value).strip())
    if len(parts) not in (2, 3):
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except (ValueError, TypeError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def expand_dose_times(primary, extra):
    """The ordered, unique 'HH:MM' times for a dose from its primary time and an
    optional free-text "additional times" string, plus any tokens that were not
    valid times.

    `extra` tokens are separated by comma, semicolon, or whitespace, each parsed
    by normalize_time. The primary time comes first; duplicates are dropped.
    Returns (times, invalid), where invalid lists the unparseable tokens so the
    form can report them. An unparseable primary yields no times.
    """
    times: list[str] = []
    invalid: list[str] = []
    primary_norm = normalize_time(primary)
    if primary_norm is not None:
        times.append(primary_norm)
    for token in re.split(r"[,;\s]+", str(extra or "").strip()):
        if not token:
            continue
        norm = normalize_time(token)
        if norm is None:
            invalid.append(token)
        elif norm not in times:
            times.append(norm)
    return times, invalid


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
    # Start date (anchor): a universal "not before" guard for every scheduled
    # type, so a dose with a future start date does not remind until that date.
    # For interval and cycle the anchor is also the cadence origin (used below).
    anchor = _parse_iso_date(data.get(CONF_ANCHOR_DATE))
    if anchor is not None and on_date < anchor:
        return False
    # End date: a universal "not after" guard, so a dose with an end date stops
    # reminding once the course is over.
    end = _parse_iso_date(data.get(CONF_END_DATE))
    if end is not None and on_date > end:
        return False
    if stype == SCHEDULE_INTERVAL:
        n = _interval_n(data)
        if anchor is None:
            # No anchor: fall back to a fixed reference so it stays deterministic.
            return on_date.toordinal() % n == 0
        return (on_date - anchor).days % n == 0
    if stype == SCHEDULE_CYCLE:
        on_days, off_days = _cycle_days(data)
        period = on_days + off_days
        if anchor is None:
            return on_date.toordinal() % period < on_days
        return (on_date - anchor).days % period < on_days
    if stype == SCHEDULE_MONTHLY:
        last = _last_day_of_month(on_date)
        # Clamp each chosen day to the month's last day, so a dose set for the
        # 31st still fires in shorter months instead of being skipped.
        due = {min(d, last) for d in _month_days(data)}
        return on_date.day in due
    days = data.get(CONF_DAYS) or WEEKDAYS
    return WEEKDAYS[on_date.weekday()] in days


def in_schedule_window(data, on_date):
    """Whether `on_date` falls within a dose's active date range.

    True when the dose has started (on or after its start/anchor date) and has
    not ended (on or before its end date). Unlike `is_due`, this ignores the
    recurrence pattern (which weekday, interval, cycle, or month-day), so a dose
    taken a day late or early still counts as inside its own course. Used for
    supply consumption, which follows the mark rather than the schedule day; a
    dose outside its date range, or an as-needed (PRN) dose, is not in a window.
    """
    stype = data.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
    if stype == SCHEDULE_PRN:
        return False
    anchor = _parse_iso_date(data.get(CONF_ANCHOR_DATE))
    if anchor is not None and on_date < anchor:
        return False
    end = _parse_iso_date(data.get(CONF_END_DATE))
    if end is not None and on_date > end:
        return False
    return True


def reset_hms(reset_time):
    """Parse a daily reset time string into an (hour, minute, second) tuple.

    Falls back to 00:01:00 (the default) on malformed input, so a bad value
    never raises where a reset time is read.
    """
    try:
        parts = [int(p) for p in str(reset_time).split(":")]
        h, m = parts[0], parts[1]
        s = parts[2] if len(parts) > 2 else 0
    except (ValueError, IndexError, TypeError):
        h, m, s = 0, 1, 0
    return h % 24, m % 60, s % 60


def med_day(now, reset_time):
    """The date of the medication day that `now` falls in.

    The day rolls over at the patient's daily reset time, not midnight, so a
    dose left un-given late at night stays "today's" (and keeps nagging) until
    the reset time passes. With the default 00:01 reset this matches the old
    calendar-date behaviour to within a minute. `now` is a timezone-aware
    local datetime.
    """
    h, m, s = reset_hms(reset_time)
    boundary = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if now < boundary:
        return (now - timedelta(days=1)).date()
    return now.date()


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


def supply_cost_breakdown(units, per_dose, cost, per_week):
    """Cost figures for a supply, or {} when no per-unit cost is set.

    `units` is the amount on hand, `per_dose` the units per dose, `cost` the
    price of one unit (in the user's currency), and `per_week` how many doses
    are scheduled per week. `est_monthly_cost` is 0 when there is no weekly
    cadence (e.g. as-needed / PRN doses).
    """
    try:
        cost = float(cost)
        units = float(units)
        per_dose = float(per_dose)
        per_week = float(per_week)
    except (TypeError, ValueError):
        return {}
    if cost <= 0:
        return {}
    return {
        "cost_per_unit": round(cost, 2),
        "value_on_hand": round(units * cost, 2),
        "cost_per_dose": round(per_dose * cost, 2),
        "est_monthly_cost": round(per_week * (52.0 / 12.0) * per_dose * cost, 2),
    }


def dose_consumption(dose_units, supply_per_dose):
    """Units one dose consumes from its supply.

    Uses the dose's own amount when set (> 0), else the supply's default
    "units consumed per dose". Both may be fractional (e.g. 0.5 for half a pill).
    """
    try:
        du = float(dose_units or 0)
    except (TypeError, ValueError):
        du = 0.0
    if du > 0:
        return du
    try:
        return max(float(supply_per_dose or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def resolve_mark_amount(marked_units, dose_units, supply_per_dose):
    """Units to decrement for a mark: an explicit per-mark amount if one was
    given (adjustable-quantity doses), else the dose/supply default.

    ``marked_units`` is the amount chosen at mark time; when it is None the dose
    falls back to ``dose_consumption`` (its own amount, or the supply default).
    A negative amount is clamped to zero.
    """
    if marked_units is not None:
        try:
            return max(0.0, float(marked_units))
        except (TypeError, ValueError):
            pass
    return dose_consumption(dose_units, supply_per_dose)


def apply_consumption(value, amount):
    """Remove ``amount`` from a supply ``value``, clamped at zero.

    Returns ``(new_value, removed)``. ``removed`` is what actually came off,
    which is less than ``amount`` when the supply would otherwise drop below
    zero. Storing ``removed`` (not the requested amount) lets an un-mark add
    back exactly what the mark took and never more, so a mark-then-unmark on a
    nearly empty supply cannot inflate the count. Both may be fractional.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    try:
        a = max(float(amount), 0.0)
    except (TypeError, ValueError):
        a = 0.0
    new = max(0.0, v - a)
    return new, v - new


def next_refills_remaining(remaining):
    """Prescription refills left after using one, never below zero."""
    try:
        return max(0, int(remaining) - 1)
    except (TypeError, ValueError):
        return 0


def restore_refills(configured, restored_configured, restored_remaining):
    """Refills-remaining value to use on (re)load.

    Keep the live decremented count while the configured prescription count is
    unchanged, so a decrement survives the entry reloads the options flow does on
    every edit. Reset to the configured count when it changes, which is how a new
    prescription (editing "Refills remaining") starts the counter over.
    """
    try:
        cfg = max(0, int(configured))
    except (TypeError, ValueError):
        cfg = 0
    try:
        rcfg = int(restored_configured)
    except (TypeError, ValueError):
        rcfg = None
    try:
        rem = max(0, int(restored_remaining))
    except (TypeError, ValueError):
        rem = None
    if rem is not None and rcfg == cfg:
        return rem
    return cfg


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


def schedule_cadence(dose):
    """A short human cadence string for a dose, for the pill-box plan view.

    E.g. "daily", "every 2 days", "Mon, Wed, Fri", "21 on / 7 off",
    "monthly on 1, 15", or "as needed".
    """
    stype = dose.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
    if stype == SCHEDULE_PRN:
        return "as needed"
    if stype == SCHEDULE_INTERVAL:
        try:
            n = int(dose.get(CONF_INTERVAL_DAYS) or DEFAULT_INTERVAL_DAYS)
        except (TypeError, ValueError):
            n = DEFAULT_INTERVAL_DAYS
        return "daily" if n == 1 else f"every {n} days"
    if stype == SCHEDULE_CYCLE:
        try:
            on = int(dose.get(CONF_CYCLE_ON) or DEFAULT_CYCLE_ON)
            off = int(dose.get(CONF_CYCLE_OFF) or DEFAULT_CYCLE_OFF)
        except (TypeError, ValueError):
            on, off = DEFAULT_CYCLE_ON, DEFAULT_CYCLE_OFF
        return f"{on} on / {off} off"
    if stype == SCHEDULE_MONTHLY:
        days = dose.get(CONF_MONTH_DAYS) or DEFAULT_MONTH_DAYS
        return "monthly on " + ", ".join(str(d) for d in days)
    days = dose.get(CONF_DAYS) or DEFAULT_DAYS
    if len(days) >= 7:
        return "daily"
    return ", ".join(d.capitalize() for d in WEEKDAYS if d in days)


def build_day_plan(doses, supplies, details, on_date):
    """The pill-box plan for one date: per-medication, per-time-slot quantities.

    Only scheduled (non-PRN) doses that are due on ``on_date`` are included (box
    prep is for scheduled meds, not as-needed). Returns::

        {"times": ["08:00", "20:00"],
         "rows": [{"med", "prescribed_for", "schedule", "amounts": {time: qty}}]}

    ``qty`` is the dose's own amount when set, else the medication's supply
    per-dose amount, else 1. Rows are sorted by medication, columns by time. All
    inputs are the stored option lists (doses / supplies / medication details);
    pure, so it is computed in the integration and handed to the dashboard.
    """
    per_dose = {}
    for s in supplies or []:
        med = str(s.get(CONF_SUPPLY_MED, "")).strip().lower()
        if not med:
            continue
        try:
            per_dose[med] = float(s.get(CONF_SUPPLY_PER_DOSE) or 0)
        except (TypeError, ValueError):
            per_dose[med] = 0.0
    detail_by_med = {d["name"].lower(): d for d in current_medications(doses, details)}
    times = set()
    rows = {}
    for dose in doses or []:
        if (dose.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS) == SCHEDULE_PRN:
            continue
        if not is_due(dose, on_date):
            continue
        time = str(dose.get(CONF_TIME, ""))[:5]
        try:
            du = float(dose.get(CONF_DOSE_UNITS) or 0)
        except (TypeError, ValueError):
            du = 0.0
        cadence = schedule_cadence(dose)
        for med in split_medications(dose.get(CONF_MEDS)):
            key = med.lower()
            qty = du if du > 0 else (per_dose.get(key) or 1)
            row = rows.setdefault(
                key,
                {
                    "med": med,
                    "prescribed_for": detail_by_med.get(key, {}).get(
                        "prescribed_for", ""
                    ),
                    "cadences": set(),
                    "amounts": {},
                },
            )
            row["cadences"].add(cadence)
            row["amounts"][time] = qty
            times.add(time)
    result_rows = [
        {
            "med": rows[k]["med"],
            "prescribed_for": rows[k]["prescribed_for"],
            "schedule": "; ".join(sorted(rows[k]["cadences"])),
            "amounts": rows[k]["amounts"],
        }
        for k in sorted(rows)
    ]
    return {"times": sorted(times), "rows": result_rows}
