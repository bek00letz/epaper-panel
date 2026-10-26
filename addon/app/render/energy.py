"""Energy widgets: a period's total (Solar this month), the grid now, and what it cost.

Values come from sources/energy.py, already in kWh, watts and Home
Assistant's currency; this only draws. Bars are one per hour, day or month
of the period, solid black (no grey on e-ink), drawn from a hairline base.
"""
from __future__ import annotations

from . import hero
from . import theme as T
from . import words
from .words import say

ICONS = {"solar": "mdi:white-balance-sunny", "grid_import": "mdi:transmission-tower-import",
         "grid_export": "mdi:transmission-tower-export", "entity": "mdi:lightning-bolt"}
PERIODS = ("day", "month", "year")
# What's missing, as words (render/words_table.py "energy.missing.*").
MISSING = {"solar": "solar", "grid_import": "grid", "grid_export": "grid", "grid": "grid", "entity": "entity",
           "prices": "prices"}


def missing(what: str) -> str:
    return say(f"energy.missing.{MISSING.get(what, 'entity')}")

# Currency symbols people expect, and whether they go before the number.
# Anything else is shown by its code after the number ("4.20 CHF").
CURRENCY = {"USD": ("$", True), "GBP": ("£", True), "JPY": ("¥", True), "CNY": ("¥", True), "INR": ("₹", True),
            "AUD": ("A$", True), "CAD": ("C$", True), "NZD": ("NZ$", True), "EUR": ("€", False),
            "RON": ("lei", False), "SEK": ("kr", False), "NOK": ("kr", False), "DKK": ("kr", False),
            "PLN": ("zł", False), "CZK": ("Kč", False), "HUF": ("Ft", False)}


def kwh(v: float) -> str:
    v = abs(float(v))
    if v >= 1000:
        return f"{words.number(v / 1000, 1)} MWh"
    return f"{words.number(v, 1 if v < 10 else 0)} kWh"


def watts(v: float) -> str:
    v = abs(float(v))
    if v >= 1000:
        return f"{words.number(v / 1000, 1)} kW"
    return f"{words.number(v, 0)} W"


def money(v: float, currency: str) -> str:
    amount = words.number(abs(float(v)), 2, group=True)
    sym, before = CURRENCY.get(str(currency or "").upper(), (str(currency or "").upper(), False))
    if not sym:
        return amount
    return f"{sym}{amount}" if before else f"{amount} {sym}"


def bars(d, box, values, *, signed: bool = False) -> None:
    """A bar per slot across the box; None slots (still to come) stay empty.
    Signed: up from a middle line for plus (buying), down for minus (selling)."""
    x, y, w, h = box
    n = len(values)
    if not n:
        return
    pitch = w / n
    bw = max(2, round(pitch * 0.7))
    line = max(2, round(h / 90))
    shown = [abs(v) for v in values if v is not None]
    peak = max(shown) if shown and max(shown) > 0 else 1.0
    if signed:
        mid = y + h // 2
        d.rectangle([(x, mid - line // 2), (x + w - 1, mid - line // 2 + line - 1)], fill=T.BLACK)
        reach = h // 2 - line
    else:
        base = y + h - line
        d.rectangle([(x, base), (x + w - 1, base + line - 1)], fill=T.BLACK)
        reach = h - line
    for k, v in enumerate(values):
        if v is None or v == 0:
            continue
        bh = max(2, round(abs(v) / peak * reach))
        x0 = round(x + k * pitch + (pitch - bw) / 2)
        if signed:
            y0, y1 = (mid - line // 2 - bh, mid - line // 2) if v > 0 else (mid - line // 2 + line, mid - line // 2 + line + bh)
        else:
            y0, y1 = base - bh, base
        d.rectangle([(x0, y0), (x0 + bw - 1, y1 - 1)], fill=T.BLACK)


def _chart_box(box):
    """Bars sit in the middle part of the space beside the number, clear of its edges."""
    x, y, w, h = box
    ch = round(h * 0.62)
    return x, y + (h - ch) // 2, w, ch


def draw_total(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    source = el.get("source") if el.get("source") in ICONS else "solar"
    period = el.get("period") if el.get("period") in PERIODS else "month"
    if data.get("total") is None:
        hero.message(d, box, missing(data.get("missing") or source))
        return
    caption = say(f"energy.{source}.{period}")
    fact = hero.Fact(kwh(data["total"]), caption, ICONS[source])
    values = data.get("bars") or []
    hero.draw(img, d, box, fact, beside=(lambda b: bars(d, _chart_box(b), values)) if values else None, scale=scale)


def draw_grid(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    w, today = data.get("watts"), data.get("today")
    if w is None and today is None:
        if data.get("missing") or el.get("entity"):
            hero.message(d, box, missing("entity" if el.get("entity") else "grid"))
        return
    if w is not None:
        caption = say("energy.buying") if w > 0 else say("energy.selling")
        if abs(w) < 1:
            caption = say("energy.idle")
        fact = hero.Fact(watts(w), caption, "mdi:transmission-tower")
    else:                                   # no power sensor: today's balance instead
        fact = hero.Fact(kwh(today), say("energy.grid_import.day" if today >= 0 else "energy.grid_export.day"), "mdi:transmission-tower")
    values = data.get("bars") or []
    hero.draw(img, d, box, fact, scale=scale,
              beside=(lambda b: bars(d, _chart_box(b), values, signed=True)) if any(v for v in values if v) else None)


def draw_cost(img, d, box, el: dict, data, *, scale: float = 1.0) -> None:
    if not isinstance(data, dict):
        return
    today, month, cur = data.get("today"), data.get("month"), data.get("currency") or ""
    if today is None:
        hero.message(d, box, missing("prices"))
        return
    sells = bool(data.get("sells"))

    def said(v, when):                      # net of both ways when you sell, so one word says it
        return say(f"energy.earned.{when}" if v >= 0 and sells else f"energy.spent.{when}")

    main = hero.Fact(money(today, cur), said(today, "day"), "mdi:cash-plus" if today >= 0 and sells else "mdi:cash-minus")
    aside = hero.Fact(money(month, cur), said(month, "month")) if month is not None else None
    hero.draw(img, d, box, main, aside=aside, scale=scale, share=0.36)
