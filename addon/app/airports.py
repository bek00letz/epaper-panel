"""Airport codes to places, from a bundled copy of OurAirports (public domain).

Offline on purpose: typing a code in the editor sends nothing anywhere.
reference/airports.json is built from https://ourairports.com/data/ and holds
every open airport with a three-letter IATA code.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

TABLE = Path(__file__).parent / "reference" / "airports.json"


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        return json.loads(TABLE.read_text(encoding="utf-8")).get("airports", {})
    except Exception as exc:
        print(f"airports: couldn't read {TABLE.name}: {exc}", flush=True)
        return {}


def lookup(code: str) -> dict | None:
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        return None
    row = _table().get(code)
    if not row:
        return None
    lat, lon, name, city, country = row
    return {"code": code, "lat": lat, "lon": lon, "name": name, "city": city, "country": country}
