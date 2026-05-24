#!/usr/bin/env python3
"""Normalize generated images to a fixed PNG canvas."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


def normalize_image(src: Path, dst: Path, size: tuple[int, int]) -> None:
    img = Image.open(src)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, format="PNG", optimize=True)


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = value.lower().split("x", 1)
        return int(width), int(height)
    except Exception as exc:
        raise argparse.ArgumentTypeError("size must look like 1536x1024") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", type=Path)
    parser.add_argument("dst", type=Path)
    parser.add_argument("--size", type=parse_size, default=(1536, 1024))
    args = parser.parse_args()

    normalize_image(args.src, args.dst, args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
