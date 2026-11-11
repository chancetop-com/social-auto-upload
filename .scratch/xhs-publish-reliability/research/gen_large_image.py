"""Ticket 24 helper — generate an incompressible PNG of a target size.

    .venv/bin/python .scratch/xhs-publish-reliability/research/gen_large_image.py \
        --out .local/probe/test_20mb.png --mb 20

No third-party deps: writes a truecolor PNG with filter 0 over random bytes,
so zlib cannot shrink it (size ~= raw size).
"""
from __future__ import annotations

import argparse
import os
import struct
import zlib
from pathlib import Path


def chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def make_png(path: Path, width: int, height: int) -> int:
    raw = bytearray()
    row = width * 3
    for _ in range(height):
        raw += b"\x00"
        raw += os.urandom(row)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return len(png)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--mb", type=float, default=20.0)
    ap.add_argument("--width", type=int, default=2600)
    args = ap.parse_args()

    # RGB bytes needed ~= mb * 1024^2 (plus one filter byte per row)
    height = max(1, int(args.mb * 1024 * 1024 / (args.width * 3)))
    size = make_png(Path(args.out), args.width, height)
    print(f"{args.out}: {size / (1024 * 1024):.2f} MiB ({args.width}x{height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
