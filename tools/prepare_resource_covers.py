"""Offline first-page thumbnails and bounded evidence extraction (not a publisher).

Use bundled Python with pypdfium2 and Pillow. Originals are read only.
"""
import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("E:/storage/oss-public"))
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/resources-preparation")
    args = parser.parse_args()
    candidates = json.loads((ROOT / "docs/research/resources-preparation/resources.candidates.json").read_text(encoding="utf-8"))
    selected = [item for item in candidates if item["object_key"] and (not args.ids or item["id"] in args.ids)]
    if not selected or (args.ids and set(args.ids) != {item['id'] for item in selected}):
        raise ValueError("Selection contains unknown/unlisted objects")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for item in selected:
        record_path = args.output / (item["id"] + ".evidence.json")
        if record_path.exists():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            results.append(record)
            continue
        source = args.source / item["review"]["uploaded_filename"]
        with pdfium.PdfDocument(str(source)) as document:
            count = len(document)
            pages = []
            for number in range(min(4, count)):
                page = document[number]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()[:14000]
                    finally:
                        textpage.close()
                    pages.append({"page": number + 1, "text": text})
                    if number == 0:
                        width, height = page.get_size()
                        bitmap = page.render(scale=800 / max(width, height))
                        picture = bitmap.to_pil().convert("RGB")
                        cover_path = args.output / (item["id"] + ".jpg")
                        for quality in (85, 75, 65):
                            picture.save(cover_path, "JPEG", quality=quality, optimize=True)
                            if cover_path.stat().st_size <= 120 * 1024:
                                break
                        picture.close()
                        bitmap.close()
                finally:
                    page.close()
            record = {"id": item["id"], "source_filename": source.name, "page_count": count,
                      "cover_page": 1, "cover_review": "pending", "pages_read": pages,
                      "cover_filename": cover_path.name, "cover_size_bytes": cover_path.stat().st_size}
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(record)
        print(f"{item['id']}: {count} pages; thumbnail {record['cover_size_bytes']} bytes", flush=True)
    # Contact sheets are numbered; separate small batches remain easy to review.
    for start in range(0, len(results), 8):
        batch = results[start:start + 8]
        sheet = Image.new("RGB", (1000, 900), "#fafbf9")
        draw = ImageDraw.Draw(sheet)
        for offset, record in enumerate(batch):
            x, y = (offset % 4) * 250, (offset // 4) * 450
            with Image.open(args.output / record['cover_filename']) as picture:
                picture.thumbnail((225, 385))
                sheet.paste(picture, (x + (250 - picture.width) // 2, y + 10))
            draw.text((x + 10, y + 405), f"{start + offset + 1:02} {record['id'][:27]}", fill="#202b33")
        sheet.save(args.output / f"contact-{start // 8 + 1}.jpg", quality=90)
    (args.output / "extraction-index.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
