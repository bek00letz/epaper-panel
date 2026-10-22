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
- **Custom sets**, each copied whole when its files change. Nothing else needs
  to be installed (the user's design, 22 Oct: e-paper no longer depends on
  Custom Icons, whose Iconify download breaks other integrations):
  - Your own icons (`local:`): SVG files in `<config>/epaper/icons`, which
    the editor's Add icons saves into as cleaned copies, and in Custom Icons'
    old folder `<config>/custom_icons`, still read (the own folder wins).
  - Iconify sets the user chooses in the editor (Settings › Icons), one
    prefix each. Each is downloaded on its own from Iconify's published
    files, only when asked, and converted once. A set Custom Icons'
    download (`custom_icons/iconify-icon-sets-master.zip`) has is taken
    from there instead, without the internet.
  - Script sets that HACS installs under `<config>/www/community`, written
    the way custom-brand-icons (`phu:`) and its kin are: a `var icons = {}`
    of name -> [x, y, w, h, path] and `window.customIcons["prefix"]`.
  A custom icon is its outline only (render/vector): nothing in an SVG runs,
  is fetched or is shown as it is, here or in the editor.

Only an Iconify download reaches the internet, and only when the user asks:
Home Assistant is on the add-on's own network, and its configuration folder
is mapped in.
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import math
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import aiohttp

import config
import health
import services
from render import icons, vector

HEALTH = "Icons from Home Assistant"
FRONTEND = (os.environ.get("HA_FRONTEND") or "http://homeassistant:8123").rstrip("/")
CHECK_EVERY = 300                   # seconds between looking for a new Home Assistant or changed files
RETRY_FIRST = 300                   # a copy of Home Assistant's set that failed: tried again after this,
RETRY_MOST = 4 * 3600               # doubling to this, until it works or Home Assistant's version changes
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
    try:
        chosen_now = chosen()               # the first start after 0.19 keeps the sets it drew (_migrate)
        forget_unchosen()
    except OSError as exc:
        chosen_now = []
        print(f"icons: the chosen sets can't be read ({health.describe(exc)})", flush=True)
    custom = d / "custom.json.gz"
    if custom.exists():
        try:
            for prefix, data in (_read_json(custom, compressed=True) or {}).items():
                if _usable(data) and prefix not in RESERVED:
                    icons.install(prefix, data)
        except (OSError, ValueError, AttributeError) as exc:
            print(f"icons: the custom sets can't be read ({health.describe(exc)}); they'll be copied again", flush=True)
    for prefix in chosen_now:
        try:
            got = _read_json(iconify_dir() / f"{prefix}.json.gz", compressed=True)
        except (OSError, ValueError):
            continue                        # copied again from what's kept, by the first copy_custom
        if _usable(got):
            icons.install(prefix, got)


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
    # A copy that failed isn't fetched again every few minutes (2.7 MB and every outline checked):
    # it waits, longer each time, until it works or Home Assistant's version changes.
    failed = _ha_failed if _ha_failed.get("ha_version") == ha_version else {}
    if failed and _now() < failed["at"]:
        return "waiting"
    try:
        said = await _copy_home_assistant(session, state)
    except Exception:
        wait = min(RETRY_MOST, failed["wait"] * 2) if failed else RETRY_FIRST
        _ha_failed.clear()
        _ha_failed.update(ha_version=ha_version, wait=wait, at=_now() + wait)
        raise
    _ha_failed.clear()
    state.update(ha_version=ha_version)
    _write_json(_state_path(), state)
    return said


# The last failed copy of Home Assistant's set: {ha_version, wait, at} (monotonic seconds), or {}.
_ha_failed: dict = {}
_now = time.monotonic


async def _copy_home_assistant(session, state: dict) -> str:
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
    state.update(mdi_version=version)
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


# ------------------------------------------------------- your own icons

OWN_FOLDER = Path("epaper") / "icons"           # in Home Assistant's configuration folder (the user's call, 22 Oct)
LEGACY_FOLDER = "custom_icons"                  # Custom Icons' folder: still read, so nothing has to move
LEGACY_ZIP = "iconify-icon-sets-master.zip"     # its Iconify download: a set is taken from it once, never fetched


def own_dir(config_dir: Path | None = None) -> Path:
    return (config_dir or config.HA_CONFIG_DIR) / OWN_FOLDER


def _read_local(folder: Path) -> dict:
    """<folder>/**/*.svg, named by their path there without .svg ("pets/cat-outside")."""
    out = {}
    if not folder.is_dir():
        return out
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


def clean_svg(rec) -> str:
    """An outline record as an SVG file holding nothing but that outline: what Add icons saves, so
    nothing else from an uploaded file ever lands in the configuration folder. Reads back the same."""
    d, e, v, strokes = vector.parts(rec)
    num = lambda x: f"{x:.3f}".rstrip("0").rstrip(".")  # noqa: E731
    paths = []
    if d:
        paths.append(f'<path fill="currentColor" d="{d}"/>')
    if e:
        paths.append(f'<path fill="currentColor" fill-rule="evenodd" d="{e}"/>')
    for sd, w in strokes:
        paths.append(f'<path fill="none" stroke="currentColor" stroke-width="{num(w)}" stroke-linecap="round" '
                     f'stroke-linejoin="round" d="{sd}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(num(x) for x in v)}">'
            + "".join(paths) + "</svg>\n")


def own_name(filename: str) -> str:
    """The name an uploaded file is used by ("Paw Paw.svg" -> "Paw Paw"), or "" when nothing's left.
    One folder deep only: no slashes, no leading dots."""
    base = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.svg$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[^\w .+-]+", "-", base).strip(" .-")[:100]
    return base if base and icons.NAME_RE.match(base) else ""


def save_own(files, config_dir: Path | None = None) -> dict:
    """Add icons (the editor): each {"name", "svg"} saved into the own folder as a cleaned copy
    (clean_svg). {"added": [name], "replaced": [name], "refused": [{"file", "why"}]}. Blocking."""
    folder = own_dir(config_dir)
    added, replaced, refused = [], [], []
    for f in files:
        label = str((f or {}).get("name") or "")[:120] or "A file"
        text = (f or {}).get("svg")
        name = own_name(label)
        if not isinstance(text, str) or len(text) > MAX_SVG:
            refused.append({"file": label, "why": "is larger than 512 kB, more than any icon needs"})
            continue
        if not name:
            refused.append({"file": label, "why": "has a name e-paper can't use. Rename it with letters, numbers and dashes"})
            continue
        rec = svg_record(text)
        if rec is None:
            refused.append({"file": label, "why": "has no shapes e-paper can draw. Text and pictures inside an SVG aren't used"})
            continue
        path = folder / f"{name}.svg"
        (replaced if path.exists() else added).append(name)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(clean_svg(rec), encoding="utf-8")
        os.replace(tmp, path)
    return {"added": added, "replaced": replaced, "refused": refused}


# ---------------------------------------------------------- Iconify sets
#
# The user chooses sets in the editor (Settings › Icons). Each is downloaded on its own, only when
# asked (added, Try again, Check for updates), from Iconify's published files, through the add-on's
# own connection. Kept as downloaded (`<prefix>.raw.json.gz`) and converted once
# (`<prefix>.json.gz`), so nothing slow happens when other icons change.

# Iconify's sets, and a few icons of a set for the previews in Add a set: services.py's "iconify"
# (its "main" and "api" addresses), so a mirror the person set is asked instead.
def iconify_base() -> str:
    return services.url("iconify")


def iconify_api() -> str:
    return services.url("iconify", "api")

SAMPLES = 6                                     # icons a preview shows, as Iconify's own list names them
MAX_DOWNLOAD = 32 * 1024 * 1024     # the largest single-color set is about 13 MB
CONVERTER = 1                       # raise when the conversion changes: every set is converted again


def iconify_dir() -> Path:
    return icon_dir() / "iconify"


def _chosen_path() -> Path:
    return icon_dir() / "chosen.json"


def chosen() -> list[str]:
    """The Iconify sets the user has chosen, in the order they were added (the first time, the
    ones the add-on drew from Custom Icons: `_migrate`)."""
    try:
        got = json.loads(_chosen_path().read_text()).get("iconify")
    except (OSError, ValueError, AttributeError):
        got = None
    if not isinstance(got, list):
        got = _migrate()
        _write_json(_chosen_path(), {"iconify": got})
    return _valid_prefixes(got)


def _migrate() -> list[str]:
    """Before e-paper chose its own sets, it drew the Iconify sets Custom Icons had switched on
    (0.18, 0.19). Those it drew are chosen, and their outlines kept as they were, so they draw on
    after Custom Icons and its download are gone."""
    try:
        old = _read_json(icon_dir() / "custom.json.gz", compressed=True)
    except (OSError, ValueError):
        return []
    got = []
    for prefix, data in (old.items() if isinstance(old, dict) else ()):
        if prefix == "local" or not _usable(data) or data.get("from") != "custom_icons" or not _valid_prefixes([prefix]):
            continue
        _write_json(iconify_dir() / f"{prefix}.json.gz", {
            "prefix": prefix, "name": str(data.get("name") or prefix), "from": "iconify", "source": "custom_icons",
            "version": "", "license": "", "converter": CONVERTER, "icons": data["icons"]}, compress=True)
        got.append(prefix)
    return got


def _valid_prefixes(got) -> list[str]:
    out = []
    for p in got or []:
        if isinstance(p, str) and icons.PREFIX_RE.match(p) and p not in RESERVED and p != "local" and p not in out:
            out.append(p)
    return out


def set_chosen(prefixes) -> list[str]:
    got = _valid_prefixes(prefixes)
    _write_json(_chosen_path(), {"iconify": got})
    return got


def _convert_iconify(data) -> tuple[str, dict]:
    """An Iconify set's own name and {name: record}. Iconify's file is {"prefix", "info": {"name"},
    "icons": {name: {"body", "width", ...}}, "aliases": {name: {"parent"}}, "width", ...}. An icon
    turned or flipped by Iconify is left out; an alias without either is its parent's outline."""
    if not isinstance(data, dict) or not isinstance(data.get("icons"), dict):
        raise ValueError("not an Iconify set")
    title = str((data.get("info") or {}).get("name") or data.get("prefix") or "")[:60]
    left, top = data.get("left", 0), data.get("top", 0)
    width, height = data.get("width", 16), data.get("height", 16)
    out = {}
    for name, ic in data["icons"].items():
        if not (isinstance(ic, dict) and isinstance(ic.get("body"), str) and icons.NAME_RE.match(name)):
            continue
        if ic.get("rotate") or ic.get("hFlip") or ic.get("vFlip"):
            continue
        vb = (ic.get("left", left), ic.get("top", top), ic.get("width", width), ic.get("height", height))
        if not all(isinstance(x, (int, float)) for x in vb):
            continue
        rec = svg_record(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}">{ic["body"]}</svg>')
        if rec:
            out[name] = rec
        if len(out) >= MAX_ICONS:
            break
    aliases = data.get("aliases") if isinstance(data.get("aliases"), dict) else {}
    for name, al in aliases.items():
        if len(out) >= MAX_ICONS:
            break
        if not (isinstance(al, dict) and icons.NAME_RE.match(name)) or name in out:
            continue
        if set(al) - {"parent"}:        # turned, flipped or resized: not the parent's outline
            continue
        if al.get("parent") in out:
            out[name] = out[al["parent"]]
    return title, out


def _zip_member(zip_path: Path, prefix: str) -> bytes | None:
    """One set's file from Custom Icons' download, read no further than the size it states."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = f"icon-sets-master/json/{prefix}.json"
            info = zf.getinfo(member)
            if info.file_size > MAX_DOWNLOAD:
                return None
            return zf.read(member)
    except (OSError, KeyError, zipfile.BadZipFile, ValueError):
        return None


def store_iconify(prefix: str, raw: bytes, *, source: str, etag: str = "") -> dict:
    """Keep a set as it came (`source`: "iconify" downloaded, "custom_icons" from its zip) and its
    outlines, both written whole or not at all. Raises ValueError when it isn't that set or has
    nothing to draw. Blocking."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("not an Iconify set") from None
    if not isinstance(data, dict) or data.get("prefix") != prefix:
        raise ValueError("not the set asked for")
    title, got = _convert_iconify(data)
    if not got:
        raise ValueError("no icons e-paper can draw")
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    lic = info.get("license") if isinstance(info.get("license"), dict) else {}
    out = {"prefix": prefix, "name": title or prefix, "from": "iconify", "source": source,
           "version": str(info.get("version") or data.get("lastModified") or "")[:40],
           "license": str(lic.get("title") or "")[:60], "converter": CONVERTER, "icons": got}
    d = iconify_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{prefix}.raw.json.gz.tmp"
    tmp.write_bytes(gzip.compress(raw, 6, mtime=0))
    os.replace(tmp, d / f"{prefix}.raw.json.gz")
    _write_json(d / f"{prefix}.json.gz", out, compress=True)
    state = _read_state()
    meta = state.get("iconify") if isinstance(state.get("iconify"), dict) else {}
    meta[prefix] = {"etag": etag if source == "iconify" else "", "source": source}
    state["iconify"] = meta
    _write_json(_state_path(), state)
    return out


def _iconify_set(prefix: str) -> dict | None:
    """A chosen set's outlines as converted, converted again from the kept download when the
    conversion changed; None when the add-on has neither."""
    d = iconify_dir()
    try:
        got = _read_json(d / f"{prefix}.json.gz", compressed=True)
        if _usable(got) and got.get("converter") == CONVERTER:
            return got
    except (OSError, ValueError):
        pass
    try:
        raw = gzip.decompress((d / f"{prefix}.raw.json.gz").read_bytes())
        source = ((_read_state().get("iconify") or {}).get(prefix) or {})
        return store_iconify(prefix, raw, source=source.get("source") or "iconify", etag=source.get("etag") or "")
    except (OSError, ValueError, EOFError, gzip.BadGzipFile):
        return None


def _iconify_from_zip(config_dir: Path, prefix: str) -> dict | None:
    zp = config_dir / LEGACY_FOLDER / LEGACY_ZIP
    raw = _zip_member(zp, prefix) if zp.is_file() else None
    if raw is None:
        return None
    try:
        return store_iconify(prefix, raw, source="custom_icons")
    except ValueError:
        return None


def forget_unchosen() -> None:
    """At start: copies of sets no longer chosen are deleted (kept until then, so Undo is instant)."""
    keep = set(chosen())
    d = iconify_dir()
    if not d.is_dir():
        return
    for p in d.glob("*.json.gz"):
        prefix = p.name.split(".", 1)[0]
        if prefix not in keep:
            p.unlink(missing_ok=True)


# The way back (the user's call, 22 Oct): True asks Custom Icons which collections are on and reads
# its own choice instead of the editor's, as 0.18 and 0.19 did. Kept, switched off, until e-paper's
# own sets have proven themselves.
ASK_CUSTOM_ICONS = False

# What Custom Icons switches on when it's set up (its config flow): when Home Assistant can't say
# which collections are on, and the add-on never heard before. Only for the way back.
CUSTOM_ICONS_DEFAULTS = frozenset({"local", "fa6-regular", "fa6-solid", "fa6-brands"})


async def collections_on(hass) -> frozenset[str] | None:
    """The collections Custom Icons has switched on, as Home Assistant says (its websocket command
    custom_icons/activesets): empty when it isn't installed or set up; None when Home Assistant
    can't say (unreachable, no key). Never from Home Assistant's own storage files, which hold
    every integration's credentials. Only for the way back (ASK_CUSTOM_ICONS)."""
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


def heard_from_custom_icons(on: frozenset[str] | None) -> frozenset[str]:
    """The way back: Custom Icons' answer, else the last one heard, else its own defaults."""
    state = _read_state()
    if on is None:
        known = state.get("custom_on")
        return frozenset(known) if isinstance(known, list) else CUSTOM_ICONS_DEFAULTS
    state["custom_on"] = sorted(on)
    _write_json(_state_path(), state)
    return on


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



def custom_signature(config_dir: Path, local: bool, iconify: list[str]) -> str:
    """What the custom sets are now (their files' names, sizes and times, and the sets chosen), so
    a change is noticed cheaply."""
    bits = []
    for name, folder in (("own", own_dir(config_dir)), ("legacy", config_dir / LEGACY_FOLDER)):
        if local and folder.is_dir():
            for p in sorted(folder.rglob("*.svg")):
                if p.is_file():
                    s = p.stat()
                    bits.append(f"{name}/{p.relative_to(folder).as_posix()}:{s.st_size}:{int(s.st_mtime)}")
    bits.append(f"local:{int(local)}|on:" + ",".join(iconify))
    zp = config_dir / LEGACY_FOLDER / LEGACY_ZIP
    for prefix in iconify:
        p = iconify_dir() / f"{prefix}.json.gz"
        if p.is_file():
            s = p.stat()
            bits.append(f"{prefix}:{s.st_size}:{int(s.st_mtime)}")
        elif zp.is_file():                          # it may come from Custom Icons' download
            s = zp.stat()
            bits.append(f"zip:{s.st_size}:{int(s.st_mtime)}")
    for p in _script_files(config_dir):
        s = p.stat()
        bits.append(f"{p.relative_to(config_dir).as_posix()}:{s.st_size}:{int(s.st_mtime)}")
    return "|".join(bits)


def read_custom_sets(config_dir: Path, iconify=(), *, local: bool = True) -> dict:
    """Every custom set on this Home Assistant: {prefix: {"name", "from", "icons", ...}}: your own
    icons (`local:`, from the own folder and Custom Icons' folder, the own one first), the chosen
    Iconify sets (`iconify`) the add-on has, taking one from Custom Icons' download when it has
    none yet, and script sets. Sets that can't be read are left out (and said in the log); the
    first of two with one prefix wins."""
    sets: dict[str, dict] = {}
    if local:
        got = {**_read_local(config_dir / LEGACY_FOLDER), **_read_local(own_dir(config_dir))}
        if got:
            sets["local"] = {"name": "Your own icons", "from": "yours", "icons": got}
    for prefix in iconify:
        if prefix in RESERVED or prefix in sets or not icons.PREFIX_RE.match(prefix):
            continue
        got = _iconify_set(prefix) or _iconify_from_zip(config_dir, prefix)
        if got:
            sets[prefix] = got
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


_copying = threading.Lock()


def copy_custom(config_dir: Path | None = None, on: frozenset[str] | None = None, *, force: bool = False) -> str:
    """Copy every custom set again when their files or the chosen sets changed (whole), and use
    them. `on` is only for the way back (ASK_CUSTOM_ICONS): the collections Custom Icons has
    switched on, which then stand for the editor's choice. Blocking: run it off the event loop."""
    config_dir = config_dir or config.HA_CONFIG_DIR
    with _copying:
        if on is None:
            local, iconify = True, chosen()
        else:
            local, iconify = "local" in on, sorted(on - {"local"})
        sig = custom_signature(config_dir, local, iconify)
        state = _read_state()
        if not force and state.get("custom_signature") == sig:
            return "unchanged"
        sets = read_custom_sets(config_dir, iconify, local=local)
        _write_json(icon_dir() / "custom.json.gz", {p: d for p, d in sets.items() if d.get("from") != "iconify"}, compress=True)
        for s in icons.sets():
            if s["prefix"] not in RESERVED and s["prefix"] not in sets:
                icons.remove(s["prefix"])
        for prefix, data in sets.items():
            icons.install(prefix, data)
        own = _read_local(own_dir(config_dir)) if local else {}
        state = _read_state()
        state.update(custom_signature=custom_signature(config_dir, local, iconify), own_count=len(own),
                     legacy_count=len((sets.get("local") or {}).get("icons") or {}) - len(own))
        _write_json(_state_path(), state)
        return ", ".join(f"{p}: {len(d['icons'])}" for p, d in sets.items()) or "none"


# ------------------------------------------------------ downloading sets

class SetError(Exception):
    """Why a set couldn't be had, in words the editor shows as they are."""


_jobs: dict[str, dict] = {}         # prefix -> {"state": "downloading" | "failed", "error"}
_tasks: set = set()                 # running downloads (kept, so none is collected half way)
_check: dict = {}                   # the last Check for updates: {"at", "running", "updated", "failed"}

UNREACHABLE = "Couldn't reach Iconify. Check that Home Assistant is online, then try again."


async def _fetch(session, path: str, etag: str = "", *, base: str | None = None, limit: int = MAX_DOWNLOAD,
                 total: float = 180) -> tuple[bytes | None, str]:
    """A file of Iconify's (bytes, its ETag); (None, etag) when it hasn't changed since `etag`.
    Only from Iconify's own addresses, over checked HTTPS, never redirected, never more than `limit`."""
    headers = {"If-None-Match": etag} if etag else {}
    try:
        async with session.get((base or iconify_base()) + path, headers=headers, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=total, sock_connect=15, sock_read=30)) as r:
            if r.status == 304 and etag:
                return None, etag
            if r.status == 404:
                raise SetError("Iconify doesn't have this set any more.")
            if r.status != 200:
                raise SetError(f"Iconify answered {r.status}. Try again later.")
            if (r.content_length or 0) > limit:
                raise SetError("This set is larger than e-paper accepts (32 MB).")
            buf = bytearray()
            async for chunk in r.content.iter_chunked(1 << 16):
                buf += chunk
                if len(buf) > limit:
                    raise SetError("This set is larger than e-paper accepts (32 MB).")
            return bytes(buf), r.headers.get("ETag", "")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        raise SetError(UNREACHABLE) from None


def _available_from(raw) -> list[dict]:
    """Iconify's list of sets (collections.json) as the ones e-paper offers: single-color only (a
    colored set would draw as solid shapes), not hidden, with a prefix of its own."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("not Iconify's list of sets")
    out = []
    for prefix, c in data.items():
        if not (isinstance(c, dict) and icons.PREFIX_RE.match(prefix)) or prefix in RESERVED or prefix == "local":
            continue
        if c.get("palette") is not False or c.get("hidden"):
            continue
        lic = c.get("license") if isinstance(c.get("license"), dict) else {}
        author = c.get("author") if isinstance(c.get("author"), dict) else {}
        samples = [n for n in (c.get("samples") or []) if isinstance(n, str) and icons.NAME_RE.match(n)][:SAMPLES]
        out.append({"prefix": prefix, "name": str(c.get("name") or prefix)[:60], "total": int(c.get("total") or 0),
                    "license": str(lic.get("title") or "")[:60], "author": str(author.get("name") or "")[:60],
                    "category": str(c.get("category") or "")[:40], "samples": samples})
    return sorted(out, key=lambda s: s["name"].lower())


async def available(session, *, refresh: bool = False) -> list[dict]:
    """The sets the editor offers. Iconify's list is fetched only when asked (the first time Add a
    set opens, or `refresh`), then kept; a failed fetch with a kept list uses the kept one."""
    path = iconify_dir() / "collections.json"
    have = path.read_bytes() if path.is_file() else None
    if have is None or refresh:
        try:
            got, etag = await _fetch(session, "/collections.json", (_read_state().get("collections_etag") or "") if have else "")
            if got is not None:
                _available_from(got)                # it reads, or it isn't kept
                path.parent.mkdir(parents=True, exist_ok=True)
                path.with_name("collections.json.tmp").write_bytes(got)
                os.replace(path.with_name("collections.json.tmp"), path)
                state = _read_state()
                state["collections_etag"] = etag
                _write_json(_state_path(), state)
                have = got
        except (SetError, ValueError):
            if have is None:
                raise SetError(UNREACHABLE) from None
    try:
        return _available_from(have)
    except ValueError:
        path.unlink(missing_ok=True)
        raise SetError("Iconify's list of sets couldn't be read. Try again.") from None


_samples: dict[str, list] | None = None     # prefix -> its sample outlines, in Iconify's order


def _samples_path() -> Path:
    return icon_dir() / "samples.json.gz"         # not with the sets, which forget_unchosen tidies


async def samples(session, prefixes) -> dict[str, list]:
    """Previews for Add a set: each set's sample icons (named in Iconify's list) as outlines,
    {prefix: [record, ...]}. Asked of Iconify only for the sets the editor shows, a few at a time,
    each converted like every other icon and kept; one that can't be had now is left out (the
    editor keeps its empty squares), never an error."""
    global _samples
    if _samples is None:
        try:
            got = _read_json(_samples_path(), compressed=True)
            _samples = got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            _samples = {}
    path = iconify_dir() / "collections.json"
    try:
        names = {s["prefix"]: s["samples"] for s in _available_from(path.read_bytes())} if path.is_file() else {}
    except ValueError:
        names = {}
    wanted = [p for p in dict.fromkeys(prefixes) if p in names and names[p]][:24]
    gate = asyncio.Semaphore(4)
    loop = asyncio.get_running_loop()

    async def one(prefix):
        q = urllib.parse.quote(",".join(names[prefix]), safe=",")
        async with gate:
            raw, _ = await _fetch(session, f"/{prefix}.json?icons={q}", base=iconify_api(), limit=256 * 1024, total=15)
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("prefix") != prefix:
            raise ValueError("not the set asked for")
        _, got = await loop.run_in_executor(None, _convert_iconify, data)
        return [got[n] for n in names[prefix] if n in got]

    missing = [p for p in wanted if p not in _samples]
    if missing:
        got = await asyncio.gather(*(one(p) for p in missing), return_exceptions=True)
        fresh = {p: g for p, g in zip(missing, got) if isinstance(g, list) and g}
        if fresh:
            _samples.update(fresh)
            snapshot = dict(_samples)
            await loop.run_in_executor(None, lambda: _write_json(_samples_path(), snapshot, compress=True))
    return {p: _samples[p] for p in wanted if p in _samples}


async def _get_set(session, prefix: str, *, update: bool = False) -> bool:
    """Make sure the add-on has this chosen set, then use it: one it has already, else from Custom
    Icons' download, else from Iconify. With `update`, ask Iconify whether it changed (a set from
    Custom Icons' download is replaced by Iconify's). True when the set changed. Raises SetError."""
    loop = asyncio.get_running_loop()
    have = await loop.run_in_executor(None, _iconify_set, prefix)
    meta = ((_read_state().get("iconify") or {}).get(prefix) or {})
    changed = False
    if have is None and not update:
        have = await loop.run_in_executor(None, _iconify_from_zip, config.HA_CONFIG_DIR, prefix)
        changed = have is not None
    if have is None or update:
        etag = (meta.get("etag") or "") if have is not None and meta.get("source") == "iconify" else ""
        raw, new_etag = await _fetch(session, f"/json/{prefix}.json", etag)
        if raw is not None:
            try:
                await loop.run_in_executor(None, lambda: store_iconify(prefix, raw, source="iconify", etag=new_etag))
            except ValueError:
                raise SetError("Iconify sent something that isn't this icon set. Try again later.") from None
            changed = True
    await loop.run_in_executor(None, lambda: copy_custom(force=True))
    return changed


def _start(session, prefix: str, *, update: bool = False):
    if (_jobs.get(prefix) or {}).get("state") == "downloading":
        return None
    _jobs[prefix] = {"state": "downloading"}

    async def run():
        try:
            changed = await _get_set(session, prefix, update=update)
            _jobs.pop(prefix, None)
            return changed
        except SetError as exc:
            _jobs[prefix] = {"state": "failed", "error": str(exc)}
        except Exception as exc:                    # noqa: BLE001 -- said, never a stuck "Downloading"
            print(f"icons: {prefix} not copied: {health.describe(exc)}", flush=True)
            _jobs[prefix] = {"state": "failed", "error": "Something went wrong copying this set. Try again."}
        return None
    task = asyncio.get_running_loop().create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def add(session, prefix: str, *, wait: float = 0):
    """Choose a set (or try it again) and get it in the background, waiting up to `wait` seconds
    so one the add-on has at hand is ready in the answer, never a flash of "Downloading". Raises
    SetError when Iconify doesn't offer it as a single-color set."""
    if prefix not in chosen():
        offered = {s["prefix"] for s in await available(session)}
        if prefix not in offered:
            raise SetError("Iconify has no single-color set by that name.")
        set_chosen(chosen() + [prefix])
    task = _start(session, prefix)
    if task is not None and wait > 0:
        await asyncio.wait({task}, timeout=wait)


async def remove(prefix: str) -> None:
    """Stop using a set. Its copy stays until the next start, so adding it back is instant."""
    set_chosen([p for p in chosen() if p != prefix])
    _jobs.pop(prefix, None)
    await asyncio.get_running_loop().run_in_executor(None, lambda: copy_custom(force=True))


async def check_updates(session) -> None:
    """Check for updates (the editor): every chosen set, asking Iconify only whether it changed."""
    if _check.get("running"):
        return
    _check.clear()
    _check.update(running=True, at=time.time(), updated=[], failed=[])

    async def run():
        try:
            for prefix in chosen():
                task = _start(session, prefix, update=True)
                if task is None:
                    continue
                changed = await task
                name = (icons.set_for(prefix) or {}).get("name") or prefix
                if (_jobs.get(prefix) or {}).get("state") == "failed":
                    _check["failed"].append(name)
                elif changed:
                    _check["updated"].append(name)
        finally:
            _check["running"] = False
    task = asyncio.get_running_loop().create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def status(config_dir: Path | None = None) -> dict:
    """What Settings › Icons shows: your own icons, the chosen sets and how each is doing."""
    state = _read_state()
    meta = state.get("iconify") if isinstance(state.get("iconify"), dict) else {}
    sets = []
    for prefix in chosen():
        s = icons.set_for(prefix) or {}
        job = _jobs.get(prefix) or {}
        sets.append({"prefix": prefix, "name": s.get("name") or prefix, "count": len(s.get("icons") or {}),
                     "license": s.get("license") or "",
                     "source": (meta.get(prefix) or {}).get("source") or s.get("source") or "",
                     "state": job.get("state") or ("ready" if s else "missing"), "error": job.get("error") or ""})
    return {"own": {"folder": OWN_FOLDER.as_posix(), "count": int(state.get("own_count") or 0),
                    "legacy_folder": LEGACY_FOLDER, "legacy": max(0, int(state.get("legacy_count") or 0))},
            "sets": sets, "check": {k: _check[k] for k in ("at", "running", "updated", "failed") if k in _check}}


# ------------------------------------------------------------------ the loop

async def keep_in_step(session, hass) -> None:
    """At start and every few minutes: Home Assistant's set when its version changed, custom sets
    when their files did. A failure keeps what's in use and shows in the problem sensors. Never
    downloads an Iconify set: that's only when the user asks."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            on = heard_from_custom_icons(await collections_on(hass)) if ASK_CUSTOM_ICONS else None
            said = await loop.run_in_executor(None, lambda: copy_custom(None, on))
            if said != "unchanged":
                print(f"icons: custom sets: {said}", flush=True)
        except Exception as exc:                    # noqa: BLE001 -- a bad file never stops the add-on
            print(f"icons: custom sets not copied: {health.describe(exc)}", flush=True)
        if hass is not None and hass.available:
            try:
                said = await copy_home_assistant(session, hass)
                if said == "waiting":
                    pass                            # still failing as far as anyone knows: health unchanged
                else:
                    if said != "unchanged":
                        print(f"icons: Home Assistant's set: {said}", flush=True)
                    health.ok(HEALTH)
            except Exception as exc:                # noqa: BLE001
                health.fail(HEALTH, exc)
        await asyncio.sleep(CHECK_EVERY)
