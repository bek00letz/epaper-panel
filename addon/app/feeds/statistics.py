"""A long-term statistic as an entity.

Statistics are websocket-only in Home Assistant -- there is no REST route --
so a template cannot reach them. This makes one available to pages.
"""
from datetime import datetime

import aiohttp

PERIOD_START = {
    "month": lambda n: n.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
    "day":   lambda n: n.replace(hour=0, minute=0, second=0, microsecond=0),
    "year":  lambda n: n.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
}


async def _query_ws(s, url, token, stat, period, start):
    async with s.ws_connect(url, timeout=10) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        if (await ws.receive_json()).get("type") != "auth_ok":
            return []
        await ws.send_json({
            "id": 1, "type": "recorder/statistics_during_period",
            "start_time": start.isoformat(), "statistic_ids": [stat],
            "period": period, "types": ["change"],
        })
        return ((await ws.receive_json()).get("result") or {}).get(stat) or []


async def fetch(src, ctx):
    stat = (src.get("entity") or "").strip()
    if not stat or not (ctx or {}).get("ha_token"):
        return []
    period = src.get("period", "month")
    if period not in PERIOD_START:
        period = "month"
    start = PERIOD_START[period](datetime.now().astimezone())

    url = ctx["ha_base"].replace("http://", "ws://").replace("https://", "wss://") + "/websocket"
    shared = ctx.get("session")
    if shared is not None:
        rows = await _query_ws(shared, url, ctx["ha_token"], stat, period, start)
    else:
        async with aiohttp.ClientSession() as s:
            rows = await _query_ws(s, url, ctx["ha_token"], stat, period, start)

    total = sum(float(r.get("change") or 0) for r in rows)
    attrs = {"friendly_name": src.get("friendly_name") or src["name"]}
    for k in ("unit", "icon"):
        if src.get(k):
            attrs["unit_of_measurement" if k == "unit" else "icon"] = src[k]
    return [(f"sensor.epaper_{src['name']}", round(total, 1), attrs)]
