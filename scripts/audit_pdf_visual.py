"""Render PDF contact sheets and representative full-size pages for QA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def parse_pages(raw: str, count: int) -> list[int]:
    if not raw.strip():
        return [0, max(0, count // 4), max(0, count // 2), max(0, 3 * count // 4), count - 1]
    result = []
    for item in raw.split(","):
        page = int(item.strip()) - 1
        if 0 <= page < count and page not in result:
            result.append(page)
    return result


def render_page(page, width: int) -> Image.Image:
    scale = width / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--representative-pages", default="1,3,20,40,70,120,153")
    args = parser.parse_args()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(args.pdf.resolve())
    stats = []
    thumbs = []
    for index, page in enumerate(doc):
        text = page.get_text("text")
        drawings = len(page.get_drawings())
        images = len(page.get_images(full=True))
        stats.append(
            {
                "page": index + 1,
                "text_chars": len(text.strip()),
                "drawings": drawings,
                "images": images,
                "width_pt": page.rect.width,
                "height_pt": page.rect.height,
            }
        )
        thumb = render_page(page, 160)
        framed = Image.new("RGB", (180, thumb.height + 28), "white")
        framed.paste(thumb, (10, 18))
        ImageDraw.Draw(framed).text((10, 2), f"p.{index + 1}", fill="black")
        thumbs.append(framed)

    cols = 5
    per_sheet = 25
    for start in range(0, len(thumbs), per_sheet):
        batch = thumbs[start : start + per_sheet]
        rows = math.ceil(len(batch) / cols)
        cell_w = max(image.width for image in batch)
        cell_h = max(image.height for image in batch)
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "#d0d0d0")
        for pos, image in enumerate(batch):
            sheet.paste(image, ((pos % cols) * cell_w, (pos // cols) * cell_h))
        sheet.save(output / f"contact_{start + 1:03d}_{start + len(batch):03d}.png")

    for index in parse_pages(args.representative_pages, len(doc)):
        render_page(doc[index], 1500).save(output / f"page_{index + 1:03d}.png")

    blank_candidates = [row["page"] for row in stats if row["text_chars"] < 5 and row["drawings"] == 0 and row["images"] == 0]
    payload = {
        "pdf": str(args.pdf.resolve()),
        "pages": len(doc),
        "blank_candidates": blank_candidates,
        "page_stats": stats,
    }
    (output / "pdf_visual_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"pages": len(doc), "blank_candidates": blank_candidates}))


if __name__ == "__main__":
    main()
