"""Small, reviewed resource catalog. File transfers always go directly to OSS."""
import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

ROOT = Path(__file__).resolve().parent.parent
OSS_ORIGIN = "https://space-hub-pub.oss-cn-chengdu.aliyuncs.com"
router = APIRouter(prefix="/api/resources")


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,119}$")
    title: str = Field(min_length=1, max_length=500)
    original_filename: str = ""
    object_key: str
    cover_key: str | None = None
    cover_asset: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]*\.jpg$")
    description_short: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=5000)
    authors: list[str] = Field(default_factory=list)
    edition: str | None = None
    language: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    format: str = Field(default="PDF", pattern=r"^PDF$")
    size_bytes: int = Field(gt=0, strict=True)
    source_note: str = ""
    published: StrictBool = False
    updated_at: str = ""
    display_order: int = Field(default=0, ge=0, strict=True)


def object_url(key: str, *, cover: bool = False) -> str:
    origin = os.environ.get("RESOURCE_OSS_ORIGIN", OSS_ORIGIN)
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or parsed.netloc != urlsplit(OSS_ORIGIN).netloc
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid OSS origin")
    prefix = "public/covers/" if cover else "public/"
    parts = key.split("/")
    if (not key.startswith(prefix) or any(part in ("", ".", "..") for part in parts)
            or "\\" in key or any(ord(char) < 32 or ord(char) == 127 for char in key)):
        raise ValueError("Invalid object key")
    if not cover and (key.startswith("public/covers/") or not key.lower().endswith(".pdf")):
        raise ValueError("Invalid PDF key")
    if cover and not re.search(r"\.(jpe?g|webp|png)$", key, re.I):
        raise ValueError("Invalid cover key")
    return origin.rstrip("/") + "/" + "/".join(quote(part, safe="") for part in parts)


class Catalog:
    def __init__(self):
        self.items: list[Resource] | None = None

    def load(self):
        try:
            path = Path(os.environ.get("RESOURCES_PATH", str(ROOT / "content/resources.json")))
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("Catalog must be an array")
            items = [Resource.model_validate(item) for item in data]
            if len({item.id for item in items}) != len(items):
                raise ValueError("Duplicate resource ID")
            if len({item.object_key for item in items}) != len(items):
                raise ValueError("Duplicate resource object key")
            for item in items:
                object_url(item.object_key)
                if item.cover_key:
                    object_url(item.cover_key, cover=True)
            self.items = sorted(items, key=lambda item: (item.display_order, item.id))
        except (OSError, ValueError, TypeError):
            logging.exception("Resource catalog unavailable")
            self.items = None

    def public_items(self):
        from . import management_store
        try:
            if management_store.active():
                return management_store.public_items()
        except management_store.ManagementError:
            raise HTTPException(503, "Resource catalog unavailable") from None
        if self.items is None:
            raise HTTPException(503, "Resource catalog unavailable")
        return [item for item in self.items if item.published]

    def find(self, resource_id):
        for item in self.public_items():
            if item.id == resource_id:
                return item
        raise HTTPException(404, "Resource not found")


catalog = Catalog()


def normalized(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


def public_record(item, detail=False):
    fields = ("id", "title", "authors", "edition", "language", "category", "tags", "format",
              "size_bytes", "description_short")
    result = {field: getattr(item, field) for field in fields}
    try:
        result["cover_url"] = (f"/assets/resource-covers/{item.cover_asset}" if item.cover_asset
                               else object_url(item.cover_key, cover=True) if item.cover_key else None)
    except ValueError as error:
        raise HTTPException(503, "Resource configuration unavailable") from error
    result["download_url"] = f"/api/resources/{item.id}/download"
    if detail:
        result.update(description=item.description, source_note=item.source_note)
    return result


@router.get("")
def list_resources(response: Response, q: str = Query("", max_length=120), category: str = Query("", max_length=80),
                   page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=48)):
    response.headers['Cache-Control'] = 'no-store'
    public = catalog.public_items()
    categories = sorted({item.category for item in public if item.category})
    query = normalized(q)
    matches = [item for item in public if (not category or item.category == category)
               and (not query or query in normalized(" ".join([item.title, *item.authors, *item.tags])))]
    total = len(matches)
    start = (page - 1) * page_size
    return {"items": [public_record(item) for item in matches[start:start + page_size]],
            "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size, "categories": categories}


@router.get("/{resource_id}/download")
def download_resource(resource_id: str):
    item = catalog.find(resource_id)
    try:
        url = object_url(item.object_key)
    except ValueError as error:
        raise HTTPException(503, "Resource configuration unavailable") from error
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


@router.get("/{resource_id}")
def resource_detail(resource_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return public_record(catalog.find(resource_id), detail=True)
