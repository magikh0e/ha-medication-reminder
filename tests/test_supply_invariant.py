"""Seeded property test for supply counting: the count is the buggiest area.

The near-empty over-restore, the refill double-count (#57), and the late-dose
miss (#61) were all supply-count logic bugs. This drives long random sequences
of the real supply operations (mark, skip-mark, un-mark, refill, manual set,
reconcile, day rollover, restart/restore) against an independent model of the
intended behaviour, and asserts after every step that the live count equals the
model and stays within [0, max]. A failure prints the seed and the last dozen
operations for an exact replay.

The model is written from the spec, not copied from the code, so a divergence is
either a real bug or a spec misunderstanding; both are worth catching here rather
than in the field.
"""

import asyncio
import copy
import random
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from entity_test_support import Event, State, load_entities

MAX = 9999.0  # MedicationSupplyNumber._attr_native_max_value
WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Two doses with different per-dose amounts. Dose "b" is scheduled for a single
# weekday, so on most days it is "not due today"; supply must still follow the
# mark (the #61 fix), so the model treats both as consumable whenever marked.
DOSES = {
    "switch.a": {"amount": 1.0, "days": list(WEEK)},
    "switch.b": {"amount": 0.5, "days": ["mon"]},
}


@pytest.fixture
def modules():
    with load_entities("number") as loaded:
        yield loaded


class Fuzz:
    START = 3.0  # small, so the near-empty clamp is hit often
    REFILL_TO = 4.0

    def __init__(self, modules, rng, add_mode):
        self.m = modules
        self.rng = rng
        self.add_mode = add_mode
        self.sw = {e: {"on": False, "skipped": False} for e in DOSES}
        # Independent model of the supply's state.
        self.value = self.START
        self.consumed = {}  # entity -> medication-day iso it was counted for
        self.consumed_amount = {}  # entity -> units that actually came off
        self.day = self._today()
        self.supply = self._new_supply()
        self.log = []

    # ---- wiring to the real entity ----
    def _record(self):
        return {
            "supply_med": "Test med",
            "supply_units": self.START,
            "supply_per_dose": 1,
            "supply_refill_to": self.REFILL_TO,
            "supply_refill_add": self.add_mode,
        }

    def _new_supply(self):
        s = self.m.number.MedicationSupplyNumber(
            SimpleNamespace(entry_id="e"), "Test patient", self._record(), "00:01:00"
        )
        s.hass = SimpleNamespace(
            state=self.m.core_state.running,
            states=SimpleNamespace(async_all=lambda _d: self._switch_states()),
            bus=SimpleNamespace(async_listen=lambda *_a: lambda: None),
        )
        s.entity_id = "number.test_supply"
        return s

    def _today(self):
        return self.m.number.med_day(self.m.clock.now(), "00:01:00").isoformat()

    def _state(self, entity, onoff):
        st = self.sw[entity]
        return State(
            entity,
            onoff,
            {
                "patient": "Test patient",
                "medications": "Test med",
                "schedule_type": "weekdays",
                "days": DOSES[entity]["days"],
                "dose_units": DOSES[entity]["amount"],
                "skipped": ["Test med"] if st["skipped"] else [],
                "given_at": self.m.clock.now().isoformat(),
            },
        )

    def _switch_states(self):
        return [
            self._state(e, "on" if st["on"] else "off") for e, st in self.sw.items()
        ]

    def _eligible(self, entity):
        """Intended consumable: on, not skipped (all DOSES are in-window)."""
        st = self.sw[entity]
        return st["on"] and not st["skipped"]

    # ---- operations: apply to the real supply AND the model, then compare ----
    def op_mark(self):
        offs = [e for e, st in self.sw.items() if not st["on"]]
        if not offs:
            return
        entity = self.rng.choice(offs)
        skipped = self.rng.random() < 0.25
        self.sw[entity] = {"on": True, "skipped": skipped}
        new = self._state(entity, "on")
        self.supply._on_state_changed(
            Event(
                "state_changed",
                {
                    "entity_id": entity,
                    "old_state": State(entity, "off", new.attributes),
                    "new_state": new,
                },
            )
        )
        if self._eligible(entity) and self.consumed.get(entity) != self.day:
            removed = min(DOSES[entity]["amount"], self.value)
            self.value -= removed
            self.consumed[entity] = self.day
            self.consumed_amount[entity] = removed
        self.log.append(f"mark {entity} skipped={skipped}")

    def op_undo(self):
        ons = [e for e, st in self.sw.items() if st["on"]]
        if not ons:
            return
        entity = self.rng.choice(ons)
        self.sw[entity] = {"on": False, "skipped": False}
        self.supply._on_dose_undone(Event("undone", {"entity_id": entity}))
        if self.consumed.get(entity) == self.day:
            refund = self.consumed_amount.pop(entity, 0.0)
            self.value = min(MAX, self.value + refund)
            del self.consumed[entity]
        self.log.append(f"undo {entity}")

    def op_refill(self):
        self.supply._on_refill(
            Event("refill", {"patient": "Test patient", "medication": "Test med"})
        )
        if self.add_mode:
            self.value = min(MAX, self.value + self.REFILL_TO)
        else:
            self.value = self.REFILL_TO
            self._baseline()
        self.log.append("refill")

    def op_manual(self):
        v = round(self.rng.uniform(0, 12), 2)
        asyncio.run(self.supply.async_set_native_value(v))
        self.value = max(0.0, v)
        self._baseline()
        self.log.append(f"manual {v}")

    def op_reconcile(self):
        self.supply._reconcile()
        for entity in DOSES:
            if self._eligible(entity) and self.consumed.get(entity) != self.day:
                removed = min(DOSES[entity]["amount"], self.value)
                self.value -= removed
                self.consumed[entity] = self.day
                self.consumed_amount[entity] = removed
        self.log.append("reconcile")

    def op_cross_day(self):
        nxt = self.m.clock.now() + timedelta(days=1)
        self.m.clock.now = (lambda t: (lambda: t))(nxt)
        for entity in self.sw:
            self.sw[entity] = {"on": False, "skipped": False}  # mirrors reset_given
        self.day = self._today()
        self.log.append("cross_day")

    def op_restore(self):
        prev = State(
            self.supply.entity_id,
            str(self.supply.native_value),
            copy.deepcopy(self.supply.extra_state_attributes),
        )
        self.supply = self._new_supply()
        self.supply.async_get_last_state = AsyncMock(return_value=prev)
        asyncio.run(self.supply.async_added_to_hass())
        self.supply._reconcile()
        for entity in DOSES:  # restore reinstates state; reconcile is idempotent
            if self._eligible(entity) and self.consumed.get(entity) != self.day:
                removed = min(DOSES[entity]["amount"], self.value)
                self.value -= removed
                self.consumed[entity] = self.day
                self.consumed_amount[entity] = removed
        self.log.append("restore")

    def _baseline(self):
        """Mirror _reset_consumption_baseline: an explicit count is authoritative,
        so already-given doses are remembered as counted with nothing to refund."""
        self.consumed = {}
        self.consumed_amount = {}
        for entity in DOSES:
            if self._eligible(entity):
                self.consumed[entity] = self.day
                self.consumed_amount[entity] = 0.0


@pytest.mark.parametrize("add_mode", [True, False])
@pytest.mark.parametrize("seed", range(8))
def test_supply_count_matches_model_under_random_ops(modules, seed, add_mode):
    rng = random.Random(seed)
    f = Fuzz(modules, rng, add_mode)
    ops = [
        f.op_mark,
        f.op_undo,
        f.op_refill,
        f.op_manual,
        f.op_reconcile,
        f.op_cross_day,
        f.op_restore,
    ]
    weights = [32, 20, 10, 8, 12, 9, 9]
    for _ in range(250):
        rng.choices(ops, weights=weights)[0]()
        got = round(f.supply.native_value, 6)
        exp = round(f.value, 6)
        tail = "\n".join(f.log[-12:])
        assert (
            0 <= got <= MAX
        ), f"out of bounds: {got}\nseed={seed} add={add_mode}\n{tail}"
        assert got == exp, (
            f"count diverged: live {got} vs model {exp}\n"
            f"seed={seed} add={add_mode}\n{tail}"
        )
