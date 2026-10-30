"""A stand-in for the add-on's HTTP session in tests: answers from saved samples, records what was asked.

No test reaches the network. `route(method, url, data)` returns (status, body, headers): a body
that's a dict or list is sent as JSON, a str or bytes as it is.
"""
import json
from pathlib import Path

from yarl import URL

SAMPLES = Path(__file__).resolve().parent / "samples"


def sample(name: str):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


class _Content:
    def __init__(self, raw: bytes, piece: int | None = None):
        self.raw, self.piece = raw, piece

    async def read(self, n=-1):
        return self.raw if n < 0 else self.raw[:n]

    async def iter_chunked(self, n):
        n = self.piece or n
        for k in range(0, len(self.raw), n):          # in pieces, as a network delivers it
            yield self.raw[k:k + n]


class _Response:
    def __init__(self, url, status, body, headers, piece=None):
        self.url, self.status, self.headers = URL(url), status, headers or {}
        raw = body if isinstance(body, bytes) else body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.content = _Content(raw, piece)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, route, piece: int | None = None):
        self.route, self.asked, self.piece = route, [], piece

    def request(self, method, url, data=None, **kw):
        self.asked.append((method, url, data, kw.get("headers") or {}))
        status, body, headers = self.route(method, url, data)
        return _Response(url, status, body, headers, self.piece)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def urls(self) -> list[str]:
        return [u for _, u, _, _ in self.asked]
