"""Constants for the Medication Reminder integration."""

DOMAIN = "medication_reminder"

CONF_PATIENT = "patient"
CONF_PATIENT_TYPE = "patient_type"
CONF_DOSES = "doses"
CONF_TIME = "time"
CONF_MEDS = "meds"
CONF_NOTIFY = "notify"
CONF_RESET_TIME = "reset_time"
CONF_NAG_MINUTES = "nag_minutes"
CONF_NAG_INTERVAL = "nag_interval"
CONF_TIME_FORMAT = "time_format"

DEFAULT_PATIENT_TYPE = "person"
DEFAULT_RESET_TIME = "00:01:00"
DEFAULT_NAG_MINUTES = 45
DEFAULT_NAG_INTERVAL = 15
DEFAULT_TIME_FORMAT = "12h"

# Icon for the patient-level "all doses given" sensor, by patient type.
PATIENT_ICONS = {
    "person": "mdi:account",
    "dog": "mdi:dog",
    "cat": "mdi:cat",
    "bird": "mdi:bird",
    "rabbit": "mdi:rabbit",
    "other": "mdi:paw",
}
