"""Home Assistant REST helpers: states, templates, actions, history."""

import health
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
import aiohttp

from config import HA_BASE, HA_TOKEN, valid_entity_id
from fixture import eval_fixture_template, load_fixture


async def ha_json(session, path, method="GET", **kw):
    url = f"{HA_BASE}/api{path}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with session.request(method, url, headers=headers, timeout=timeout, **kw) as r:
        r.raise_for_status()
        return await r.json()


async def ha_template(session, tpl) -> str | None:
    """Render one template through Home Assistant.

    Returns None on HTTP/network failure so batched callers can distinguish
    a syntax error in one template from a legitimate empty string.
    """
    if not HA_TOKEN:
        return eval_fixture_template(tpl)
    url = f"{HA_BASE}/api/template"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with session.post(url, headers=headers, json={"template": tpl}, timeout=timeout) as r:
            if r.status != 200:
                return None
            return (await r.text()).strip()
    except Exception:
        return None


SEP = "<<<|epaper|>>>"


async def resolve_templates(session, templates):
    """Render many templates in ONE request, with per-template fallback.

    If one page has a broken Jinja expression, the batch call returns HTTP 400
    (`None`). Falling back to individual evaluation ensures one bad template
    never blanks out the rest of the panel.
    """
    if not templates:
        return {}
    keys = list(templates)
    if not HA_TOKEN:
        return {k: eval_fixture_template(templates[k]) for k in keys}
    # The add-on's own values go in as they are: Home Assistant only has them through a broker.
    import conditions
    import runtime
    templates = {k: conditions.inline(templates[k], runtime.PUBLISHED) for k in keys}

    joined = f"\n{SEP}\n".join(templates[k] for k in keys)
    out = await ha_template(session, joined)
    if out is not None:
        parts = [p.strip() for p in out.split(SEP)]
        if len(parts) == len(keys):
            return {k: parts[i] for i, k in enumerate(keys)}

    # Fallback: resolve individually so one broken template only affects itself
    results = {}
    for k in keys:
        res = await ha_template(session, templates[k])
        results[k] = res if res is not None else ""
    return results


async def call_ha_service(session, domain, service, data=None) -> bool:
    """Call a Home Assistant action. Returns whether Home Assistant accepted it."""
    if not HA_TOKEN:
        return False
    safe_domain = re.sub(r"[^a-z0-9_]+", "", str(domain).lower())
    safe_service = re.sub(r"[^a-z0-9_]+", "", str(service).lower())
    try:
        await ha_json(session, f"/services/{safe_domain}/{safe_service}",
                      method="POST", json=data or {})
        return True
    except Exception as exc:
        print(f"service {safe_domain}.{safe_service} failed: {health.describe(exc)}", flush=True)
        return False


async def curve_series(session, entity, hours=24, buckets=24):
    """Rolling hourly means for a sparkline, from the recorder's history API."""
    eid = str(entity or "").strip()
    if not valid_entity_id(eid):
        return []
    if not HA_TOKEN:
        return list(load_fixture().get("pv_curve_w") or [])

    hours = max(1, min(168, int(hours or 24)))
    buckets = max(2, min(48, int(buckets or min(hours, 24))))
    now = datetime.now().astimezone()
    start = now - timedelta(hours=hours)
    safe_start = urllib.parse.quote(start.isoformat(), safe=":+")
    safe_eid = urllib.parse.quote(eid, safe=".")
    path = (f"/history/period/{safe_start}"
            f"?filter_entity_id={safe_eid}&minimal_response&no_attributes")
    try:
        rows = await ha_json(session, path)
    except Exception:
        return []
    if not rows or not rows[0]:
        return []

    span_sec = max(1.0, (now - start).total_seconds())
    sums, counts = [0.0] * buckets, [0] * buckets
    initial_val = None
    for r in rows[0]:
        try:
            v = float(r["state"])
            t = datetime.fromisoformat(r["last_changed"]).astimezone()
        except (KeyError, TypeError, ValueError):
            continue
        if t <= start:
            initial_val = v
            continue
        idx = int(((t - start).total_seconds() / span_sec) * buckets)
        idx = max(0, min(buckets - 1, idx))
        sums[idx] += v
        counts[idx] += 1

    last = max((i for i, c in enumerate(counts) if c), default=-1)
    if last < 0:
        return [initial_val, initial_val] if initial_val is not None else []

    out = []
    carry = initial_val if initial_val is not None else 0.0
    for i in range(last + 1):
        if counts[i]:
            carry = sums[i] / counts[i]
        out.append(carry)
    return out
