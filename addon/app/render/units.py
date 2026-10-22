"""Dynamic units: a value that picks its own unit, so 950 W stays watts and
1234 W reads 1.23 kW, without a hand-written template.

An element opts in with `units`:

    {"base": "W", "mode": "scale", "decimals": 2}     # step up through kW, MW…
    {"base": "m/s", "mode": "convert", "to": "km/h"}  # always shown in km/h
    {"base": "W", "show_unit": False}                  # just the number; a label says the unit

`base` is the sensor's own unit. Scaling only ever steps *up* from it, so a
kW sensor reading 0.5 says 0.50 kW rather than surprising anyone with 500 W.
A text element with `show: "unit"` and the same `units` shows just the unit
the value would use, so a label can follow along ("kW used").
"""

# Each family in rising order: (unit, size in the family's smallest unit).
FAMILIES = (
    (("mW", 1e-3), ("W", 1), ("kW", 1e3), ("MW", 1e6), ("GW", 1e9)),
    (("Wh", 1), ("kWh", 1e3), ("MWh", 1e6), ("GWh", 1e9)),
    (("mg", 1e-3), ("g", 1), ("kg", 1e3), ("t", 1e6)),
    (("mm", 1e-3), ("cm", 1e-2), ("m", 1), ("km", 1e3)),
    (("mA", 1e-3), ("A", 1), ("kA", 1e3)),
    (("mV", 1e-3), ("V", 1), ("kV", 1e3)),
    (("VA", 1), ("kVA", 1e3), ("MVA", 1e6)),
    (("var", 1), ("kvar", 1e3)),
    (("B", 1), ("kB", 1e3), ("MB", 1e6), ("GB", 1e9), ("TB", 1e12)),
    (("bit/s", 1), ("kbit/s", 1e3), ("Mbit/s", 1e6), ("Gbit/s", 1e9)),
    (("Hz", 1), ("kHz", 1e3), ("MHz", 1e6), ("GHz", 1e9)),
    (("mL", 1e-3), ("L", 1), ("m³", 1e3)),
    (("ms", 1e-3), ("s", 1), ("min", 60), ("h", 3600), ("d", 86400)),
)

# Fixed conversions: (from, to) -> function.
CONVERSIONS = {
    ("m/s", "km/h"): lambda v: v * 3.6,
    ("km/h", "m/s"): lambda v: v / 3.6,
    ("km/h", "mph"): lambda v: v / 1.609344,
    ("mph", "km/h"): lambda v: v * 1.609344,
    ("m/s", "mph"): lambda v: v * 2.236936,
    ("°C", "°F"): lambda v: v * 9 / 5 + 32,
    ("°F", "°C"): lambda v: (v - 32) * 5 / 9,
    ("km", "mi"): lambda v: v / 1.609344,
    ("mi", "km"): lambda v: v * 1.609344,
    ("kg", "lb"): lambda v: v * 2.2046226,
    ("lb", "kg"): lambda v: v / 2.2046226,
    ("hPa", "inHg"): lambda v: v * 0.02953,
    ("L", "gal"): lambda v: v / 3.785412,
}


def family_of(unit: str):
    for fam in FAMILIES:
        for i, (u, _) in enumerate(fam):
            if u == unit:
                return fam, i
    return None, -1


def can_scale(unit: str) -> bool:
    fam, _ = family_of(str(unit or "").strip())
    return fam is not None


def apply(value: float, units: dict) -> tuple[float, str, bool]:
    """(value, unit, changed) for a number under an element's `units`."""
    base = str((units or {}).get("base") or "").strip()
    mode = (units or {}).get("mode") or "scale"
    if mode == "convert":
        to = str(units.get("to") or "").strip()
        fn = CONVERSIONS.get((base, to))
        return (fn(value), to, True) if fn else (value, base, False)
    fam, i = family_of(base)
    if fam is None:
        return value, base, False
    size = fam[i][1]
    in_small = value * size
    pick = i
    for j in range(i, len(fam)):
        if abs(in_small) >= fam[j][1]:
            pick = j
    if pick == i:
        return value, base, False
    unit, step = fam[pick]
    return in_small / step, unit, True


def format_value(value: float, el: dict) -> str:
    """The number, in its chosen unit, with the element's decimals."""
    units = el.get("units") or {}
    v, unit, changed = apply(value, units)
    if changed:
        dec = units.get("decimals", 2 if units.get("mode", "scale") == "scale" else el.get("decimals", 0))
    else:
        dec = el.get("decimals", 0)
    dec = max(0, min(6, int(dec or 0)))
    sep = units.get("sep", " ")
    if not unit or units.get("show_unit") is False:
        return f"{v:.{dec}f}"
    return f"{v:.{dec}f}{sep}{unit}"


def unit_for(raw, el: dict) -> str:
    """Just the unit the value would be shown in, for a label that follows it."""
    units = el.get("units") or {}
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return str(units.get("base") or "")
    _, unit, _ = apply(v, units)
    return unit


# ---------------------------------------------------------------- a unit that follows its sensor (review 2 #3)

FOLLOWS = ("number", "bar")                 # elements whose `unit: "entity"` is their sensor's unit


def suffix_for(unit) -> str:
    """What follows a value for a sensor's unit: "%" close up, any other with a space, nothing for none."""
    u = str(unit or "").strip()
    return "" if not u else u if u == "%" else f" {u}"


def follows(el: dict) -> bool:
    return isinstance(el, dict) and el.get("type") in FOLLOWS and el.get("unit") == "entity" and bool(str(el.get("entity") or "").strip())


def follow_units(pages: dict, unit_of: dict) -> list[str]:
    """Pages made before a unit followed its sensor: a number or gauge whose unit after it is its
    sensor's own (as the editor copied it in) follows the sensor from now on. A unit you typed
    that isn't the sensor's stays yours. `unit_of`: {entity: its unit now}. Returns the pages changed."""
    changed = []
    for name, page in (pages or {}).items():
        for el in (page or {}).get("elements") or []:
            if not isinstance(el, dict) or el.get("type") not in FOLLOWS or el.get("unit") or "suffix" not in el:
                continue
            ent = str(el.get("entity") or "").strip()
            if not ent or ent not in unit_of or (isinstance(el.get("value"), str) and el["value"].strip()):
                continue
            if str(el.get("suffix") or "").strip() == str(unit_of[ent] or "").strip() and unit_of[ent]:
                el["unit"] = "entity"
                del el["suffix"]
                if name not in changed:
                    changed.append(name)
    return changed
