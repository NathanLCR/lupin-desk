#!/usr/bin/env python3
"""Gera os PNGs 480x320 do Lupin para o ESP32 a partir dos SVGs em static/lupin/.

Os SVGs por camada são a fonte única. Cada PNG sai com transparência, cores
indexadas de 8 bits e passa por checagem de orçamento (padrão: 20 KB).

Dependências só de desenvolvimento (não entram no servidor):

    pip install pillow resvg-py

Uso:

    python scripts/gerar_png_lupin.py [--saida build/lupin-png] [--limite-kb 20]
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "static" / "lupin"
LARGURA, ALTURA = 480, 320


def converter(svg: Path, cores: int):
    import resvg_py
    from PIL import Image

    dados = bytes(resvg_py.svg_to_bytes(svg_path=str(svg)))
    imagem = Image.open(io.BytesIO(dados)).convert("RGBA")
    if imagem.size != (LARGURA, ALTURA):
        raise SystemExit(f"{svg}: esperado {LARGURA}x{ALTURA}, veio {imagem.size}")
    indexada = imagem.quantize(colors=cores, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    buffer = io.BytesIO()
    indexada.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--saida", default=str(RAIZ / "build" / "lupin-png"))
    parser.add_argument("--limite-kb", type=float, default=20.0)
    parser.add_argument("--cores", type=int, default=64)
    args = parser.parse_args()

    try:
        import PIL  # noqa: F401
        import resvg_py  # noqa: F401
    except ImportError:
        print("Faltam dependências: pip install pillow resvg-py", file=sys.stderr)
        return 2

    saida = Path(args.saida)
    svgs = sorted(FONTE.rglob("*.svg"))
    if not svgs:
        print(f"Nenhum SVG em {FONTE}", file=sys.stderr)
        return 2

    limite = args.limite_kb * 1024
    estouros = []
    total = 0
    for svg in svgs:
        relativo = svg.relative_to(FONTE).with_suffix(".png")
        destino = saida / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        png = converter(svg, args.cores)
        destino.write_bytes(png)
        total += len(png)
        marca = ""
        if len(png) > limite:
            estouros.append(relativo)
            marca = "  <-- acima do orçamento"
        print(f"{str(relativo):38} {len(png) / 1024:6.1f} KB{marca}")

    camadas = len([s for s in svgs if s.parent.parent.name == "camadas"])
    print(f"\n{len(svgs)} PNGs ({camadas} de camadas), total {total / 1024:.0f} KB em {saida}")
    if estouros:
        print(f"{len(estouros)} arquivo(s) acima de {args.limite_kb:g} KB", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
