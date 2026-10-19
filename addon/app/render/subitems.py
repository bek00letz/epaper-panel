"""Sub-item discovery, item identity generation, and slice mapping.

Every category page in the rotation can either be:
1. Single-page (1 slice): standard dashboard page or fixed widget.
2. Multi-item (N slices): a category with sub-items (e.g. live sports matches,
   overhead airspace flights, media watch queues, calendars, or future composite items).

To make navigation, rotation, and locks completely impervious to pages or items
being added, removed, or reordered:
- Each category has a 32-bit identity: `stripmeta.identity(f"cat:{cat_name}")`.
- Each slice has a 32-bit identity: `stripmeta.identity(f"slice:{cat_name}:{item_key}")`.

Even if a category moves from index 8 to index 9, or a match shifts position
because another match ended or started, the panel matches against these 32-bit
identities in PSRAM.
"""

from __future__ import annotations

from typing import Any
try:
    from . import binding, stripmeta
except (ImportError, ValueError):
    from render import binding, stripmeta


def derive_item_key(item: Any, fallback_index: int) -> str:
    """Extract a stable, content-derived string key from any item dictionary or object."""
    if isinstance(item, dict):
        for k in ("id", "uid", "event_id", "icao24", "callsign", "key", "slug"):
            val = item.get(k)
            if val is not None and str(val).strip():
                return str(val).strip()
        # Sports match fallback: home vs away
        h = item.get("home_team")
        a = item.get("away_team")
        if h and a:
            return f"{h}_vs_{a}".replace(" ", "_")
        # Feed/media fallback: title + detail
        title = item.get("title") or item.get("name")
        if title:
            detail = item.get("detail") or ""
            return f"{title}:{detail}".replace(" ", "_")[:60]
    elif isinstance(item, str) and item.strip():
        return item.strip()[:60]
    return str(fallback_index)


def item_value(el: dict, feed_entity: str | None, item: Any) -> str | None:
    """What an attribute binding shows on the slice for one feed item.

    A feed's items carry the same parts as its sensor's attributes (Jellyfin's
    `episode_name`, `added_ago`, ...), so on each slice the binding reads that
    item's own value, with the element's replacements applied. Returns None
    when the element doesn't bind to one of the item's parts.
    """
    if not feed_entity or not isinstance(item, dict) or el.get("show") != "attribute":
        return None
    if str(el.get("entity", "")).strip() != feed_entity:
        return None
    if el.get("attribute") not in item:
        return None
    return binding.local_value(el, {feed_entity: {"attributes": item}})


def inspect_category_subitems(
    page_def: dict,
    page_vals: dict,
    feed_items_cache: dict[str, list[dict]] | None = None
) -> tuple[int, str | None, list[str], list[Any], str | None]:
    """Inspect a page definition and resolved values to discover its sub-items.

    Returns:
        sub_count: Number of slices for this category (at least 1).
        sub_type: Type of sub-items ('sports', 'flight', 'feed', or None).
        sub_keys: Deduplicated stable key strings for each sub-slice.
        items: List of raw item objects (or empty list if single-page).
        feed_entity: Entity ID of the feed sensor if applicable.
    """
    elements = page_def.get("elements") or []
    sub_count = 1
    sub_type = None
    items: list[Any] = []
    feed_entity = None

    # 1. Check for built-in composite widgets with multiple sub-items
    for el_idx, el in enumerate(elements):
        if not isinstance(el, dict):
            continue
        el_t = el.get("type")
        if el_t == "flight_tracker":
            fl_list = page_vals.get(el_idx)
            if isinstance(fl_list, list) and len(fl_list) > 1:
                sub_count = max(sub_count, min(len(fl_list), 5))
                sub_type = "flight"
                items = fl_list[:sub_count]
        elif el_t == "sports_match":
            sm_list = page_vals.get(el_idx)
            if isinstance(sm_list, list) and len(sm_list) > 1:
                sub_count = max(sub_count, min(len(sm_list), 6))
                sub_type = "sports"
                items = sm_list[:sub_count]

    # 2. Check for feed items (Watch/Jellyfin, RSS, or any sensor with an 'items' attribute)
    if not sub_type and feed_items_cache:
        for el in elements:
            if not isinstance(el, dict):
                continue
            ent = str(el.get("entity", ""))
            if ent.startswith("sensor.epaper_") and not ent.endswith("_count") and not ent.startswith("sensor.epaper_category_") and not ent.startswith("sensor.epaper_panel_"):
                f_items = feed_items_cache.get(ent)
                if f_items and isinstance(f_items, list) and len(f_items) > 1:
                    feed_entity = ent
                    sub_count = max(sub_count, min(len(f_items), 5))
                    sub_type = "feed"
                    items = f_items[:sub_count]
                    break

    # 3. Generate unique stable keys for each slice in this category
    sub_keys: list[str] = []
    seen_keys: set[str] = set()

    if sub_count <= 1:
        sub_count = 1
        sub_keys = ["0"]
    else:
        for idx in range(sub_count):
            raw_item = items[idx] if idx < len(items) else None
            k = derive_item_key(raw_item, idx)
            # Ensure keys within this category are strictly unique
            unique_k = k
            disambig = 2
            while unique_k in seen_keys:
                unique_k = f"{k}#{disambig}"
                disambig += 1
            seen_keys.add(unique_k)
            sub_keys.append(unique_k)

    return sub_count, sub_type, sub_keys, items, feed_entity


def compute_identities(
    live_cats: list[str],
    cat_sub_keys: list[list[str]]
) -> tuple[list[int], list[int]]:
    """Compute 32-bit integer identities for all categories and slices.

    Guarantees:
    - `cat_ids` has length `len(live_cats)` and no duplicate IDs.
    - `sub_ids` has length `sum(len(k) for k in cat_sub_keys)` and no duplicates
      within any individual category.
    """
    cat_ids: list[int] = []
    seen_cat_ids: set[int] = set()
    for cat_name in live_cats:
        c_id = stripmeta.identity(f"cat:{cat_name}")
        disambig = 2
        while c_id in seen_cat_ids:
            c_id = stripmeta.identity(f"cat:{cat_name}:{disambig}")
            disambig += 1
        seen_cat_ids.add(c_id)
        cat_ids.append(c_id)

    sub_ids: list[int] = []
    for cat_name, sub_keys in zip(live_cats, cat_sub_keys):
        seen_slice_ids: set[int] = set()
        for k in sub_keys:
            s_id = stripmeta.identity(f"slice:{cat_name}:{k}")
            disambig = 2
            while s_id in seen_slice_ids:
                s_id = stripmeta.identity(f"slice:{cat_name}:{k}:{disambig}")
                disambig += 1
            seen_slice_ids.add(s_id)
            sub_ids.append(s_id)

    return cat_ids, sub_ids
