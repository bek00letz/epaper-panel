"""Talking to Home Assistant: REST and one-shot websocket commands.

A small transport object, so the code that decides *what* to say to Home
Assistant can be tested without a Home Assistant.
"""
from __future__ import annotations

import itertools

import aiohttp


class HassError(Exception):
    """Home Assistant refused or failed a request. `status` is the HTTP code, 0 for network errors."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class Hass:
    def __init__(self, base: str, token: str, session_getter):
        self.base = base.rstrip("/")
        self.token = token
        self._session = session_getter
        self._ids = itertools.count(1)

    @property
    def available(self) -> bool:
        return bool(self.token) and self._session() is not None

    async def rest(self, method: str, path: str, json=None, timeout: float = 15):
        """Call `/api<path>`. Returns the decoded body; raises HassError on any failure."""
        session = self._session()
        if not self.token or session is None:
            raise HassError("not connected to Home Assistant")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            async with session.request(method, f"{self.base}/api{path}", headers=headers, json=json,
                                       timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                text = await r.text()
                if r.status >= 400:
                    raise HassError(text.strip()[:300] or r.reason or "request failed", r.status)
                if not text:
                    return None
                try:
                    return await r.json(content_type=None)
                except Exception:
                    return text
        except HassError:
            raise
        except Exception as exc:
            raise HassError(f"{type(exc).__name__}: {exc}") from exc

    async def ws(self, payload: dict, timeout: float = 10):
        """Run one websocket command and return its `result`; raises HassError on failure."""
        session = self._session()
        if not self.token or session is None:
            raise HassError("not connected to Home Assistant")
        url = self.base.replace("http://", "ws://").replace("https://", "wss://") + "/websocket"
        try:
            async with session.ws_connect(url, timeout=timeout) as ws:
                await ws.receive_json(timeout=timeout)
                await ws.send_json({"type": "auth", "access_token": self.token})
                if (await ws.receive_json(timeout=timeout)).get("type") != "auth_ok":
                    raise HassError("websocket authentication failed", 401)
                msg_id = next(self._ids)
                await ws.send_json({**payload, "id": msg_id})
                while True:
                    msg = await ws.receive_json(timeout=timeout)
                    if msg.get("id") != msg_id:
                        continue
                    if not msg.get("success", False):
                        err = msg.get("error") or {}
                        raise HassError(err.get("message") or "websocket command failed")
                    return msg.get("result")
        except HassError:
            raise
        except Exception as exc:
            raise HassError(f"{type(exc).__name__}: {exc}") from exc
