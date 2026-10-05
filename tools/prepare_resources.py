"""Build a review-only inventory without changing source PDFs or publishing items.

Run from the repository root:
    .venv/Scripts/python.exe tools/prepare_resources.py --source E:/storage/oss-public
"""
import argparse
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def prepare(source: Path, objects_document: Path):
    files = {path.name: path for path in source.glob("*.pdf")}
    if not files:
        raise ValueError("No local PDFs found")
    table = source / "文件名对照表.csv"
    raw = table.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    if not lines or lines[0] != "原始文件名,上传文件名":
        raise ValueError("Unexpected mapping header")
    # This repair is for the inspected, unquoted source table only. Split at its
    # final delimiter, then require an exact match against an actual local PDF.
    mappings = []
    repaired = []
    seen = set()
    for line_number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        if '"' in line or "," not in line:
            raise ValueError(f"Line {line_number}: source format changed; review manually")
        original, uploaded = line.rsplit(",", 1)
        if not original or uploaded not in files or uploaded in seen:
            raise ValueError(f"Line {line_number}: missing, unknown or duplicate mapping")
        seen.add(uploaded)
        mappings.append((original, uploaded))
        if len(next(csv.reader([line]))) != 2:
            repaired.append({"line": line_number, "uploaded_filename": uploaded})
    if seen != set(files):
        raise ValueError(f"Unmapped local PDFs: {sorted(set(files) - seen)}")
    objects_text = objects_document.read_text(encoding="utf-8-sig")
    objects = re.findall(r"^\| ([a-z0-9-]+\.pdf) \|", objects_text, re.MULTILINE)
    if not objects or len(objects) != len(set(objects)) or set(objects) - seen:
        raise ValueError("OSS document has missing, duplicate or unknown object names")
    timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    items = []
    for order, (original, uploaded) in enumerate(mappings, 1):
        listed = uploaded in objects
        items.append({
            "id": Path(uploaded).stem,
            "title": original[:-4] if original.lower().endswith(".pdf") else original,
            "original_filename": original,
            "object_key": "public/" + uploaded if listed else None,
            "cover_key": None,
            "description_short": "",
            "description": "",
            "authors": [], "edition": None, "language": None,
            "category": None, "tags": [], "format": "PDF",
            "size_bytes": files[uploaded].stat().st_size,
            "source_note": "名称来自文件名对照表；内容、来源说明和发布条件待审核。",
            "published": False, "updated_at": timestamp, "display_order": order,
            "review": {
                "uploaded_filename": uploaded,
                "listed_in_oss_document": listed,
                "size_source": "local_stat",
                "metadata_status": "pending",
                "publication_status": "pending",
                "remote_status": "not_verified",
                "cover_status": "pending",
            },
        })
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["原始文件名", "上传文件名"])
    writer.writerows(mappings)
    # Round-trip with a standard CSV reader before any output is written.
    assert list(csv.reader(io.StringIO(output.getvalue())))[1:] == [list(row) for row in mappings]
    summary = {
        "generated_at": timestamp, "local_count": len(files),
        "oss_document_count": len(objects), "published_count": 0,
        "total_size_bytes": sum(item["size_bytes"] for item in items),
        "repaired_rows": repaired,
        "not_listed_in_oss_document": sorted(seen - set(objects)),
        "note": "Local inventory only; no remote headers, full downloads or metadata approval implied.",
    }
    return output.getvalue(), items, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--objects", type=Path,
                        default=ROOT / "docs/research/OSS资料对象清单-20261005.md")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/research/resources-preparation")
    args = parser.parse_args()
    csv_text, items, summary = prepare(args.source, args.objects)
    targets = {
        "filename-mapping.csv": csv_text,
        "resources.candidates.json": json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        "inventory-check.json": json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    }
    # Protect subsequent human review edits. Regeneration needs a new directory.
    if any((args.output / name).exists() for name in targets):
        raise FileExistsError("Output already exists; use --output with a new directory")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in targets.items():
        (args.output / name).write_text(content, encoding="utf-8", newline="")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
