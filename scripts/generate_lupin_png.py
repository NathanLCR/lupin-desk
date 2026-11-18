#!/usr/bin/env python3
"""Generate Lupin's 480x320 PNGs for the ESP32 from the SVGs in static/lupin/.

The per-layer SVGs are the single source. Each PNG is written with transparency
and 8-bit indexed colors, and is checked against a size budget (default: 20 KB).

Development-only dependencies (not part of the server):

    pip install pillow resvg-py

Usage:

    python scripts/generate_lupin_png.py [--output build/lupin-png] [--limit-kb 20]
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "static" / "lupin"
WIDTH, HEIGHT = 480, 320


def convert(svg: Path, colors: int):
    import resvg_py
    from PIL import Image

    data = bytes(resvg_py.svg_to_bytes(svg_path=str(svg)))
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    if image.size != (WIDTH, HEIGHT):
        raise SystemExit(f"{svg}: expected {WIDTH}x{HEIGHT}, got {image.size}")
    indexed = image.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    buffer = io.BytesIO()
    indexed.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--output", default=str(ROOT / "build" / "lupin-png"))
    parser.add_argument("--limit-kb", type=float, default=20.0)
    parser.add_argument("--colors", type=int, default=64)
    args = parser.parse_args()

    try:
        import PIL  # noqa: F401
        import resvg_py  # noqa: F401
    except ImportError:
        print("Missing dependencies: pip install pillow resvg-py", file=sys.stderr)
        return 2

    output = Path(args.output)
    svgs = sorted(SOURCE.rglob("*.svg"))
    if not svgs:
        print(f"No SVGs in {SOURCE}", file=sys.stderr)
        return 2

    limit = args.limit_kb * 1024
    over_budget = []
    total = 0
    for svg in svgs:
        relative = svg.relative_to(SOURCE).with_suffix(".png")
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        png = convert(svg, args.colors)
        target.write_bytes(png)
        total += len(png)
        flag = ""
        if len(png) > limit:
            over_budget.append(relative)
            flag = "  <-- over budget"
        print(f"{str(relative):38} {len(png) / 1024:6.1f} KB{flag}")

    layers = len([s for s in svgs if s.parent.parent.name == "layers"])
    print(f"\n{len(svgs)} PNGs ({layers} layers), total {total / 1024:.0f} KB in {output}")
    if over_budget:
        print(f"{len(over_budget)} file(s) over {args.limit_kb:g} KB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
