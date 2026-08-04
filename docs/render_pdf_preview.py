# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="PDF path")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--pages", nargs="*", type=int, default=[1, 4, 8, 12, 16, 20, 24])
    parser.add_argument("--dpi", type=int, default=170)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.pdf).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    zoom = args.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(pdf_path) as pdf:
        for page_no in args.pages:
            if page_no < 1 or page_no > pdf.page_count:
                continue
            page = pdf.load_page(page_no - 1)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out_path = outdir / f"page_{page_no:02d}.png"
            pix.save(out_path)


if __name__ == "__main__":
    main()
