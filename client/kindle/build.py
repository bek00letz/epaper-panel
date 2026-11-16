"""Build the Kindle client's install and uninstall packages: what Update Your Kindle runs.

    python client/kindle/build.py          writes them where the add-on serves them
    python client/kindle/build.py --check  says whether those are up to date (exit 1 if not)

A jailbroken Kindle runs an update package signed with the jailbreak's key
(keys/jailbreak_updater_key.pem: the public key the jailbreak installs is its
other half; it ships in the jailbreak's own package, from MobileRead). The
format is KindleTool's (NiLuJe/KindleTool, create.c), checked against the
MobileRead Kindlet Kit's and USBNetwork's Kindle 4 packages, whose signatures
this reproduces byte for byte (tests/test_kindle_client.py):

  SP01 envelope   "SP01", certificate number (u32, 0: the developer key), zeros to 64 bytes,
                  then an RSA-SHA256 PKCS#1 v1.5 signature of everything after it
  FC04 package    "FC04", source revision (u64, 0), target revision (u64, all ones), the number
                  of devices (u16) and each device's code (u16), critical (u8), a zero byte,
                  the tarball's MD5 (32 hex digits, scrambled), the number of metadata strings
                  (u16, 0), then the tarball, scrambled
  the tarball     each file, a signature of each (<name>.sig), and update-filelist.dat with a line
                  per file: 128 (a file) or 129 (a script it runs), its MD5, its name, its size in
                  64-byte blocks, and "<name>_ktool_file"; and that file's own signature

"Scrambled" is each byte with its two halves swapped, then XOR 0x7A.

Pure Python on purpose: nothing to install, and the same bytes every time
(fixed file times, owners and gzip header), so the packages in the repository
can be checked against these sources.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import struct
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = HERE / "keys" / "jailbreak_updater_key.pem"
OUT = HERE.parents[1] / "addon" / "app" / "kindle"

# Kindle 4 device codes (KindleTool's kindle_tool.h): the silver one (2011) and the black one (2012).
KINDLE_4 = (0x0E, 0x23)

# What each package holds: (name in the package, source file, whether the updater runs it).
INSTALL = [
    ("install.sh", HERE / "package" / "install.sh", True),
    ("epaper-panel.sh", HERE / "root" / "usr" / "local" / "epaper-panel" / "epaper-panel.sh", False),
    ("epaper-panel.init", HERE / "root" / "etc" / "init.d" / "epaper-panel", False),
]
UNINSTALL = [
    ("uninstall.sh", HERE / "package" / "uninstall.sh", True),
]
PACKAGES = {
    "Update_epaper-panel_install.bin": INSTALL,
    "Update_epaper-panel_uninstall.bin": UNINSTALL,
}

MTIME = 1763251200                      # a fixed time (16 Nov 2025) for every file, so builds match
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")   # SHA-256's, for PKCS#1 v1.5


def scramble(data: bytes) -> bytes:
    return data.translate(bytes((((b >> 4) | (b << 4)) & 0xFF) ^ 0x7A for b in range(256)))


def unscramble(data: bytes) -> bytes:
    return data.translate(bytes(((((b ^ 0x7A) >> 4) | ((b ^ 0x7A) << 4)) & 0xFF) for b in range(256)))


def _der(buf: bytes, i: int = 0) -> tuple[int, bytes, int]:
    tag, n = buf[i], buf[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(buf[i:i + k], "big")
        i += k
    return tag, buf[i:i + n], i + n


def load_key(pem: str) -> tuple[int, int, int]:
    """(n, e, d) from a PEM "RSA PRIVATE KEY" (PKCS#1)."""
    raw = base64.b64decode("".join(line for line in pem.splitlines() if line and not line.startswith("-----")))
    _, seq, _ = _der(raw)
    values, i = [], 0
    while i < len(seq):
        _, v, i = _der(seq, i)
        values.append(int.from_bytes(v, "big"))
    return values[1], values[2], values[3]


def sign(data: bytes, key: tuple[int, int, int]) -> bytes:
    n, _, d = key
    size = (n.bit_length() + 7) // 8
    t = _DIGEST_INFO + hashlib.sha256(data).digest()
    block = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(block, "big"), d, n).to_bytes(size, "big")


def verify(data: bytes, signature: bytes, key: tuple[int, int, int]) -> bool:
    n, e, _ = key
    size = (n.bit_length() + 7) // 8
    block = pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big")
    return block.endswith(_DIGEST_INFO + hashlib.sha256(data).digest()) and block[:2] == b"\x00\x01"


def _tarball(files: list[tuple[str, bytes, bool]], key) -> bytes:
    entries: list[tuple[str, bytes, int]] = []
    index = []
    for name, data, runs in files:
        entries.append((name, data, 0o755 if runs else 0o644))
        index.append(f"{129 if runs else 128} {hashlib.md5(data).hexdigest()} {name} {len(data) // 64} {name}_ktool_file")
    for name, data, _ in files:
        entries.append((name + ".sig", sign(data, key), 0o644))
    listing = ("\n".join(index) + "\n").encode()
    entries += [("update-filelist.dat.sig", sign(listing, key), 0o644), ("update-filelist.dat", listing, 0o644)]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name, data, mode in entries:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, MTIME
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def package(files: list[tuple[str, bytes, bool]], key, devices=KINDLE_4) -> bytes:
    """A signed update package holding `files` [(name, bytes, runs)] for `devices`."""
    tgz = _tarball(files, key)
    header = b"FC04" + struct.pack("<QQH", 0, 0xFFFFFFFFFFFFFFFF, len(devices))
    header += b"".join(struct.pack("<H", d) for d in devices)
    header += b"\x00\x00" + scramble(hashlib.md5(tgz).hexdigest().encode()) + struct.pack("<H", 0)
    inner = header + scramble(tgz)
    return b"SP01" + struct.pack("<I", 0) + b"\x00" * 56 + sign(inner, key) + inner


def read_package(data: bytes, key=None) -> dict:
    """What a package holds, checked: {"devices": [...], "files": {name: bytes}, "runs": [names]}.
    Raises ValueError for anything a Kindle would refuse (a bad signature, a wrong checksum)."""
    if data[:4] != b"SP01":
        raise ValueError("not a signed update package")
    inner = data[64 + 128:]
    if key is not None and not verify(inner, data[64:64 + 128], key):
        raise ValueError("its signature isn't the jailbreak key's")
    if inner[:4] != b"FC04":
        raise ValueError(f"not an FC04 package: {inner[:4]!r}")
    count = struct.unpack("<H", inner[20:22])[0]
    devices = list(struct.unpack(f"<{count}H", inner[22:22 + 2 * count]))
    at = 22 + 2 * count + 2
    md5 = unscramble(inner[at:at + 32]).decode()
    tgz = unscramble(inner[at + 32 + 2:])
    if hashlib.md5(tgz).hexdigest() != md5:
        raise ValueError("its checksum doesn't match")
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tar:
        files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    if key is not None:
        for name, body in files.items():
            if not name.endswith(".sig") and not verify(body, files.get(name + ".sig", b""), key):
                raise ValueError(f"{name}'s signature isn't the jailbreak key's")
    runs = [line.split()[2] for line in files.get("update-filelist.dat", b"").decode().splitlines()
            if line.startswith("129 ")]
    return {"devices": devices, "files": files, "runs": runs}


def build() -> dict[str, bytes]:
    key = load_key(KEY.read_text())
    return {name: package([(n, src.read_bytes(), runs) for n, src, runs in files], key)
            for name, files in PACKAGES.items()}


def main(argv: list[str]) -> int:
    built = build()
    if "--check" in argv:
        stale = [n for n, data in built.items() if not (OUT / n).exists() or (OUT / n).read_bytes() != data]
        for n in stale:
            print(f"{n} is out of date: run python client/kindle/build.py")
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in built.items():
        (OUT / name).write_bytes(data)
        print(f"wrote {OUT / name} ({len(data):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
