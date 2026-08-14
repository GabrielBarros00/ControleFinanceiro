#!/usr/bin/env python3
"""Converte os PNGs de `npm run shots` para paleta de 256 cores, em docs/images.

Por que existe: o catálogo de telas sempre foi publicado recomprimido, mas o
passo era manual e dependia de ter ImageMagick ou Pillow na máquina. Numa
regeração sem essas ferramentas as imagens entraram cruas e `docs/images` cresceu
45% de uma vez — um passo de release que ninguém consegue repetir não é um passo,
é uma lembrança. Aqui ele usa só a biblioteca padrão.

Uso:
    python frontend/scripts/comprimir-shots.py            # screenshots -> docs/images
    python frontend/scripts/comprimir-shots.py --check    # falha se algo mudaria

Captura de UI tem áreas chapadas e pouca variação real de cor; 256 entradas
seguram texto antialiasado sem diferença perceptível no tamanho em que o catálogo
é lido. Se um dia entrar uma tela com foto, revise isto — não é um quantizador
para imagem contínua.
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

RAIZ = Path(__file__).resolve().parents[2]
ORIGEM = RAIZ / "frontend" / "screenshots"
DESTINO = RAIZ / "docs" / "images"

Pixel = Tuple[int, int, int]


# --- Decodificação ----------------------------------------------------------

def _ler_chunks(dados: bytes) -> Tuple[Dict[str, bytes], bytes]:
    if dados[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("não é PNG")
    pos, unicos, idat = 8, {}, bytearray()
    while pos < len(dados):
        (tamanho,) = struct.unpack(">I", dados[pos:pos + 4])
        tipo = dados[pos + 4:pos + 8].decode("ascii")
        corpo = dados[pos + 8:pos + 8 + tamanho]
        if tipo == "IDAT":
            idat += corpo
        else:
            unicos[tipo] = corpo
        pos += 12 + tamanho
    return unicos, bytes(idat)


def _desfiltra(bruto: bytes, largura: int, altura: int, canais: int) -> bytearray:
    """Desfaz os filtros por scanline (PNG §9). Devolve os bytes crus da imagem."""
    passo = largura * canais
    saida = bytearray(passo * altura)
    anterior = bytearray(passo)
    pos = 0
    for y in range(altura):
        filtro = bruto[pos]
        pos += 1
        linha = bytearray(bruto[pos:pos + passo])
        pos += passo
        if filtro == 1:  # Sub
            for i in range(canais, passo):
                linha[i] = (linha[i] + linha[i - canais]) & 0xFF
        elif filtro == 2:  # Up
            for i in range(passo):
                linha[i] = (linha[i] + anterior[i]) & 0xFF
        elif filtro == 3:  # Average
            for i in range(passo):
                esq = linha[i - canais] if i >= canais else 0
                linha[i] = (linha[i] + ((esq + anterior[i]) >> 1)) & 0xFF
        elif filtro == 4:  # Paeth
            for i in range(passo):
                a = linha[i - canais] if i >= canais else 0
                b = anterior[i]
                c = anterior[i - canais] if i >= canais else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                linha[i] = (linha[i] + pr) & 0xFF
        elif filtro != 0:
            raise ValueError(f"filtro desconhecido: {filtro}")
        saida[y * passo:(y + 1) * passo] = linha
        anterior = linha
    return saida


def ler_png(caminho: Path) -> Tuple[int, int, List[Pixel]]:
    unicos, idat = _ler_chunks(caminho.read_bytes())
    largura, altura, profundidade, tipo_cor = struct.unpack(">IIBB", unicos["IHDR"][:10])
    if profundidade != 8 or tipo_cor not in (2, 6):
        raise ValueError(f"{caminho.name}: esperado RGB/RGBA de 8 bits, veio {tipo_cor}/{profundidade}")
    canais = 3 if tipo_cor == 2 else 4
    cru = _desfiltra(zlib.decompress(idat), largura, altura, canais)
    # Alfa é descartado: as capturas são opacas (o Playwright pinta o fundo).
    pixels = [
        (cru[i], cru[i + 1], cru[i + 2])
        for i in range(0, len(cru), canais)
    ]
    return largura, altura, pixels


# --- Quantização (median cut) -----------------------------------------------

def _corta(caixa: Sequence[Pixel], restantes: int) -> List[List[Pixel]]:
    if restantes <= 1 or len(caixa) <= 1:
        return [list(caixa)]
    eixo = max(range(3), key=lambda c: max(p[c] for p in caixa) - min(p[c] for p in caixa))
    ordenada = sorted(caixa, key=lambda p: p[eixo])
    meio = len(ordenada) // 2
    esq = restantes // 2
    return _corta(ordenada[:meio], esq) + _corta(ordenada[meio:], restantes - esq)


def paleta_de(pixels: Sequence[Pixel], maximo: int = 256) -> List[Pixel]:
    distintas = list({p for p in pixels})
    if len(distintas) <= maximo:
        return distintas
    # Median cut sobre as cores DISTINTAS ponderadas pela frequência seria mais
    # fiel, mas em captura de UI o fundo domina a contagem e puxaria a paleta
    # inteira para dois tons de cinza. Sobre as distintas, o texto sobrevive.
    caixas = _corta(distintas, maximo)
    cores = []
    for caixa in caixas:
        if not caixa:
            continue
        n = len(caixa)
        cores.append(tuple(sum(p[c] for p in caixa) // n for c in range(3)))
    return cores[:maximo]


def _indexa(pixels: Sequence[Pixel], paleta: Sequence[Pixel]) -> bytearray:
    exato = {cor: i for i, cor in enumerate(paleta)}
    cache: Dict[Pixel, int] = {}
    saida = bytearray(len(pixels))
    for i, p in enumerate(pixels):
        idx = exato.get(p)
        if idx is None:
            idx = cache.get(p)
            if idx is None:
                idx = min(
                    range(len(paleta)),
                    key=lambda j: (p[0] - paleta[j][0]) ** 2
                    + (p[1] - paleta[j][1]) ** 2
                    + (p[2] - paleta[j][2]) ** 2,
                )
                cache[p] = idx
        saida[i] = idx
    return saida


# --- Codificação ------------------------------------------------------------

def _chunk(tipo: bytes, corpo: bytes) -> bytes:
    return struct.pack(">I", len(corpo)) + tipo + corpo + struct.pack(
        ">I", zlib.crc32(tipo + corpo) & 0xFFFFFFFF
    )


def escreve_png_indexado(
    caminho: Path, largura: int, altura: int, paleta: Sequence[Pixel], indices: bytes
) -> None:
    linhas = bytearray()
    for y in range(altura):
        linhas.append(0)  # filtro None: o padrão para imagem com paleta
        linhas += indices[y * largura:(y + 1) * largura]
    corpo = b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 3, 0, 0, 0)),
        _chunk(b"PLTE", b"".join(bytes(c) for c in paleta)),
        _chunk(b"IDAT", zlib.compress(bytes(linhas), 9)),
        _chunk(b"IEND", b""),
    ])
    caminho.write_bytes(corpo)


# --- Orquestração -----------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="não escreve; só relata")
    args = ap.parse_args()

    if not ORIGEM.is_dir():
        print(f"nada em {ORIGEM} — rode `npm run shots` antes", file=sys.stderr)
        return 1
    DESTINO.mkdir(parents=True, exist_ok=True)

    total_antes = total_depois = 0
    arquivos = sorted(ORIGEM.glob("*.png"))
    for i, origem in enumerate(arquivos, 1):
        largura, altura, pixels = ler_png(origem)
        paleta = paleta_de(pixels)
        indices = _indexa(pixels, paleta)
        destino = DESTINO / origem.name
        if not args.check:
            escreve_png_indexado(destino, largura, altura, paleta, bytes(indices))
        antes = origem.stat().st_size
        depois = destino.stat().st_size if destino.exists() else antes
        total_antes += antes
        total_depois += depois
        print(
            f"[{i:>2}/{len(arquivos)}] {origem.name:<44} "
            f"{antes // 1024:>4} KB -> {depois // 1024:>4} KB  ({len(paleta)} cores)"
        )

    print(
        f"\nTotal: {total_antes // 1024} KB -> {total_depois // 1024} KB "
        f"({100 - total_depois * 100 // max(total_antes, 1)}% menor)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
