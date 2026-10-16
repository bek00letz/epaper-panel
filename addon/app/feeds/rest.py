"""Generic JSON over HTTP. Covers any API nobody has written a preset for."""
import json
import aiohttp


def _pick(data, path):
    """Walk a dotted path, with [n] for list indices. Blank path = whole doc."""
    if not path:
        return data
    cur = data
    for part in str(path).replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        try:
            if isinstance(cur, list):
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        except (IndexError, ValueError, TypeError, KeyError):
            return None
        if cur is None:
            return None
    return cur


def _parse_headers(raw):
    """Accept a dict, a JSON object string, or 'Header: Value' lines from the UI."""
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if not isinstance(raw, str) or not raw.strip():
        return {}
    s = raw.strip()
    if s.startswith("{"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            pass
    out = {}
    for line in s.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


async def fetch(src, ctx):
    url = (src.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return []
    headers = _parse_headers(src.get("headers"))
    timeout = aiohttp.ClientTimeout(total=15)
    shared = (ctx or {}).get("session")
    if shared is not None:
        async with shared.get(url, headers=headers, timeout=timeout) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
    else:
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
