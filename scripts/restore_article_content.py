#!/usr/bin/env python3
"""Restore article body content from source posts and rebuild main layout."""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

BASE_URL = "https://www.fcgestaoestrategica.com.br"
ROOT_DIR = Path(__file__).resolve().parents[1]
POSTS_PATH = ROOT_DIR / "data" / "posts.json"
IMAGES_DIR = ROOT_DIR / "imagens" / "blog"
REPORT_PATH = ROOT_DIR / "layout-fix-report.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def fetch(session: requests.Session, url: str, retries: int = 3) -> str:
    backoff = 1
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30, verify=False)
            resp.raise_for_status()
            return resp.text
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"Failed to fetch {url}")


def slug_from_file(path: Path) -> str:
    return path.stem.replace("artigo-", "")


def pick_image_url(img_tag) -> str | None:
    if img_tag is None:
        return None
    attrs = [
        "data-src",
        "data-lazy-src",
        "nitro-lazy-src",
        "data-original",
        "src",
    ]
    for attr in attrs:
        val = img_tag.get(attr)
        if val and not val.startswith("data:"):
            return urljoin(BASE_URL, val)
    srcset = img_tag.get("srcset") or img_tag.get("nitro-lazy-srcset") or img_tag.get("data-srcset")
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        if first and not first.startswith("data:"):
            return urljoin(BASE_URL, first)
    return None


def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[<>:\"/\\|?*]", "-", name)
    name = name.replace(" ", "-")
    name = re.sub(r"-+", "-", name)
    return name or "imagem"


def download_image(session: requests.Session, url: str, slug: str) -> str | None:
    if not url:
        return None
    if url.startswith("imagens/"):
        return url

    parsed = urlparse(url)
    filename = safe_filename(Path(parsed.path).name)
    dest_dir = IMAGES_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not filename or "." not in filename:
        filename = f"imagem-{int(time.time())}.jpg"

    dest_path = dest_dir / filename
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return dest_path.relative_to(ROOT_DIR).as_posix()

    try:
        resp = session.get(url, timeout=30, verify=False)
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)
        return dest_path.relative_to(ROOT_DIR).as_posix()
    except Exception:
        return url


def extract_body_html(post_div):
    if not post_div:
        return ""

    widgets = post_div.select(".elementor-widget")
    pieces = []

    def append_html(html: str) -> None:
        if html and html.strip():
            pieces.append(html)

    def extract_from_container(container) -> str:
        if not container:
            return ""

        editor = container.select_one(".elementor-text-editor")
        if editor:
            return editor.decode_contents()

        allowed_tags = {"p", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "blockquote", "figure", "img", "iframe"}
        included = []
        included_ids = set()

        def has_included_parent(el) -> bool:
            parent = el.parent
            while parent and parent is not container:
                if id(parent) in included_ids:
                    return True
                parent = parent.parent
            return False

        for el in container.find_all(allowed_tags):
            if has_included_parent(el):
                continue
            included.append(el)
            included_ids.add(id(el))

        if included:
            return "\n".join(str(el) for el in included)

        text = container.get_text(" ", strip=True)
        return container.decode_contents() if text else ""

    for widget in widgets:
        widget_type = widget.get("data-widget_type", "")
        if "spacer" in widget_type or "divider" in widget_type:
            continue

        container = widget.select_one(".elementor-widget-container") or widget
        html = extract_from_container(container)
        append_html(html)

    if pieces:
        return "\n".join(pieces)

    fallback = post_div.select_one(".entry-content") or post_div
    return extract_from_container(fallback)


def rewrite_internal_links(body_soup: BeautifulSoup, posts_by_slug: dict) -> None:
    legacy_pages = {
        "": "index.html",
        "contato": "contato.html",
        "servicos": "servicos.html",
        "quem-somos": "sobre.html",
        "sobre": "sobre.html",
        "cases": "cases.html",
        "produtosdigitais": "produtosdigitais.html",
        "produtos-digitais": "produtosdigitais.html",
        "blog": "blog.html",
    }

    for anchor in body_soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and "fcgestaoestrategica.com.br" in parsed.netloc:
            slug = parsed.path.strip("/").split("/")[-1]
            if slug in posts_by_slug:
                anchor["href"] = f"artigo-{slug}.html"
                continue
            mapped = legacy_pages.get(slug or "")
            if mapped:
                anchor["href"] = mapped
                continue
        if href.startswith("/blog"):
            anchor["href"] = "blog.html"


def build_main(soup: BeautifulSoup, title: str, date_text: str, category: str, cover_path: str | None, body_html: str):
    main = soup.new_tag("main")
    section = soup.new_tag("section", **{"class": "py-16 sm:py-20"})
    container = soup.new_tag("div", **{"class": "container mx-auto px-6 max-w-4xl"})

    meta = soup.new_tag("p", **{"class": "text-sm text-slate-500"})
    meta.string = f"{category} - {date_text}" if date_text else category

    h1 = soup.new_tag("h1", **{"class": "mt-3 text-3xl md:text-4xl font-black tracking-tight text-slate-900"})
    h1.string = title

    container.append(meta)
    container.append(h1)

    if cover_path:
        figure = soup.new_tag("figure", **{"class": "my-8"})
        img = soup.new_tag(
            "img",
            src=cover_path,
            alt=title,
            **{"class": "w-full h-auto rounded-xl shadow-lg"},
        )
        figure.append(img)
        container.append(figure)

    article = soup.new_tag("article", **{"class": "prose max-w-none"})
    fragment = BeautifulSoup(body_html, "html.parser")
    for node in list(fragment.contents):
        article.append(node)
    container.append(article)

    section.append(container)
    main.append(section)
    return main


def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.headers.update(HEADERS)

    posts = []
    if POSTS_PATH.exists():
        posts = json.loads(POSTS_PATH.read_text(encoding="utf-8"))
    posts_by_slug = {post.get("slug"): post for post in posts}

    report = {
        "totalArticles": 0,
        "fixedOK": 0,
        "skipped": [],
        "missingCSSAfterFix": [],
        "brokenAssetPathsSuspected": [],
        "templateUsed": "blog.html",
    }

    for path in sorted(ROOT_DIR.glob("artigo-*.html")):
        report["totalArticles"] += 1
        slug = slug_from_file(path)
        post = posts_by_slug.get(slug, {})
        source_url = post.get("sourceUrl") or f"{BASE_URL}/{slug}/"

        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        main = soup.find("main")

        try:
            source_html = fetch(session, source_url)
        except Exception as exc:
            report["skipped"].append({"file": str(path.relative_to(ROOT_DIR)), "reason": f"fetch failed: {exc}"})
            continue

        source_soup = BeautifulSoup(source_html, "html.parser")
        post_div = source_soup.find("div", attrs={"data-elementor-type": "wp-post"}) or source_soup.find("article")
        body_html = extract_body_html(post_div)
        if not body_html:
            report["skipped"].append({"file": str(path.relative_to(ROOT_DIR)), "reason": "no body content"})
            continue

        body_soup = BeautifulSoup(body_html, "html.parser")
        rewrite_internal_links(body_soup, posts_by_slug)

        for img in body_soup.find_all("img"):
            img_url = pick_image_url(img)
            local_path = download_image(session, img_url, slug) if img_url else None
            if local_path:
                img["src"] = local_path
            for attr in [
                "srcset",
                "sizes",
                "data-src",
                "data-lazy-src",
                "nitro-lazy-src",
                "nitro-lazy-srcset",
                "data-srcset",
                "data-original",
                "nitro-lazy-empty",
            ]:
                if attr in img.attrs:
                    del img.attrs[attr]

        cover_path = post.get("coverImagePath")
        if not cover_path:
            og_image = source_soup.find("meta", property="og:image")
            cover_url = og_image.get("content") if og_image else None
            cover_path = download_image(session, cover_url, slug) if cover_url else None
        if not cover_path:
            first_img = body_soup.find("img")
            if first_img and first_img.get("src"):
                cover_path = first_img.get("src")

        title = post.get("title") or (source_soup.find("h1").get_text(strip=True) if source_soup.find("h1") else slug)
        date_text = post.get("dateHumanPTBR") or ""
        category = post.get("category") or "Blog"

        new_main = build_main(soup, title, date_text, category, cover_path, body_soup.decode_contents())

        if soup.body:
            existing_main = soup.body.find("main")
            if existing_main:
                existing_main.replace_with(new_main)
            else:
                soup.body.append(new_main)
        else:
            report["skipped"].append({"file": str(path.relative_to(ROOT_DIR)), "reason": "missing body"})
            continue

        path.write_text(soup.decode(), encoding="utf-8")
        report["fixedOK"] += 1

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
