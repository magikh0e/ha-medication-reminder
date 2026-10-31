"""Load real entity modules with small, scoped Home Assistant boundary doubles.

The integration's logic and const.py are executed unchanged. Only HA's entity
base classes, clock, state/event containers and registration hooks are replaced,
so these unit tests can run in the existing pytest-only CI environment. This
does not simulate an HA installation or test service/platform registration.
"""

import importlib
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


class Entity:
    def async_write_ha_state(self):
        pass

    def async_on_remove(self, unsubscribe):
        pass


class RestoreEntity(Entity):
    async def async_added_to_hass(self):
        pass


class State:
    def __init__(self, entity_id, state, attributes):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes

    @property
    def name(self):
        return self.attributes.get("friendly_name", self.entity_id)


class Event:
    def __init__(self, event_type, data):
        self.event_type = event_type
        self.data = data


def _register(*args, **kwargs):
    return lambda: None


@contextmanager
def load_entities(*platforms):
    """Isolate imports and restore sys.modules after each test."""
    modules = {}

    def module(name, **attributes):
        result = ModuleType(name)
        result.__path__ = []
        result.__dict__.update(attributes)
        modules[name] = result
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(modules[parent], child, result)
        return result

    module("homeassistant")
    module("homeassistant.util", slugify=lambda s: re.sub(r"\W+", "_", s.lower()))
    clock = module(
        "homeassistant.util.dt",
        now=lambda: datetime(2026, 6, 1, 14, tzinfo=timezone.utc),
        parse_datetime=lambda value: datetime.fromisoformat(value) if value else None,
        as_local=lambda value: value,
    )
    module("homeassistant.components")
    for name, class_name in (
        ("number", "NumberEntity"),
        ("switch", "SwitchEntity"),
        ("binary_sensor", "BinarySensorEntity"),
        ("sensor", "SensorEntity"),
    ):
        module(
            "homeassistant.components." + name,
            **{class_name: type(class_name, (Entity,), {})}
        )
    modules["homeassistant.components.number"].NumberMode = SimpleNamespace(BOX="box")
    modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = (
        SimpleNamespace(PROBLEM="problem")
    )
    modules["homeassistant.components.sensor"].SensorDeviceClass = SimpleNamespace(
        TIMESTAMP="timestamp"
    )
    modules["homeassistant.components.sensor"].RestoreSensor = RestoreEntity
    module("homeassistant.config_entries", ConfigEntry=object)
    module("homeassistant.const", EVENT_HOMEASSISTANT_STARTED="homeassistant_started")
    core_state = SimpleNamespace(running=object())
    module(
        "homeassistant.core",
        CoreState=core_state,
        State=State,
        Event=Event,
        HomeAssistant=object,
        callback=lambda func: func,
    )
    module("homeassistant.helpers")
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module("homeassistant.helpers.config_validation")
    module("homeassistant.helpers.entity_registry")
    module(
        "homeassistant.helpers.event",
        async_call_later=_register,
        async_track_time_change=_register,
        async_track_time_interval=_register,
    )
    module(
        "homeassistant.helpers.restore_state",
        RestoreEntity=RestoreEntity,
        ExtraStoredData=object,
    )
    module("homeassistant.helpers.storage", Store=object)
    module("voluptuous")
    package = module("_medication_entity_test")
    package.__path__ = [
        str(
            Path(__file__).resolve().parents[1]
            / "custom_components"
            / "medication_reminder"
        )
    ]
    with patch.dict(sys.modules, modules):
        loaded = {
            name: importlib.import_module(package.__name__ + "." + name)
            for name in platforms
        }
        yield SimpleNamespace(**loaded, clock=clock, core_state=core_state)
