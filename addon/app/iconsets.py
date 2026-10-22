"""Icon sets copied into the add-on, whole: Home Assistant's own and custom ones.

The add-on ships Material Design Icons (render/icons), so it always draws.
This keeps what it draws the same as Home Assistant's (the user's design,
21 Oct):

- **Home Assistant's set.** Its frontend serves Material Design Icons as
  plain files on the local network (`/static/mdi/iconMetadata.json`, which
  names the version and the chunks, then each chunk as name -> path). When
  that version isn't the shipped one, every chunk is copied in one go into
  `/data/icons/mdi.json` and used from then on. Checked at start and when
  Home Assistant's own version changes; never per icon, never on demand,
  never during a render.
- **Custom sets**, read from Home Assistant's configuration folder whenever
  their files change, each copied whole:
  - Custom Icons (thomasloven/hass-custom_icons): SVG files in
    `<config>/custom_icons` (prefix `local:`), and the Iconify sets it
    downloaded (`iconify-icon-sets-master.zip`, one prefix each), the ones
    switched on in its settings, as Home Assistant says (`collections_on`).
  - Script sets that HACS installs under `<config>/www/community`, written
    the way custom-brand-icons (`phu:`) and its kin are: a `var icons = {}`
    of name -> [x, y, w, h, path] and `window.customIcons["prefix"]`.
  A custom icon is its outline only (render/vector): nothing in an SVG runs,
  is fetched or is shown as it is, here or in the editor.

Nothing here reaches the internet: Home Assistant is on the add-on's own
network, and its configuration folder is mapped in.
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import math
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import aiohttp

import config
import health
from render import icons, vector

HEALTH = "Icons from Home Assistant"
FRONTEND = (os.environ.get("HA_FRONTEND") or "http://homeassistant:8123").rstrip("/")
CHECK_EVERY = 300                   # seconds between looking for a new Home Assistant or changed files
MAX_SVG = 512 * 1024                # bytes; an icon is a few kB
MAX_SCRIPT = 32 * 1024 * 1024
MAX_ICONS = 60000                   # per set
MAX_DEPTH = 32                      # groups inside groups; a real icon has a handful
RESERVED = {icons.DEFAULT, icons.BUILT_IN}


def icon_dir() -> Path:
    return config.DATA_DIR / "icons"


def _state_path() -> Path:
    return icon_dir() / "state.json"


def _read_state() -> dict:
    try:
        got = json.loads(_state_path().read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data, compress=False) -> None:
    """Written whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(data, separators=(",", ":")).encode()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(gzip.compress(raw, 6, mtime=0) if compress else raw)
    os.replace(tmp, path)


def _read_json(path: Path, compressed=False):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if compressed else raw)


# ---------------------------------------------------------------- at start

def load_copies() -> None:
    """Use the sets copied before, from the add-on's data (a start, before anything is drawn)."""
    d = icon_dir()
    mdi = d / "mdi.json.gz"
    if mdi.exists():
        try:
            got = _read_json(mdi, compressed=True)
            if _usable(got):
                icons.install(icons.DEFAULT, got)
        except (OSError, ValueError) as exc:
            print(f"icons: the copy of Home Assistant's set can't be read ({health.describe(exc)}); using the shipped one", flush=True)
    custom = d / "custom.json.gz"
    if custom.exists():
        try:
            for prefix, data in (_read_json(custom, compressed=True) or {}).items():
                if _usable(data) and prefix not in RESERVED:
                    icons.install(prefix, data)
        except (OSError, ValueError, AttributeError) as exc:
            print(f"icons: the custom sets can't be read ({health.describe(exc)}); they'll be copied again", flush=True)


def _usable(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("icons"), dict) and bool(data["icons"])


# ------------------------------------------------- Home Assistant's own set

async def _get_json(session, path: str, timeout=15):
    """A file Home Assistant's frontend serves to anyone on its network (no key)."""
    bases = [FRONTEND] + ([FRONTEND.replace("http://", "https://", 1)] if FRONTEND.startswith("http://") else [])
    for i, base in enumerate(bases):
        # Home Assistant may serve its own HTTPS on the internal name, which no certificate names;
        # what's fetched is public icon outlines, each checked before it's used.
        extra = {"ssl": False} if base.startswith("https://") else {}
        try:
            async with session.get(base + path, timeout=aiohttp.ClientTimeout(total=timeout), **extra) as r:
                r.raise_for_status()
                return await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if i == len(bases) - 1:
                raise


async def copy_home_assistant(session, hass, *, ha_version: str = "") -> str:
    """Bring the Material Design set in step with Home Assistant's: what happened, in words.

    Only when Home Assistant's version is new to the add-on. The copy is all or nothing: every
    chunk, every outline checked, at least as many icons as the shipped set less a tenth, or the
    set in use stays as it is.
    """
    state = _read_state()
    if not ha_version:
        cfg = await hass.rest("GET", "/config") or {}
        ha_version = str(cfg.get("version") or "")
    if ha_version and state.get("ha_version") == ha_version:
        return "unchanged"
    meta = await _get_json(session, "/static/mdi/iconMetadata.json")
    version = str((meta or {}).get("version") or "")
    chunks = [p.get("file") for p in (meta or {}).get("parts") or [] if isinstance(p, dict)]
    if not version or not chunks or not all(isinstance(f, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", f) for f in chunks):
        raise ValueError("Home Assistant's icon list isn't in the form the add-on knows")
    shipped = icons.shipped()
    have = icons.set_for(icons.DEFAULT) or {}
    if version == shipped.get("version"):
        if (icon_dir() / "mdi.json.gz").exists():
            (icon_dir() / "mdi.json.gz").unlink()
        icons.remove(icons.DEFAULT)
        said = f"the same as the add-on's ({version})"
    elif have.get("from") == "home_assistant" and have.get("version") == version:
        said = f"already copied ({version})"
    else:
        got: dict[str, str] = {}
        for f in chunks:
            part = await _get_json(session, f"/static/mdi/{f}.json")
            if not isinstance(part, dict):
                raise ValueError("a part of Home Assistant's icons isn't a list of icons")
            got.update(part)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _checked_mdi, got, version, len(shipped.get("icons") or {}))
        await loop.run_in_executor(None, lambda: _write_json(icon_dir() / "mdi.json.gz", data, compress=True))
        icons.install(icons.DEFAULT, data)
        said = f"copied {len(data['icons'])} icons ({version})"
    state.update(ha_version=ha_version, mdi_version=version)
    _write_json(_state_path(), state)
    return said


def _checked_mdi(got: dict, version: str, shipped_count: int) -> dict:
    out = {}
    for name, d in got.items():
        if not (isinstance(name, str) and icons.NAME_RE.match(name) and isinstance(d, str) and vector.check(d)):
            raise ValueError(f"Home Assistant's icon {str(name)[:40]!r} can't be drawn")
        out[name] = d
    if len(out) < shipped_count * 0.9:
        raise ValueError(f"Home Assistant served only {len(out)} icons")
    return {"prefix": icons.DEFAULT, "name": "Material Design", "version": version, "from": "home_assistant",
            "icons": dict(sorted(out.items()))}


# ------------------------------------------------------------- custom sets

_LENGTH = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_SKIP = {"defs", "clipPath", "mask", "symbol", "title", "desc", "style", "script", "metadata", "text",
         "image", "pattern", "linearGradient", "radialGradient", "filter", "foreignObject", "marker", "switch", "a"}
_WHITE = {"#fff", "#ffffff", "white", "rgb(255,255,255)"}


def _num(x, default=0.0) -> float:
    m = _LENGTH.match(str(x or ""))
    return float(m.group(1)) if m else default


def _style(el, inherited: dict) -> dict:
    st = dict(inherited)
    for k in ("fill", "stroke", "stroke-width", "fill-rule", "display", "visibility", "opacity", "fill-opacity"):
        if el.get(k) is not None:
            st[k] = el.get(k).strip()
    for decl in str(el.get("style") or "").split(";"):
        k, _, v = decl.partition(":")
        if k.strip() in ("fill", "stroke", "stroke-width", "fill-rule", "display", "visibility", "opacity", "fill-opacity"):
            st[k.strip()] = v.strip()
    return st


def _mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3],
            a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _transform(text: str):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", str(text or "")):
        a = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if name == "matrix" and len(a) == 6:
            t = tuple(a)
        elif name == "translate" and a:
            t = (1, 0, 0, 1, a[0], a[1] if len(a) > 1 else 0)
        elif name == "scale" and a:
            t = (a[0], 0, 0, a[1] if len(a) > 1 else a[0], 0, 0)
        elif name == "rotate" and a:
            r = math.radians(a[0])
            t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(a) == 3:
                t = _mul(_mul((1, 0, 0, 1, a[1], a[2]), t), (1, 0, 0, 1, -a[1], -a[2]))
        elif name == "skewX" and a:
            t = (1, 0, math.tan(math.radians(a[0])), 1, 0, 0)
        elif name == "skewY" and a:
            t = (1, math.tan(math.radians(a[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)
    return m


def _shape_d(tag: str, el) -> str:
    g = lambda k: _num(el.get(k))  # noqa: E731
    if tag == "path":
        return str(el.get("d") or "")
    if tag in ("circle", "ellipse"):
        cx, cy = g("cx"), g("cy")
        rx = g("r") if tag == "circle" else g("rx")
        ry = g("r") if tag == "circle" else g("ry")
        if rx <= 0 or ry <= 0:
            return ""
        return f"M{cx - rx} {cy}A{rx} {ry} 0 1 0 {cx + rx} {cy}A{rx} {ry} 0 1 0 {cx - rx} {cy}Z"
    if tag == "rect":
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        if w <= 0 or h <= 0:
            return ""
        rx, ry = g("rx"), g("ry")
        rx, ry = (rx or ry), (ry or rx)
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0:
            return f"M{x} {y}H{x + w}V{y + h}H{x}Z"
        return (f"M{x + rx} {y}H{x + w - rx}A{rx} {ry} 0 0 1 {x + w} {y + ry}V{y + h - ry}"
                f"A{rx} {ry} 0 0 1 {x + w - rx} {y + h}H{x + rx}A{rx} {ry} 0 0 1 {x} {y + h - ry}"
                f"V{y + ry}A{rx} {ry} 0 0 1 {x + rx} {y}Z")
    if tag in ("polygon", "polyline"):
        nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", str(el.get("points") or ""))
        if len(nums) < 4:
            return ""
        pts = [f"{nums[i]} {nums[i + 1]}" for i in range(0, len(nums) - 1, 2)]
        return "M" + "L".join(pts) + ("Z" if tag == "polygon" else "")
    if tag == "line":
        return f"M{g('x1')} {g('y1')}L{g('x2')} {g('y2')}"
    return ""


def svg_record(text: str):
    """An SVG file as an outline record (render/vector), or None when it has nothing to draw.

    Only shapes are read: paths, circles, ellipses, rectangles, polygons, lines, in groups with
    transforms; fill and stroke, either fill rule. Scripts, links, styles sheets, pictures and
    text are left out, and a file that declares its own entities isn't read at all.
    """
    if not isinstance(text, str) or len(text) > MAX_SVG or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    tag = lambda el: str(el.tag).rsplit("}", 1)[-1]  # noqa: E731
    if tag(root) != "svg":
        return None
    vb = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", str(root.get("viewBox") or ""))]
    if len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
        w, h = _num(root.get("width"), 24.0), _num(root.get("height"), 24.0)
        vb = [0.0, 0.0, w if w > 0 else 24.0, h if h > 0 else 24.0]
    fill, odd, strokes = [], [], []
    base = {"fill": "black", "stroke": "none", "stroke-width": "1", "fill-rule": "nonzero"}

    def walk(el, matrix, st, depth=0):
        t = tag(el)
        if t in _SKIP or depth > MAX_DEPTH:
            return
        st = _style(el, st)
        if st.get("display") == "none" or st.get("visibility") == "hidden" or _num(st.get("opacity"), 1.0) <= 0:
            return
        if el.get("transform"):
            matrix = _mul(matrix, _transform(el.get("transform")))
        if t in ("svg", "g"):
            for child in el:
                walk(child, matrix, st, depth + 1)
            return
        d = _shape_d(t, el)
        if not d:
            return
        try:
            nd = vector.normalize(d, matrix)
        except (vector.PathError, ValueError, ZeroDivisionError):
            return
        f = st.get("fill", "black").replace(" ", "").lower()
        if t not in ("line", "polyline") and f != "none" and f not in _WHITE and not f.startswith("url(") \
                and _num(st.get("fill-opacity"), 1.0) > 0:
            (odd if st.get("fill-rule") == "evenodd" else fill).append(nd)
        s = st.get("stroke", "none").replace(" ", "").lower()
        sw = _num(st.get("stroke-width"), 1.0) * math.sqrt(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]))
        if s not in ("none", "") and s not in _WHITE and sw > 0:
            strokes.append([nd, round(sw, 3)])

    try:
        walk(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), base)
    except (RecursionError, ValueError, OverflowError, ZeroDivisionError):
        return None                     # a file no icon is like: left out, never the set with it
    rec = {"d": "".join(fill), "v": [round(x, 3) for x in vb]}
    if odd:
        rec["e"] = "".join(odd)
    if strokes:
        rec["s"] = strokes
    if not rec["d"]:
        del rec["d"]
    return rec if vector.check(rec) else None


# What Custom Icons switches on when it's set up (its config flow): when Home Assistant can't say
# which collections are on, and the add-on never heard before.
CUSTOM_ICONS_DEFAULTS = frozenset({"local", "fa6-regular", "fa6-solid", "fa6-brands"})


async def collections_on(hass) -> frozenset[str] | None:
    """The collections Custom Icons has switched on, as Home Assistant says (its websocket command
    custom_icons/activesets): empty when it isn't installed or set up; None when Home Assistant
    can't say (unreachable, no key), and then `copy_custom` keeps the last answer it had. Never from
    Home Assistant's own storage files, which hold every integration's credentials."""
    from hass import HassError
    if hass is None or not hass.available:
        return None
    try:
        got = await hass.ws({"type": "custom_icons/activesets"})
    except HassError as exc:
        if exc.code == "unknown_command":           # Custom Icons isn't installed
            return frozenset()
        return None
    return frozenset(str(x) for x in got if isinstance(x, str)) if isinstance(got, list) else frozenset()


def _read_local(folder: Path) -> dict:
    """<config>/custom_icons/**/*.svg, named by their path there without .svg ("pets/cat-outside")."""
    out = {}
    for path in sorted(folder.rglob("*.svg")):
        if path.name.endswith("-webfont.svg") or not path.is_file() or path.stat().st_size > MAX_SVG:
            continue
        name = path.relative_to(folder).as_posix().removesuffix(".svg")
        if not icons.NAME_RE.match(name):
            continue
        try:
            rec = svg_record(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if rec:
            out[name] = rec
        if len(out) >= MAX_ICONS:
            break
    return out


def _read_iconify(zip_path: Path, prefix: str) -> tuple[str, dict]:
    """One Iconify set from Custom Icons' download (its own name, {name: record}). Iconify's file
    is {"info": {"name"}, "icons": {name: {"body", "width", ...}}, "width", ...}."""
    with zipfile.ZipFile(zip_path) as zf:
        member = f"icon-sets-master/json/{prefix}.json"
        info = zf.getinfo(member)
        if info.file_size > MAX_SCRIPT:
            return prefix, {}
        data = json.loads(zf.read(member))
    title = str((data.get("info") or {}).get("name") or prefix)[:60]
    left, top = data.get("left", 0), data.get("top", 0)
    width, height = data.get("width", 16), data.get("height", 16)
    out = {}
    for name, ic in (data.get("icons") or {}).items():
        if not (isinstance(ic, dict) and isinstance(ic.get("body"), str) and icons.NAME_RE.match(name)):
            continue
        if ic.get("rotate") or ic.get("hFlip") or ic.get("vFlip"):
            continue
        vb = (ic.get("left", left), ic.get("top", top), ic.get("width", width), ic.get("height", height))
        rec = svg_record(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">{ic["body"]}</svg>')
        if rec:
            out[name] = rec
        if len(out) >= MAX_ICONS:
            break
    return title, out


_SCRIPT_PREFIX = re.compile(r"""window\.customIcons\s*\[\s*["']([a-z][a-z0-9_-]{0,31})["']\s*\]\s*=""")
_SCRIPT_ICONS = re.compile(r"""\b(?:var|let|const)\s+icons\s*=\s*\{""")


def read_script_set(text: str):
    """(prefix, {name: record}) from a script icon set written like custom-brand-icons, or None."""
    m = _SCRIPT_PREFIX.search(text)
    start = _SCRIPT_ICONS.search(text)
    if not m or not start:
        return None
    end = text.find("\n};", start.end())
    if end < 0:
        return None
    literal = text[start.end() - 1:end + 2]
    try:
        raw = json.loads(re.sub(r",\s*}\s*$", "}", literal))
    except ValueError:
        return None
    out = {}
    for name, v in raw.items():
        if not (isinstance(v, list) and len(v) >= 5 and isinstance(v[4], str) and icons.NAME_RE.match(str(name))):
            continue
        try:
            view = [float(x) for x in v[:4]]
        except (TypeError, ValueError):
            continue
        rec = v[4] if view == [0.0, 0.0, 24.0, 24.0] else {"d": v[4], "v": view}
        if vector.check(rec):
            out[name] = rec
        if len(out) >= MAX_ICONS:
            break
    return m.group(1), out


def _title(folder: str) -> str:
    """A set's name from its folder: "custom-brand-icons" reads "Custom brand icons"."""
    words = re.sub(r"^(hass|ha|lovelace)[-_]", "", folder).replace("-", " ").replace("_", " ").strip()
    return (words[:1].upper() + words[1:])[:60] or folder


def _script_files(config_dir: Path):
    root = config_dir / "www" / "community"
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*.js") if p.is_file() and p.stat().st_size <= MAX_SCRIPT)


def custom_signature(config_dir: Path, on: frozenset[str]) -> str:
    """What the custom sets are now (their files' names, sizes, times, and the collections switched
    on), so a change is noticed cheaply."""
    bits = []
    folder = config_dir / "custom_icons"
    if folder.is_dir():
        for p in sorted(folder.rglob("*")):
            if p.is_file() and (p.suffix in (".svg", ".zip")):
                s = p.stat()
                bits.append(f"{p.relative_to(folder).as_posix()}:{s.st_size}:{int(s.st_mtime)}")
    bits.append("on:" + ",".join(sorted(on)))
    for p in _script_files(config_dir):
        s = p.stat()
        bits.append(f"{p.relative_to(config_dir).as_posix()}:{s.st_size}:{int(s.st_mtime)}")
    return "|".join(bits)


def read_custom_sets(config_dir: Path, on: frozenset[str] = frozenset()) -> dict:
    """Every custom set on this Home Assistant: {prefix: {"name", "from", "icons"}}, Custom Icons'
    collections as far as `on` has them switched on. Sets that can't be read are left out (and said
    in the log); the first of two with one prefix wins."""
    sets: dict[str, dict] = {}
    folder = config_dir / "custom_icons"
    if on and folder.is_dir():
        if "local" in on:
            got = _read_local(folder)
            if got:
                sets["local"] = {"name": "Your own icons", "from": "custom_icons", "icons": got}
        zp = folder / "iconify-icon-sets-master.zip"
        for prefix in sorted(on - {"local"}):
            if prefix in RESERVED or prefix in sets or not icons.PREFIX_RE.match(prefix) or not zp.is_file():
                continue
            try:
                title, got = _read_iconify(zp, prefix)
            except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                title, got = prefix, {}
            if got:
                sets[prefix] = {"name": title, "from": "custom_icons", "icons": got}
    for path in _script_files(config_dir):
        try:
            found = read_script_set(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            found = None
        if not found:
            continue
        prefix, got = found
        if prefix in RESERVED or prefix in sets:
            print(f"icons: {path.parent.name} uses the prefix {prefix}:, which another set has; left out", flush=True)
            continue
        if got:
            sets[prefix] = {"name": _title(path.parent.name), "from": "script", "icons": got}
    return sets


def copy_custom(config_dir: Path | None = None, on: frozenset[str] | None = None, *, force: bool = False) -> str:
    """Copy every custom set again when their files or Custom Icons' switches changed (whole), and
    use them. `on`: the collections switched on (`collections_on`); None when Home Assistant
    couldn't say, which keeps the last answer, else Custom Icons' own defaults. Blocking: run it
    off the event loop."""
    config_dir = config_dir or config.HA_CONFIG_DIR
    state = _read_state()
    if on is None:
        known = state.get("custom_on")
        on = frozenset(known) if isinstance(known, list) else CUSTOM_ICONS_DEFAULTS
    sig = custom_signature(config_dir, on)
    if not force and state.get("custom_signature") == sig:
        return "unchanged"
    sets = read_custom_sets(config_dir, on)
    _write_json(icon_dir() / "custom.json.gz", sets, compress=True)
    for s in icons.sets():
        if s["prefix"] not in RESERVED and s["prefix"] not in sets:
            icons.remove(s["prefix"])
    for prefix, data in sets.items():
        icons.install(prefix, data)
    state = _read_state()
    state.update(custom_signature=sig, custom_on=sorted(on))
    _write_json(_state_path(), state)
    return ", ".join(f"{p}: {len(d['icons'])}" for p, d in sets.items()) or "none"


# ------------------------------------------------------------------ the loop

async def keep_in_step(session, hass) -> None:
    """At start and every few minutes: Home Assistant's set when its version changed, custom sets
    when their files did. A failure keeps what's in use and shows in the problem sensors."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            on = await collections_on(hass)
            said = await loop.run_in_executor(None, lambda: copy_custom(None, on))
            if said != "unchanged":
                print(f"icons: custom sets: {said}", flush=True)
        except Exception as exc:                    # noqa: BLE001 -- a bad file never stops the add-on
            print(f"icons: custom sets not copied: {health.describe(exc)}", flush=True)
        if hass is not None and hass.available:
            try:
                said = await copy_home_assistant(session, hass)
                if said != "unchanged":
                    print(f"icons: Home Assistant's set: {said}", flush=True)
                health.ok(HEALTH)
            except Exception as exc:                # noqa: BLE001
                health.fail(HEALTH, exc)
        await asyncio.sleep(CHECK_EVERY)
