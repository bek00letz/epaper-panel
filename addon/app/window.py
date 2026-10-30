"""The moving window: a panel that can't hold its whole rotation holds the part around the page it
shows, and the add-on hands it the next part as it goes (the user's call, 30 Oct).

For firmware that says `window=1` on its downloads (0.24 and later; components/epf). Everything is
drawn in the render cycle, every item of every page, and kept here as the frame file stores it
(deflated or not); a download only packs the pictures it needs (frames.fit_window, the one rule
in bytes) and draws nothing, so a panel scrolling past what it holds waits for the network, never
for a render.

Where the panel is, it says on each download: `at=<page>&item=<item>` (the page's place in the
rotation, from 0, and the item it shows), or `page=<n>` (Home Assistant's show_page, every item
of every page counted). The window has that page first (CAT_FLAG_AT), from that item, then the
next pages and the one before, each whole while it fits. Each category record says where its page
sits in the rotation (epf.place), so the panel knows what it holds and what it must ask for. A
rotation that fits whole is sent whole, as before: a window is only for one that doesn't.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import frames
from render import epf


@dataclass
class Sleep:
    """The sleep screen as it stores, with its identity and flags (category 0 when it fits)."""
    stored: bytes
    cat_id: int
    sub_id: int
    flags: int


class Window:
    """Every picture of a rotation, as stored, and the window around any page of it.

    `pages[i][k]`: page i's item k as stored; `cat_ids`, `sub_ids[i][k]`, `pill_widths`: as the
    whole file would have them, so a page keeps its identity from one window to the next.
    `header`: pack_epf's keywords for every window (size, flags, geometry). `auto_sleep`: quiet
    hours want the panel asleep, so with no room for the sleep screen beside a page it holds only
    the sleep screen (as a whole file does)."""

    def __init__(self, pages: list[list[bytes]], cat_ids: list[int], sub_ids: list[list[int]],
                 pill_widths: list[int], capacity: int, sleep: Sleep | None, header: dict,
                 auto_sleep: bool = False):
        self.pages, self.cat_ids, self.sub_ids, self.pill_widths = pages, cat_ids, sub_ids, pill_widths
        self.capacity, self.sleep, self.header, self.auto_sleep = capacity, sleep, header, auto_sleep
        self._files: dict[tuple[int, int], tuple[bytes, str]] = {}

    @property
    def wants(self) -> list[int]:
        return [len(p) for p in self.pages]

    def where(self, page: int) -> tuple[int, int]:
        """Home Assistant's show_page counts every item of every page: (page, item) of the nth."""
        for i, n in enumerate(self.wants):
            if page < n:
                return i, page
            page -= n
        raise IndexError("no such page")

    def fit(self, at: int = 0, item: int = 0) -> frames.Fit:
        return frames.fit_window(self.wants, at, item, self.capacity,
                                 None if self.sleep is None else len(self.sleep.stored),
                                 lambda i, k: len(self.pages[i][k]))

    def holds(self) -> int:
        """How many pictures a window holds, from the start of the rotation (the editor's line)."""
        return sum(self.fit().counts)

    def file(self, at: int = 0, item: int = 0, page: int | None = None) -> tuple[bytes, str]:
        """The frame file around `at` and `item` (or Home Assistant's `page`), and its ETag. Packed
        once per render and kept; never drawn."""
        n = len(self.pages)
        if page is not None:
            try:
                at, item = self.where(page)
            except IndexError:
                pass                                   # not a page: the window stays where it is
        at %= n
        item %= self.wants[at]
        key = (at, item)
        if key not in self._files:
            body = self._pack(at, item)
            self._files[key] = body, f'"{hashlib.blake2s(body, digest_size=8).hexdigest()}"'
        return self._files[key]

    def _pack(self, at: int, item: int) -> bytes:
        got = self.fit(at, item)
        n = len(self.pages)
        stored, cat_ids, offsets, sizes, pills, flags, places, sub_ids, items = [], [], [], [], [], [], [], [], []
        only_sleep = self.sleep is not None and self.auto_sleep and not got.sleep_screen
        if self.sleep is not None and (got.sleep_screen or only_sleep):
            stored.append(self.sleep.stored)
            cat_ids.append(self.sleep.cat_id)
            offsets.append(0)
            sizes.append(1)
            pills.append(0)
            flags.append(self.sleep.flags)
            places.append(0)
            sub_ids.append(self.sleep.sub_id)
            items.append(0)
        if not only_sleep:
            before = (at - 1) % n
            start = before if n > 1 and got.counts[before] else at
            for step in range(n):                      # in rotation order, from the one before
                i = (start + step) % n
                if not got.counts[i]:
                    break                              # past the window's far end
                ks = got.items[i]
                offsets.append(len(stored))
                sizes.append(len(ks))
                cat_ids.append(self.cat_ids[i])
                pills.append(self.pill_widths[i])
                flags.append((epf.CAT_FLAG_AT if i == at else 0)
                             | (epf.CAT_FLAG_PART if len(ks) < self.wants[i] else 0))
                places.append(epf.place(i, n))
                for k in ks:
                    stored.append(self.pages[i][k])
                    sub_ids.append(self.sub_ids[i][k])
                    items.append(k)
        return epf.pack_epf(stored, cat_ids, offsets, sizes, pills, sub_ids, cat_flags=flags, cat_places=places,
                            sub_indexes=items, **self.header)
