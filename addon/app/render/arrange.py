"""One design, several sizes: where each element sits on a canvas other than the one it was made on.

A design is made on one canvas (its `canvas`, like "792x272"): its elements'
boxes are for that size. Every other canvas a screen shows it on has an
**arrangement**: per element ID (unique in the design, so renaming a page
keeps it), the element's own box and text size there (ARRANGE_KEYS). What an element shows (its binding, text, icon,
style) is the design's, the same on every size.

An element with no arrangement for a canvas is placed automatically: the
design's content area scaled uniformly to fit the other content area and
centred. It's marked `_auto` in the editor's view until someone moves it.

Pure functions over plain dicts; devices.py does the storing.
"""
from __future__ import annotations

import copy
import secrets

from . import theme as T

# What may differ between sizes. Everything else is the element's content and style.
ARRANGE_KEYS = ("x", "y", "w", "h", "size", "font_scale")
AUTO = "_auto"



def canvas_key(w: int, h: int) -> str:
    return f"{int(w)}x{int(h)}"


def parse_canvas(key: str) -> tuple[int, int]:
    w, _, h = str(key).partition("x")
    return int(w), int(h)


# ---------------------------------------------------------------- element IDs

def new_id(taken) -> str:
    while True:
        cand = "e" + secrets.token_hex(3)
        if cand not in taken:
            return cand


def ensure_ids(pages: dict) -> dict:
    """Give every element an ID that's unique in the design.

    A missing ID is derived from the element's place (`e<n>`, counting through
    the pages in order), so the same design read twice gets the same IDs until
    it's saved with them. A repeated one (a copied page) gets a fresh one.
    """
    seen, n = set(), 0
    for page in (pages or {}).values():
        if not isinstance(page, dict):
            continue
        for el in page.get("elements") or []:
            if not isinstance(el, dict):
                continue
            eid = str(el.get("id") or "")[:24]
            if not eid:
                eid = f"e{n}"
            if eid in seen:
                eid = new_id(seen)
            el["id"] = eid
            seen.add(eid)
            n += 1
    return pages


# ---------------------------------------------------------------- automatic placement

def content_height(key: str) -> int:
    """The height above the footer band on a canvas (theme.band_height(): 25 to 36 px by screen height)."""
    _, h = parse_canvas(key)
    return max(1, h - T.band_height(h))


def _fit(base: str, target: str) -> tuple[float, float, float]:
    """Scale and offset that fit base's content area into target's, centred."""
    bw, bh = parse_canvas(base)
    tw, th = parse_canvas(target)
    bch, tch = content_height(base), content_height(target)
    s = min(tw / bw, tch / bch)
    return s, (tw - bw * s) / 2, (tch - bch * s) / 2


def auto_box(el: dict, base: str, target: str) -> dict:
    """The element's ARRANGE_KEYS on `target`, placed automatically from its box on `base`."""
    s, ox, oy = _fit(base, target)
    out = {}
    for k in ("x", "w"):
        if isinstance(el.get(k), (int, float)):
            out[k] = round(el[k] * s + (ox if k == "x" else 0))
    for k in ("y", "h"):
        if isinstance(el.get(k), (int, float)):
            out[k] = round(el[k] * s + (oy if k == "y" else 0))
    if isinstance(el.get("size"), (int, float)) and el.get("size"):
        out["size"] = max(8, round(el["size"] * s))
    if "font_scale" in el:
        out["font_scale"] = el["font_scale"]
    return out


def base_box(box: dict, base: str, target: str) -> dict:
    """The inverse of auto_box: a box drawn on `target`, as it would sit on `base`."""
    s, ox, oy = _fit(base, target)
    out = {}
    for k in ("x", "w"):
        if isinstance(box.get(k), (int, float)):
            out[k] = round((box[k] - (ox if k == "x" else 0)) / s)
    for k in ("y", "h"):
        if isinstance(box.get(k), (int, float)):
            out[k] = round((box[k] - (oy if k == "y" else 0)) / s)
    if isinstance(box.get("size"), (int, float)) and box.get("size"):
        out["size"] = max(8, round(box["size"] / s))
    if "font_scale" in box:
        out["font_scale"] = box["font_scale"]
    return out


# ---------------------------------------------------------------- views and saving

def pages_for(design: dict, base: str, target: str) -> dict:
    """The design's pages with every element placed for `target`.

    On the design's own canvas that's the pages as they are. Elsewhere each
    element takes its arrangement, or is placed automatically and marked AUTO.
    """
    pages = copy.deepcopy(design.get("pages") or {})
    if target == base:
        return pages
    placed = ((design.get("arrangements") or {}).get(target) or {})
    for page in pages.values():
        for el in page.get("elements") or []:
            box = placed.get(el.get("id"))
            if isinstance(box, dict):
                el.update({k: v for k, v in box.items() if k in ARRANGE_KEYS})
            else:
                el.update(auto_box(el, base, target))
                el[AUTO] = True
    return pages


def merge_pages(design: dict, pages: dict, base: str, target: str) -> dict:
    """A design with `pages` (as edited on `target`) saved into it.

    Content and order go to the design, so every size sees them. Boxes go to
    the design itself on its own canvas, or to `target`'s arrangement. An
    element still marked AUTO keeps being placed automatically. Elements and
    pages that are gone leave every arrangement too.
    """
    out = copy.deepcopy(design)
    old_pages = design.get("pages") or {}
    pages = ensure_ids(copy.deepcopy(pages))
    arrangements = copy.deepcopy(design.get("arrangements") or {})
    if target == base:
        for page in pages.values():
            for el in page.get("elements") or []:
                el.pop(AUTO, None)
        out["pages"] = pages
    else:
        placed = arrangements.setdefault(target, {})
        old_els = {e.get("id"): e for p in old_pages.values() for e in p.get("elements") or []}
        new_pages = {}
        for name, page in pages.items():
            els = []
            for el in page.get("elements") or []:
                auto = el.pop(AUTO, False)
                box = {k: el[k] for k in ARRANGE_KEYS if k in el}
                old = old_els.get(el["id"])
                content = {k: v for k, v in el.items() if k not in ARRANGE_KEYS}
                if old is not None:
                    mine = {**content, **{k: old[k] for k in ARRANGE_KEYS if k in old}}
                else:
                    mine = {**content, **base_box(box, base, target)}       # new here: a place on the design's canvas
                if auto and old is not None:
                    placed.pop(el["id"], None)
                else:
                    placed[el["id"]] = box
                els.append(mine)
            new_pages[name] = {**{k: v for k, v in page.items() if k != "elements"}, "elements": els}
        out["pages"] = new_pages
    # Nothing arranged for what no longer exists.
    ids = {e.get("id") for p in out["pages"].values() for e in p.get("elements") or []}
    for key in list(arrangements):
        for eid in [i for i in arrangements[key] if i not in ids]:
            del arrangements[key][eid]
        if not arrangements[key]:
            del arrangements[key]
    if arrangements:
        out["arrangements"] = arrangements
    else:
        out.pop("arrangements", None)
    return out


def bake(design: dict, base: str, target: str) -> dict:
    """A copy of the design made on `target`: its pages as placed there, no arrangements."""
    out = {k: copy.deepcopy(v) for k, v in design.items() if k not in ("pages", "arrangements", "canvas")}
    pages = pages_for(design, base, target)
    for page in pages.values():
        for el in page.get("elements") or []:
            el.pop(AUTO, None)
    out["pages"] = pages
    out["canvas"] = target
    return out
