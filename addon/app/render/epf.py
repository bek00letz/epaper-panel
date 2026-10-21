"""Binary E-Paper Frame (.epf) Protocol v3.0

High-performance, zero-decode binary container format for CrowPanel displays.
Provides stride-aligned 1-bit scanline memory layout for direct DMA/memcpy
streaming on microcontrollers with zero CPU decompression overhead.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Sequence
from PIL import Image

try:
    from . import theme as T
except ImportError:                     # imported as a top-level module
    from render import theme as T

# 64-byte aligned header constants
MAGIC = b"EPAP"  # 0x45504150
VERSION = 3
HEADER_SIZE = 64
CAT_RECORD_SIZE = 16
PAGE_RECORD_SIZE = 16
CRC_SIZE = 4

# Each board's id in a frame file, from its profile (theme.DISPLAYS "frame_model").
MODEL_MAP = {d: p["frame_model"] for d, p in T.DISPLAYS.items() if "frame_model" in p}

MODEL_REV_MAP = {v: k for k, v in MODEL_MAP.items()}

# Flags
FLAG_ALERT_INTERRUPT = 0x0001
FLAG_QUIET_HOURS = 0x0002
FLAG_FORCE_FULL = 0x0004
FLAG_ORIENTATION_180 = 0x0008
FLAG_GEOMETRY = 0x0010          # the reserved header bytes carry an OverlayGeometry

# Category flags (EpfCategory.flags)
CAT_FLAG_SLEEP = 0x0001         # the sleep screen (always category 0 when present)
CAT_FLAG_SLEEP_AUTO = 0x0002    # quiet hours: the panel should be asleep now

# Panels whose frame buffer stores each row right-to-left (the CrowPanel
# driver's mirror_x; the profile's "mirrored"). Pages are flipped before
# packing so a straight memcpy into the buffer shows them the right way round.
MIRRORED_MODELS = tuple(d for d, p in T.DISPLAYS.items() if p.get("mirrored"))

HEADER_FMT = ">4sHHHHHHHHIQIII"          # 44 bytes, then 20 reserved
GEOMETRY_FMT = ">HHBBHHHHH4x"             # 20 bytes in the reserved area


# What a panel can hold when it hasn't said (firmware before 0.10.1 has two
# 1 MiB buffers and doesn't report its size).
DEFAULT_CAPACITY = 1024 * 1024


def encoded_size(pages: int, cats: int, page_bytes: int) -> int:
    """The size of a frame file with this many pages and categories."""
    return HEADER_SIZE + cats * CAT_RECORD_SIZE + pages * (PAGE_RECORD_SIZE + page_bytes) + CRC_SIZE


@dataclass(frozen=True)
class OverlayGeometry:
    """How the panel finds the footer pills it highlights.

    Everything in logical (pre-rotation) pixels, plus the transform from
    logical to physical buffer coordinates. The server drew the footer, so it
    is the only side that knows where things are; the firmware just applies it.
    """
    logical_w: int
    logical_h: int
    quarter_turns: int       # orientation setting / 90: 0, 1 (90°), 2 (180°), 3 (270°)
    mirror_x: bool
    pill_y0: int
    pill_y1: int
    cat_x0: int
    sub_x0: int
    sub_x1: int

    def pack(self) -> bytes:
        return struct.pack(GEOMETRY_FMT, self.logical_w, self.logical_h, self.quarter_turns & 3,
                           1 if self.mirror_x else 0, self.pill_y0, self.pill_y1,
                           self.cat_x0, self.sub_x0, self.sub_x1)

    @classmethod
    def unpack(cls, raw: bytes) -> "OverlayGeometry":
        lw, lh, q, tf, y0, y1, cx0, sx0, sx1 = struct.unpack(GEOMETRY_FMT, raw)
        return cls(lw, lh, q & 3, bool(tf & 1), y0, y1, cx0, sx0, sx1)


def to_physical(geo: OverlayGeometry, x: int, y: int) -> tuple[int, int]:
    """Logical pixel -> physical buffer pixel, matching theme.orient_for_panel
    followed by the mirror flip in encode_epf. The firmware implements the same."""
    lw, lh = geo.logical_w, geo.logical_h
    q = geo.quarter_turns & 3
    if q == 0:
        px, py, pw = x, y, lw
    elif q == 1:                     # 90°: PIL ROTATE_270 (a clockwise quarter turn)
        px, py, pw = lh - 1 - y, x, lh
    elif q == 2:                     # 180°
        px, py, pw = lw - 1 - x, lh - 1 - y, lw
    else:                            # 270°: PIL ROTATE_90 (counter-clockwise)
        px, py, pw = y, lw - 1 - x, lh
    if geo.mirror_x:
        px = pw - 1 - px
    return px, py


@dataclass(frozen=True)
class EpfCategory:
    cat_id: int
    offset_page: int
    page_count: int
    pill_width: int = 110
    flags: int = 0


@dataclass(frozen=True)
class EpfPage:
    sub_id: int
    cat_id: int
    cat_index: int
    sub_index: int


@dataclass(frozen=True)
class EpfHeader:
    magic: bytes
    version: int
    model_id: int
    width: int
    height: int
    stride: int
    page_count: int
    cat_count: int
    rotate_sec: int
    flags: int
    content_hash: int
    payload_size: int
    dir_offset: int
    data_offset: int


@dataclass(frozen=True)
class EpfStream:
    header: EpfHeader
    geometry: OverlayGeometry | None
    categories: tuple[EpfCategory, ...]
    pages: tuple[EpfPage, ...]
    pixel_data: bytes
    crc32: int

    def page_slice(self, page_index: int) -> bytes:
        """Return raw scanline bytes for a specific page."""
        if page_index < 0 or page_index >= self.header.page_count:
            raise IndexError(f"Page index {page_index} out of range [0..{self.header.page_count-1}]")
        bytes_per_page = self.header.stride * self.header.height
        start = page_index * bytes_per_page
        return self.pixel_data[start : start + bytes_per_page]


def encode_epf(
    pages: Sequence[Image.Image],
    cat_ids: Sequence[int],
    cat_offsets: Sequence[int],
    cat_sizes: Sequence[int],
    cat_pill_widths: Sequence[int],
    sub_ids: Sequence[int],
    display_model: str = "crowpanel_579",
    width: int = 792,
    height: int = 272,
    rotate_sec: int = 30,
    quiet_hours: bool = False,
    alert_interrupt: bool = False,
    force_full_waveform: bool = False,
    orientation_180: bool = False,
    content_hash: int = 0,
    geometry: OverlayGeometry | None = None,
    cat_flags: Sequence[int] | None = None,
) -> bytes:
    """Encode layout pages and identity directories into an aligned .epf binary buffer."""
    num_pages = len(pages)
    num_cats = len(cat_ids)
    if num_pages == 0:
        raise ValueError("Cannot encode EPF stream with zero pages")
    if num_cats == 0:
        raise ValueError("Cannot encode EPF stream with zero categories")
    if len(sub_ids) != num_pages:
        raise ValueError(f"sub_ids count ({len(sub_ids)}) does not match pages count ({num_pages})")

    stride = (width + 7) // 8
    bytes_per_page = stride * height
    payload_size = bytes_per_page * num_pages
    if display_model not in MODEL_MAP:
        raise ValueError(f"unknown display model {display_model!r}")
    model_id = MODEL_MAP[display_model]

    flags = 0
    if alert_interrupt:
        flags |= FLAG_ALERT_INTERRUPT
    if quiet_hours:
        flags |= FLAG_QUIET_HOURS
    if force_full_waveform:
        flags |= FLAG_FORCE_FULL
    if orientation_180:
        flags |= FLAG_ORIENTATION_180
    if geometry is not None:
        flags |= FLAG_GEOMETRY

    dir_offset = HEADER_SIZE
    cat_dir_size = num_cats * CAT_RECORD_SIZE
    page_dir_size = num_pages * PAGE_RECORD_SIZE
    data_offset = dir_offset + cat_dir_size + page_dir_size

    # 1. Pack Header (64 bytes)
    # 4s magic + 8*H + I flags + Q hash + 3*I sizes = 44 bytes, then 20 bytes of geometry.
    header_bytes = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        model_id,
        width,
        height,
        stride,
        num_pages,
        num_cats,
        max(5, min(3600, int(rotate_sec))),
        flags,
        int(content_hash) & 0xFFFFFFFFFFFFFFFF,
        payload_size,
        dir_offset,
        data_offset,
    ) + (geometry.pack() if geometry is not None else b"\x00" * 20)
    assert len(header_bytes) == HEADER_SIZE, f"Header size mismatch: {len(header_bytes)}"

    # 2. Pack Category Directory
    # struct EpfCategory: uint32 cat_id, uint16 offset, uint16 count, uint16 pill_w, uint16 flags, uint32 res
    cat_records = []
    for c in range(num_cats):
        cid = int(cat_ids[c]) & 0xFFFFFFFF
        off = int(cat_offsets[c]) if c < len(cat_offsets) else c
        sz = int(cat_sizes[c]) if c < len(cat_sizes) else 1
        pw = int(cat_pill_widths[c]) if c < len(cat_pill_widths) else 110
        cf = int(cat_flags[c]) if cat_flags and c < len(cat_flags) else 0
        cat_records.append(struct.pack(">IHHHHI", cid, off, sz, pw, cf, 0))
    cat_bytes = b"".join(cat_records)

    # 3. Pack Page Directory
    # struct EpfPage: uint32 sub_id, uint32 cat_id, uint16 cat_idx, uint16 sub_idx, uint32 res
    page_records = []
    for p in range(num_pages):
        sid = int(sub_ids[p]) & 0xFFFFFFFF
        # Determine parent category
        c_idx = 0
        s_idx = 0
        for c in range(num_cats):
            off = int(cat_offsets[c]) if c < len(cat_offsets) else c
            sz = int(cat_sizes[c]) if c < len(cat_sizes) else 1
            if off <= p < off + sz:
                c_idx = c
                s_idx = p - off
                break
        parent_cid = int(cat_ids[c_idx]) & 0xFFFFFFFF if c_idx < num_cats else 0
        page_records.append(struct.pack(">IIHHI", sid, parent_cid, c_idx, s_idx, 0))
    page_bytes = b"".join(page_records)

    # 4. Pack Scanline Pixel Payload
    # Each Pillow Image must be converted to 1-bit and raw scanlines extracted
    scanline_parts = []
    for p, img in enumerate(pages):
        if img.mode != "1":
            img_1bit = img.convert("1")
        else:
            img_1bit = img
        if img_1bit.size != (width, height):
            padded = Image.new("1", (width, height), 1)
            padded.paste(img_1bit, (0, 0))
            img_1bit = padded
        # CrowPanel hardware scanline orientation for direct DisplayBuffer memcpy:
        # CrowPanel 5.79" (and other mirror_x displays) stores rows in FLIP_LEFT_RIGHT
        # so that a direct std::memcpy into the display buffer matches draw_pixel_at.
        if display_model in MIRRORED_MODELS:
            packed_img = img_1bit.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        else:
            packed_img = img_1bit
        raw = packed_img.tobytes()
        scanline_parts.append(raw)
    pixel_bytes = b"".join(scanline_parts)

    body = header_bytes + cat_bytes + page_bytes + pixel_bytes

    # 5. Compute CRC-32 (IEEE 802.3 standard) over entire stream
    crc_val = zlib.crc32(body) & 0xFFFFFFFF
    crc_bytes = struct.pack(">I", crc_val)

    return body + crc_bytes


def decode_epf(data: bytes) -> EpfStream:
    """Decode and validate an .epf binary buffer."""
    if len(data) < HEADER_SIZE + CRC_SIZE:
        raise ValueError(f"Data buffer too small: {len(data)} bytes (min {HEADER_SIZE + CRC_SIZE})")

    # Verify CRC-32
    body = data[:-CRC_SIZE]
    expected_crc = struct.unpack(">I", data[-CRC_SIZE:])[0]
    computed_crc = zlib.crc32(body) & 0xFFFFFFFF
    if expected_crc != computed_crc:
        raise ValueError(f"CRC-32 checksum mismatch: got 0x{computed_crc:08X}, expected 0x{expected_crc:08X}")

    # Unpack Header
    header_fields = struct.unpack(HEADER_FMT, data[:44])
    magic = header_fields[0]
    if magic != MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}, expected {MAGIC!r}")

    version = header_fields[1]
    if version != VERSION:
        raise ValueError(f"Unsupported EPF version: {version}, expected {VERSION}")

    header = EpfHeader(
        magic=magic,
        version=version,
        model_id=header_fields[2],
        width=header_fields[3],
        height=header_fields[4],
        stride=header_fields[5],
        page_count=header_fields[6],
        cat_count=header_fields[7],
        rotate_sec=header_fields[8],
        flags=header_fields[9],
        content_hash=header_fields[10],
        payload_size=header_fields[11],
        dir_offset=header_fields[12],
        data_offset=header_fields[13],
    )

    # Validate offsets
    cat_dir_start = header.dir_offset
    page_dir_start = cat_dir_start + (header.cat_count * CAT_RECORD_SIZE)
    if header.data_offset != page_dir_start + (header.page_count * PAGE_RECORD_SIZE):
        raise ValueError("Malformed directory offsets in header")

    bytes_per_page = header.stride * header.height
    expected_payload_size = bytes_per_page * header.page_count
    if header.payload_size != expected_payload_size:
        raise ValueError(f"Payload size mismatch: {header.payload_size} != {expected_payload_size}")

    if len(body) != header.data_offset + header.payload_size:
        raise ValueError("Corrupt stream length")

    # Unpack Categories
    categories = []
    pos = cat_dir_start
    for _ in range(header.cat_count):
        cid, off, sz, pw, flg, _ = struct.unpack(">IHHHHI", data[pos : pos + CAT_RECORD_SIZE])
        categories.append(EpfCategory(cat_id=cid, offset_page=off, page_count=sz, pill_width=pw, flags=flg))
        pos += CAT_RECORD_SIZE

    # Unpack Pages
    pages = []
    pos = page_dir_start
    for _ in range(header.page_count):
        sid, cid, c_idx, s_idx, _ = struct.unpack(">IIHHI", data[pos : pos + PAGE_RECORD_SIZE])
        pages.append(EpfPage(sub_id=sid, cat_id=cid, cat_index=c_idx, sub_index=s_idx))
        pos += PAGE_RECORD_SIZE

    pixel_data = body[header.data_offset :]
    geometry = OverlayGeometry.unpack(data[44:HEADER_SIZE]) if header.flags & FLAG_GEOMETRY else None
    return EpfStream(
        header=header,
        geometry=geometry,
        categories=tuple(categories),
        pages=tuple(pages),
        pixel_data=pixel_data,
        crc32=computed_crc,
    )


def extract_page_epf(stream: EpfStream | bytes, page_index: int) -> bytes:
    """Extract a standalone single-page .epf binary stream from an existing stream."""
    if isinstance(stream, bytes):
        stream = decode_epf(stream)

    if page_index < 0 or page_index >= stream.header.page_count:
        raise IndexError(f"Page index {page_index} out of range [0..{stream.header.page_count-1}]")

    target_page = stream.pages[page_index]
    # Find matching category
    target_cat = stream.categories[target_page.cat_index]

    raw_page_bytes = stream.page_slice(page_index)
    bytes_per_page = len(raw_page_bytes)

    dir_offset = HEADER_SIZE
    cat_dir_size = 1 * CAT_RECORD_SIZE
    page_dir_size = 1 * PAGE_RECORD_SIZE
    data_offset = dir_offset + cat_dir_size + page_dir_size

    header_bytes = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        stream.header.model_id,
        stream.header.width,
        stream.header.height,
        stream.header.stride,
        1,  # page_count = 1
        1,  # cat_count = 1
        stream.header.rotate_sec,
        stream.header.flags,
        stream.header.content_hash,
        bytes_per_page,
        dir_offset,
        data_offset,
    ) + (stream.geometry.pack() if stream.geometry is not None else b"\x00" * 20)

    cat_bytes = struct.pack(
        ">IHHHHI",
        target_cat.cat_id,
        0,  # offset_page = 0
        1,  # page_count = 1
        target_cat.pill_width,
        target_cat.flags,
        0,
    )

    page_bytes = struct.pack(
        ">IIHHI",
        target_page.sub_id,
        target_page.cat_id,
        0,  # cat_index = 0
        0,  # sub_index = 0
        0,
    )

    body = header_bytes + cat_bytes + page_bytes + raw_page_bytes
    crc_val = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(">I", crc_val)


def extract_page_image(stream: EpfStream | bytes, page_index: int) -> Image.Image:
    """Extract a single page from an EPF stream and reconstruct the original PIL Image."""
    if isinstance(stream, bytes):
        stream = decode_epf(stream)
    raw = stream.page_slice(page_index)
    im = Image.frombytes("1", (stream.header.width, stream.header.height), raw)
    if stream.header.model_id in tuple(MODEL_MAP[m] for m in MIRRORED_MODELS):
        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return im

