"""The self-describing metadata rows under the frames strip.

`frames.png` is every slice of the rotation stacked vertically, followed by a
few rows of 1-bit metadata: a byte stream laid out row-major, one bit per
pixel, MSB first, black = 1. The panel reads it from the same PSRAM buffer as
the pixels, so structure and content can never arrive out of step.

Byte stream (version 2)::

    0        0xA5 magic
    1        version
    2        N, the number of categories (1..30)
    3..      N x (offset, size, pill_width)         | the v1 prefix. Always fits
             quiet hours flag (0xA5 quiet, 0x00)    | in row 0, which is all that
             rotate_seconds (hi, lo)                | v1 firmware reads, so old
             content hash (hi, lo)                  | panels keep working.
             flags (bit 0: an alert owns the screen)
             P, the number of slices (hi, lo)
             N x category identity (u32, big-endian)
             P x slice identity (u32, big-endian)
             CRC-8 of every preceding byte

Identities are what make navigation survive the rotation changing under it:
the panel remembers *which* category and slice it is showing, not their
positions, and finds them again after every fetch. See
`firmware/panel_core.h` for the reader, and `subitems.py` for where the keys
come from.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

MAGIC = 0xA5
VERSION = 2
QUIET_ON = 0xA5
FLAG_INTERRUPT = 0x01

# Hard limits of the format: v1 firmware rejects more than 30 categories, and
# offsets are a single byte.
MAX_CATEGORIES = 30
MAX_PAGES = 255


def identity(key: str) -> int:
    """32-bit identity for a category or slice key. Stable across processes."""
    return int.from_bytes(hashlib.blake2s(key.encode("utf-8"), digest_size=4).digest(), "big")


def crc8(data) -> int:
    """CRC-8, polynomial 0x07, initial value 0. Mirrored in panel_core.h."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


@dataclass
class StripMeta:
    offsets: list[int]
    sizes: list[int]
    pill_widths: list[int]
    cat_ids: list[int]
    sub_ids: list[int]
    quiet: bool = False
    rotate_seconds: int = 30
    content_hash: int = 0
    interrupt: bool = False
    # Set by decode(): False when the stream carried no usable identities.
    has_identity: bool = field(default=True, compare=False)

    @property
    def page_count(self) -> int:
        return sum(self.sizes)

    def validate(self) -> None:
        n = len(self.offsets)
        if not 1 <= n <= MAX_CATEGORIES:
            raise ValueError(f"{n} categories; the strip format allows 1..{MAX_CATEGORIES}")
        if not (len(self.sizes) == len(self.pill_widths) == len(self.cat_ids) == n):
            raise ValueError("per-category lists differ in length")
        running = 0
        for off, size in zip(self.offsets, self.sizes):
            if off != running or size < 1:
                raise ValueError(f"categories are not contiguous at offset {off}")
            running += size
        if running > MAX_PAGES:
            raise ValueError(f"{running} slices; the strip format allows {MAX_PAGES}")
        if len(self.sub_ids) != running:
            raise ValueError(f"{len(self.sub_ids)} slice identities for {running} slices")
        if len(set(self.cat_ids)) != n:
            raise ValueError("category identities collide")
        for off, size in zip(self.offsets, self.sizes):
            if len(set(self.sub_ids[off:off + size])) != size:
                raise ValueError(f"slice identities collide in the category at offset {off}")


def encode(meta: StripMeta) -> bytes:
    meta.validate()
    out = bytearray([MAGIC, VERSION, len(meta.offsets)])
    for off, size, pill in zip(meta.offsets, meta.sizes, meta.pill_widths):
        out += bytes([off, size, max(0, min(255, int(pill)))])
    rot = max(5, min(3600, int(meta.rotate_seconds)))
    out += bytes([QUIET_ON if meta.quiet else 0x00, rot >> 8, rot & 0xFF,
                  (meta.content_hash >> 8) & 0xFF, meta.content_hash & 0xFF])
    pages = meta.page_count
    out += bytes([FLAG_INTERRUPT if meta.interrupt else 0x00, pages >> 8, pages & 0xFF])
    for ident in (*meta.cat_ids, *meta.sub_ids):
        out += (ident & 0xFFFFFFFF).to_bytes(4, "big")
    out.append(crc8(out))
    return bytes(out)


def decode(data: bytes, pages: int) -> StripMeta:
    """Reference reader, deliberately shaped like PanelCore::parse().

    Raises ValueError where the firmware would fall back to positional
    navigation with no metadata at all. Returns `has_identity=False` where the
    firmware would keep the structure but navigate by position.
    """
    def byte(i: int) -> int:
        if i >= len(data):
            raise ValueError("metadata truncated")
        return data[i]

    if byte(0) != MAGIC:
        raise ValueError("no metadata magic")
    version, n = byte(1), byte(2)
    if not 1 <= n <= MAX_CATEGORIES:
        raise ValueError(f"bad category count {n}")
    offsets, sizes, pills = [], [], []
    running = 0
    for i in range(n):
        off, size, pill = byte(3 + 3 * i), byte(4 + 3 * i), byte(5 + 3 * i)
        if off != running or size < 1:
            raise ValueError("categories are not contiguous")
        offsets.append(off)
        sizes.append(size)
        pills.append(pill or 110)
        running += size
    if running != pages:
        raise ValueError(f"metadata describes {running} slices, image holds {pages}")
    base = 3 + 3 * n
    meta = StripMeta(
        offsets=offsets, sizes=sizes, pill_widths=pills, cat_ids=[], sub_ids=[],
        quiet=byte(base) == QUIET_ON,
        rotate_seconds=(byte(base + 1) << 8) | byte(base + 2),
        content_hash=(byte(base + 3) << 8) | byte(base + 4),
        has_identity=False,
    )
    if version < 2:
        return meta
    try:
        ext = base + 5
        flags = byte(ext)
        if ((byte(ext + 1) << 8) | byte(ext + 2)) != pages:
            return meta
        pos = ext + 3
        ids = []
        for _ in range(n + pages):
            ids.append(int.from_bytes(bytes(byte(pos + k) for k in range(4)), "big"))
            pos += 4
        if crc8(data[:pos]) != byte(pos):
            return meta
    except ValueError:
        return meta
    meta.cat_ids, meta.sub_ids = ids[:n], ids[n:]
    meta.interrupt = bool(flags & FLAG_INTERRUPT)
    meta.has_identity = True
    return meta


def rows_needed(n_bytes: int, width: int) -> int:
    return max(1, -(-n_bytes * 8 // width))


def paint(img, meta_y: int, data: bytes) -> None:
    """Write `data` into a mode-"1" image from row `meta_y` down."""
    w = img.width
    for i, byte_val in enumerate(data):
        for b in range(8):
            p = i * 8 + b
            # PIL mode "1": 0 = black = bit set; ESPHome reads it as red < 128.
            img.putpixel((p % w, meta_y + p // w), 0 if (byte_val >> (7 - b)) & 1 else 1)


def read(img, meta_y: int) -> bytes:
    """Read every whole byte from row `meta_y` to the bottom of the image."""
    w = img.width
    n_bytes = (img.height - meta_y) * w // 8
    out = bytearray()
    for i in range(n_bytes):
        val = 0
        for b in range(8):
            p = i * 8 + b
            if img.getpixel((p % w, meta_y + p // w)) == 0:
                val |= 1 << (7 - b)
        out.append(val)
    return bytes(out)
