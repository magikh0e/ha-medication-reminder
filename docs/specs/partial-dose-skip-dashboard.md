# Spec: dashboard skip control for partial dose marking

Follow-up to #30 / v0.35.0. That release added the `skipped` parameter to the
`medication_reminder.mark_given` service, so a grouped dose can be marked given
while one or more of its meds are left out (their supply does not decrement).
Today that is service-only. This spec covers making it tappable from the bundled
dashboards, for a caregiver who is standing at the pill box and notices one med
is missing.

## The problem, stated honestly

A dose is one `switch.<patient>_<time>_<meds>`. Its `medications` attribute is a
string that can list several meds ("Apoquel & Vitamin D"). "Skip one med" is a
per-med, multi-select choice made at the moment of marking.

Three hard constraints shape every option:

1. **Lovelace holds no transient multi-tap state.** There is no way for a card to
   remember "the caregiver unchecked Vitamin D" between taps and then feed that
   set into a single `mark_given` call, unless that choice is stored in an
   entity. A checkbox list that defaults to "all taken" and remembers unchecks
   therefore needs one boolean of state per (dose, med).
2. **Markdown cards cannot call services.** The existing per-med rendering (the
   current-medications card already splits `medications` with
   `regex_replace('[&+]|\s+/\s+', ',')`) can *show* each med, but a markdown link
   cannot run `mark_given`. Tap targets have to be real entities or a card that
   supports `tap_action: call-service`.
3. **The bundled dashboards are auto-discovering and low-dependency.** They add
   no helpers and depend only on `auto-entities` + `card-mod`. Whatever we add has
   to discover itself from entity attributes (no per-patient YAML) and should not
   pull in new HACS cards for the caregiver view, which is meant to be safe and
   simple to share.

Constraint 1 is the decider: a true "pick which meds to skip, then mark" needs
state, and state means entities. So the realistic choices split into
**stateless** (one tap = mark-given-except-this-one-med) and **stateful** (toggle
some meds off, then mark).

## Options

### Option A - per-med "skip" buttons (stateless, simplest) — recommended first step

For each **scheduled** dose that lists **2 or more** meds, the integration creates
one button per med:

- entity: `button.<patient>_<time>_<meds>_skip_<med>`
- unique_id: `{entry_id}_skipbtn_{slugify(time+'_'+meds)}_{slugify(med)}`
- name: `"Mark given, skip <med>"`
- attributes: `patient`, `dose_time`, `medications` (the parent dose), `skip_med`
  (the one med), `parent_entity` (the dose switch's unique_id suffix)
- press -> calls `async_mark_given_at(skipped=[skip_med])` on the parent dose.

Dashboard: an auto-discovered `entities` card ("Partial dose") that lists these
buttons for doses due today, grouped under the dose. Filter template mirrors the
existing Mark given card:

```yaml
- type: custom:auto-entities
  show_empty: false
  card: { type: entities, title: "Took most of it", show_header_toggle: false }
  filter:
    template: >
      {% set today = ['mon','tue','wed','thu','fri','sat','sun'][now().weekday()] %}
      {% for b in states.button if b.attributes.skip_med is defined %}
      {% set sw = states.switch
         | selectattr('attributes.medications','eq', b.attributes.medications)
         | selectattr('attributes.patient','eq', b.attributes.patient) | first %}
      {% if sw and sw.state == 'off'
         and sw.attributes.get('scheduled_today', today in (sw.attributes.days or [])) %}
      {{ b.entity_id }}
      {% endif %}
      {% endfor %}
  sort: { method: name }
```

- **Pros:** stateless, no multi-tap state, discovers itself, no new HACS deps,
  composes directly with the v0.35.0 `skipped` plumbing (the button just calls
  the service that already exists). One obvious tap for the real-world case the
  issue described ("one specific pill is missing").
- **Cons:** only skips **one** med per press. A dose of 3 meds where 2 are missing
  is not expressible (you would skip one, then the dose is already given). Entity
  count grows: a 2-med dose adds 2 buttons, a 3-med dose adds 3. Clutter if a
  patient has many grouped doses.
- **Scope guard:** only create these for scheduled doses with >= 2 meds. Single-med
  doses and PRN doses get nothing (PRN is logged per-med already).

### Option B - per-med skip toggles (stateful, full multi-select)

For each scheduled dose with >= 2 meds, create a per-med **switch**:

- entity: `switch.<patient>_<time>_<meds>_skip_<med>` ("Skip <med> next mark",
  default off), device_class none, resets to off daily and after any mark/un-mark
  of the parent dose.
- When the parent dose is marked given (plain toggle **or** `mark_given` with no
  explicit `skipped`), `async_mark_given_at` gathers its sibling skip switches
  that are on, uses their meds as the `skipped` list, then resets them off. An
  explicit `skipped` argument still wins (service callers are unaffected).

Dashboard: an auto-discovered card per dose showing the dose plus its skip
toggles, so the caregiver flips "Skip Vitamin D" on and then taps the dose.

- **Pros:** true multi-select; skip any subset before marking; still
  auto-discovering; no new HACS deps; the mental model ("uncheck what you didn't
  give, then mark given") matches a pill organiser.
- **Cons:** most integration work and the most coupling. The dose switch has to
  find and reset sibling entities at mark time, which is new cross-entity logic.
  Doubles the skip entity count vs Option A (switch per med, held as state).
  Two-step interaction (toggle, then mark) is more than a caregiver may want for
  the common one-pill case. Restart/reload has to restore the skip toggles' state
  consistently with the dose.

### Option C - pure-frontend popup (no new entities)

A per-dose "Skip a med…" action opens a popup (needs `browser_mod`) listing the
dose's meds, each calling `mark_given` with that one med skipped.

- **Pros:** no new entities; keeps the dose list clean (one extra action per dose).
- **Cons:** adds a `browser_mod` dependency, which the caregiver view deliberately
  avoids; popup state still cannot accumulate a multi-med selection without an
  entity, so it is really Option A's single-skip behaviour behind a popup; harder
  to template generically.

## Recommendation

Ship **Option A** first. It covers the exact case the forum user raised ("one med
in the handful is missing"), is stateless and low-risk, reuses the v0.35.0 service
unchanged, and needs no new HACS card. Gate the buttons behind a per-dose or
global option (see open questions) so patients who never need it do not get extra
entities.

Treat **Option B** as a later upgrade if multi-med skipping is actually requested.
It is the "correct" general answer but a real step up in integration complexity
and entity count; not worth it on spec alone.

Skip **Option C** unless a popup UX is wanted for other reasons; it buys little
over A and adds a dependency the caregiver view avoids.

## Cross-cutting details (apply to A and B)

- **Eligibility:** only scheduled doses (not PRN) with `len(split_medications(meds)) >= 2`.
  Reuse `split_medications` / `meds_contains` from `const.py`; no new matching code.
- **Placement:** put the control on the **caregiver** and the single-card layouts
  (that is where marking happens). The **admin** view can show it too, but it is
  not essential there.
- **Daily reset / undo:** a skip button (A) is stateless, nothing to reset. Skip
  toggles (B) must reset off at the dose's daily reset and whenever the parent
  dose is un-marked, so a skip never leaks into the next day or a re-mark.
- **Supply:** no new supply logic. Marking with `skipped` already leaves the
  skipped med's supply untouched and still fires `medication_reminder_dose_given`
  with `skipped`, so history/logbook already reflect it.
- **Naming:** keep labels explicit so a caregiver is not surprised that a single
  tap marks the whole dose given. Option A's "Mark given, skip <med>" says exactly
  what happens; Option B's "Skip <med> next mark" reads as a modifier, not an
  action.
- **Entity-count impact:** state it in the docs. A patient with three 2-med doses
  gains 6 skip entities under Option A (or 6 switches under B). Keep it opt-in.

## Open questions for the maintainer

1. **Opt-in granularity:** a single global "enable partial-dose controls" option
   on the entry, or per-dose? Global is simpler and matches how little state this
   needs; per-dose avoids entities on doses that never skip.
2. **Entity domain for Option A:** buttons (as specced) vs `scene`/`script`-style.
   Buttons are the natural fit and auto-discover cleanly.
3. **Do we want Option B at all,** or is single-skip (A) enough for the real
   demand? The issue only described one missing med.
4. **Caregiver safety:** is a one-tap "mark given but skip X" acceptable on the
   shareable caregiver view, or should partial marking live only on the admin
   view? (It does not edit counts, so it is arguably caregiver-safe.)
5. **Label wording** for the card and buttons, to keep "this marks the dose given"
   unambiguous.

## Not changing

The v0.35.0 service stays as-is; every option here is a producer of
`mark_given(skipped=...)` calls, so the service is the stable seam. No supply,
event, or restore logic changes are required for Option A.
