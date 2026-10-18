"""Self-contained, zero-dependency ISO/IEC 18004 QR Code matrix generator (Versions 1-6, ECC Level M/L)."""

# Capabilities for Byte mode: (version, total_codewords, ec_codewords_per_block, num_blocks, ec_level_bits)
# Using ECC Level M (00) for v1-v4, ECC Level L (01) for v5-v6 to fit up to 134 bytes (Wi-Fi strings, URLs, etc.)
_VERSIONS = [
    # (ver, size, data_cw, ec_cw_per_blk, num_blks, fmt_ec_bits, align_centers)
    (1, 21, 16, 10, 1, 0b00, []),
    (2, 25, 28, 16, 1, 0b00, [6, 18]),
    (3, 29, 44, 26, 1, 0b00, [6, 22]),
    (4, 33, 64, 18, 2, 0b00, [6, 26]),
    (5, 37, 108, 26, 1, 0b01, [6, 30]),
    (6, 41, 136, 18, 2, 0b01, [6, 34]),
]

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_gen_poly(nsym: int) -> list[int]:
    g = [1]
    for i in range(nsym):
        ng = [0] * (len(g) + 1)
        factor = _GF_EXP[i]
        for j, coeff in enumerate(g):
            ng[j] ^= coeff
            ng[j + 1] ^= _gf_mul(coeff, factor)
        g = ng
    return g


def _rs_encode(data: list[int], nsym: int) -> list[int]:
    gen = _rs_gen_poly(nsym)
    res = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


def _bch_format(fmt_val: int) -> int:
    d = fmt_val << 10
    g = 0b10100110111
    for i in range(14, 9, -1):
        if d & (1 << i):
            d ^= g << (i - 10)
    return ((fmt_val << 10) | d) ^ 0b101010000010010


def encode_qr_matrix(text: str) -> list[list[bool]]:
    """Encode string into a 2D boolean QR matrix (True = black module, False = white module)."""
    raw = (text or "https://home-assistant.io").encode("utf-8")
    if len(raw) > 134:
        raw = raw[:134]

    chosen = _VERSIONS[-1]
    for v in _VERSIONS:
        if len(raw) + 2 <= v[2]:
            chosen = v
            break
    ver, size, total_data_cw, ec_cw, num_blks, ec_bits, align_pos = chosen

    # Build bit stream: 0100 (Byte mode) + 8-bit length + bytes + terminator + pad
    bits: list[int] = [0, 1, 0, 0]
    for shift in range(7, -1, -1):
        bits.append((len(raw) >> shift) & 1)
    for b in raw:
        for shift in range(7, -1, -1):
            bits.append((b >> shift) & 1)
    max_bits = total_data_cw * 8
    for _ in range(min(4, max_bits - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords: list[int] = []
    for i in range(0, len(bits), 8):
        val = 0
        for b in bits[i:i + 8]:
            val = (val << 1) | b
        codewords.append(val)

    pad_bytes = [0xEC, 0x11]
    p_idx = 0
    while len(codewords) < total_data_cw:
        codewords.append(pad_bytes[p_idx % 2])
        p_idx += 1

    # Split into blocks and compute Reed-Solomon EC codewords
    blk_len = total_data_cw // num_blks
    data_blocks = []
    ec_blocks = []
    for b in range(num_blks):
        blk = codewords[b * blk_len:(b + 1) * blk_len]
        data_blocks.append(blk)
        ec_blocks.append(_rs_encode(blk, ec_cw))

    # Interleave data & EC blocks
    final_cw: list[int] = []
    for i in range(blk_len):
        for b in range(num_blks):
            final_cw.append(data_blocks[b][i])
    for i in range(ec_cw):
        for b in range(num_blks):
            final_cw.append(ec_blocks[b][i])

    final_bits: list[int] = []
    for cw in final_cw:
        for shift in range(7, -1, -1):
            final_bits.append((cw >> shift) & 1)
    # Remainder bits (7 for v2-v6)
    if ver >= 2:
        final_bits.extend([0] * 7)

    grid: list[list[int]] = [[0] * size for _ in range(size)]
    reserved: list[list[bool]] = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int):
        if 0 <= r < size and 0 <= c < size:
            grid[r][c] = 1 if val else 0
            reserved[r][c] = True

    # Finder patterns + separators
    for fr, fc in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = fr + dr, fc + dc
                if 0 <= r < size and 0 <= c < size:
                    in_outer = 0 <= dr <= 6 and 0 <= dc <= 6
                    if not in_outer:
                        set_mod(r, c, 0)
                    elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                        set_mod(r, c, 1)
                    else:
                        set_mod(r, c, 0)

    # Alignment patterns
    if align_pos:
        for ar in align_pos:
            for ac in align_pos:
                if reserved[ar][ac]:
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                        set_mod(ar + dr, ac + dc, val)

    # Timing patterns
    for i in range(8, size - 8):
        if not reserved[6][i]:
            set_mod(6, i, (i + 1) % 2)
        if not reserved[i][6]:
            set_mod(i, 6, (i + 1) % 2)

    # Dark module & reserve format areas
    set_mod(size - 8, 8, 1)
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
    for i in range(8):
        if not reserved[8][size - 1 - i]:
            reserved[8][size - 1 - i] = True
        if not reserved[size - 1 - i][8]:
            reserved[size - 1 - i][8] = True

    # Place data bits upward/downward in 2-column strips
    bit_idx = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        row_iter = range(size - 1, -1, -1) if up else range(size)
        for r in row_iter:
            for dc in (0, 1):
                c = col - dc
                if not reserved[r][c]:
                    grid[r][c] = final_bits[bit_idx] if bit_idx < len(final_bits) else 0
                    bit_idx += 1
        up = not up
        col -= 2

    # Try masks 0..7 and pick lowest simple run-length penalty
    best_grid = None
    best_penalty = 10**9
    for mask_id in range(8):
        cand = [row[:] for row in grid]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c]:
                    cond = (
                        (r + c) % 2 == 0 if mask_id == 0 else
                        r % 2 == 0 if mask_id == 1 else
                        c % 3 == 0 if mask_id == 2 else
                        (r + c) % 3 == 0 if mask_id == 3 else
                        (r // 2 + c // 3) % 2 == 0 if mask_id == 4 else
                        (r * c) % 2 + (r * c) % 3 == 0 if mask_id == 5 else
                        ((r * c) % 2 + (r * c) % 3) % 2 == 0 if mask_id == 6 else
                        ((r + c) % 2 + (r * c) % 3) % 2 == 0
                    )
                    if cond:
                        cand[r][c] ^= 1

        # Write format bits for this mask
        fmt_bits = _bch_format((ec_bits << 3) | mask_id)
        f_coords_1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
                      (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
        f_coords_2 = [(size - 1 - i, 8) for i in range(7)] + [(8, size - 8 + i) for i in range(8)]
        for i in range(15):
            b = (fmt_bits >> i) & 1
            r1, c1 = f_coords_1[i]
            r2, c2 = f_coords_2[i]
            cand[r1][c1] = b
            cand[r2][c2] = b

        # Evaluate penalty
        pen = 0
        for r in range(size):
            run = 1
            for c in range(1, size):
                if cand[r][c] == cand[r][c - 1]:
                    run += 1
                    if run == 5:
                        pen += 3
                    elif run > 5:
                        pen += 1
                else:
                    run = 1
        for c in range(size):
            run = 1
            for r in range(1, size):
                if cand[r][c] == cand[r - 1][c]:
                    run += 1
                    if run == 5:
                        pen += 3
                    elif run > 5:
                        pen += 1
                else:
                    run = 1
        if pen < best_penalty:
            best_penalty = pen
            best_grid = cand

    return [[bool(cell) for cell in row] for row in (best_grid or grid)]
