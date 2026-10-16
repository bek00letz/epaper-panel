"""Generic JSON over HTTP. Covers any API nobody has written a preset for."""
import aiohttp


def _pick(data, path):
    """Walk a dotted path, with [n] for list indices. Blank path = whole doc."""
    if not path:
        return data
    cur = data
    for part in str(path).replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur.get(part)
        if cur is None:
            return None
    return cur


async def fetch(src, ctx):
    url = src.get("url")
    if not url:
        return []
    headers = src.get("headers") or {}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=headers) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)

    value = _pick(data, src.get("pick", ""))
    attrs = {"friendly_name": src.get("friendly_name") or src["name"]}
    if src.get("unit"):
        attrs["unit_of_measurement"] = src["unit"]
    if src.get("icon"):
        attrs["icon"] = src["icon"]
    return [(f"sensor.epaper_{src['name']}", value, attrs)]
