"""The token that protects frames on the LAN port.

Every install has one: the `frame_token` option if set, otherwise one the
add-on generates on first start and keeps in /data. Panel setup puts it in the
panel's download address.

Switching an existing panel over must never leave it blank, so until the
panel first asks *with* the token, frames are still served without it. The
first request that carries it switches protection on for good (remembered in
/data). An explicitly set `frame_token` option is required from the start.
"""
from __future__ import annotations

import hmac
import secrets

import config

TOKEN_FILE = "frame_token"
SEEN_FILE = "frame_token_in_use"


def token() -> str:
    if config.FRAME_TOKEN:
        return config.FRAME_TOKEN
    path = config.DATA_DIR / TOKEN_FILE
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    new = secrets.token_urlsafe(24)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new)
    tmp.chmod(0o600)
    tmp.replace(path)
    return new


def required() -> bool:
    """Whether a request without the token is refused."""
    return bool(config.FRAME_TOKEN) or (config.DATA_DIR / SEEN_FILE).exists()


def check(provided: str) -> str:
    """'ok', 'missing' or 'wrong' for a request's token, switching protection on
    the first time the right one is seen."""
    if not provided:
        return "missing"
    # Bytes, not str: compare_digest raises on non-ASCII text (a 500 for anyone
    # who sends ?token=é).
    if not hmac.compare_digest(provided.encode("utf-8", "replace"), token().encode()):
        return "wrong"
    seen = config.DATA_DIR / SEEN_FILE
    if not seen.exists():
        seen.write_text("1")
        print("frames: the panel now uses its token; frames require it from now on", flush=True)
    return "ok"


def status() -> str:
    return "on" if required() else "waiting for the panel"
