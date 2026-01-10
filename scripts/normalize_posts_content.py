#!/usr/bin/env python3
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
    from bs4.element import NavigableString, Tag
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("Missing dependency: beautifulsoup4. Install with: python -m pip install beautifulsoup4") from exc


ROOT_DIR = Path(__file__).resolve().parents[1]
POSTS_JSON_PATH = ROOT_DIR / "data" / "posts.json"
REPORT_PATH = ROOT_DIR / "blog-normalize-report.json"

SIZE_SUFFIX_RE = re.compile(r"-\d+x\d+(?=\.[a-z0-9]+$)", re.IGNORECASE)
SCALED_SUFFIX_RE = re.compile(r"-(scaled|rotated)(?=\.[a-z0-9]+$)", re.IGNORECASE)
HASH_SUFFIX_RE = re.compile(r"-[a-z0-9]{12,}(?=\.[a-z0-9]+$)", re.IGNORECASE)


def normalize_src(src: str) -> str:
    if not src:
        return ""
    raw = src.strip()
    if raw.startswith("data:"):
        return ""

    parsed = urlparse(raw)
    path = parsed.path if (parsed.scheme or parsed.netloc) else raw
    path = path.split("?", 1)[0].split("#", 1)[0]
    path = path.replace("\\", "/")

    while path.startswith("./"):
        path = path[2:]
    while path.startswith("../"):
        path = path[3:]
    path = path.lstrip("/")
    if path.lower().startswith("fcge/"):
        path = path[5:]

    path = posixpath.normpath(path)
    if path == ".":
        path = ""

    if path:
        parts = path.split("/")
        filename = parts[-1]
        filename = SIZE_SUFFIX_RE.sub("", filename)
        filename = SCALED_SUFFIX_RE.sub("", filename)
        filename = HASH_SUFFIX_RE.sub("", filename)
        parts[-1] = filename
        path = "/".join(parts)

    return path.lower()


def is_blank(node: Tag | NavigableString) -> bool:
    if isinstance(node, NavigableString):
        return not node.strip()
    if isinstance(node, Tag):
        return False
    return True


def cleanup_container(node: Tag | None) -> None:
    if not node or not isinstance(node, Tag):
        return
    if node.name not in {"a", "figure"}:
        return
    meaningful = [child for child in node.contents if not is_blank(child)]
    if not meaningful:
        node.decompose()


def remove_image(img: Tag) -> None:
    parent = img.parent if isinstance(img.parent, Tag) else None
    img.decompose()
    cleanup_container(parent)
    if parent and parent.name == "figure":
        cleanup_container(parent)


def wrap_image(img: Tag, soup: BeautifulSoup) -> None:
    parent = img.parent if isinstance(img.parent, Tag) else None
    wrap_target: Tag = img

    if parent and parent.name == "a":
        meaningful = [child for child in parent.contents if not is_blank(child)]
        if len(meaningful) == 1 and meaningful[0] is img:
            wrap_target = parent

    existing_figure = wrap_target.parent if isinstance(wrap_target.parent, Tag) else None
    if existing_figure and existing_figure.name == "figure":
        classes = existing_figure.get("class", [])
        if "post-figure" not in classes:
            classes.append("post-figure")
            existing_figure["class"] = classes
        return

    figure = soup.new_tag("figure")
    figure["class"] = ["post-figure"]
    wrap_target.wrap(figure)


def iter_images(soup: BeautifulSoup) -> Iterable[Tag]:
    return soup.find_all("img")


def normalize_post(post: dict[str, object]) -> tuple[str, int, int, bool, list[str]]:
    content_html = str(post.get("contentHtml") or "")
    cover_path = str(post.get("coverImagePath") or "")
    slug = str(post.get("slug") or "")

    warnings: list[str] = []
    if not cover_path:
        warnings.append(f"{slug}: missing coverImagePath")

    soup = BeautifulSoup(content_html, "html.parser")
    cover_norm = normalize_src(cover_path)

    removed_duplicates = 0
    removed_cover = 0
    seen: set[str] = set()

    for img in list(iter_images(soup)):
        src = img.get("src", "")
        norm = normalize_src(src)
        if not norm:
            continue
        if cover_norm and norm == cover_norm:
            remove_image(img)
            removed_cover += 1
            continue
        if norm in seen:
            remove_image(img)
            removed_duplicates += 1
            continue
        seen.add(norm)

    for img in iter_images(soup):
        img["loading"] = "lazy"
        img["decoding"] = "async"
        wrap_image(img, soup)

    for h1 in soup.find_all("h1"):
        h1.name = "h3"

    new_html = soup.decode_contents()
    if not new_html.strip():
        warnings.append(f"{slug}: empty contentHtml")

    if not list(iter_images(soup)):
        warnings.append(f"{slug}: no images in contentHtml")

    changed = new_html != content_html
    if changed:
        post["contentHtml"] = new_html

    return slug, removed_duplicates, removed_cover, changed, warnings


def main() -> None:
    posts = json.loads(POSTS_JSON_PATH.read_text(encoding="utf-8"))
    total_duplicates = 0
    total_cover = 0
    changed_slugs: list[str] = []
    warnings: list[str] = []

    for post in posts:
        slug, removed_dup, removed_cover, changed, post_warnings = normalize_post(post)
        total_duplicates += removed_dup
        total_cover += removed_cover
        if changed:
            changed_slugs.append(slug)
        warnings.extend(post_warnings)

    POSTS_JSON_PATH.write_text(
        json.dumps(posts, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    report = {
        "totalPosts": len(posts),
        "imagesRemovedAsDuplicate": total_duplicates,
        "coverDuplicatesRemoved": total_cover,
        "postsWithChanges": changed_slugs,
        "warnings": warnings,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
