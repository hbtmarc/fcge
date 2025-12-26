#!/usr/bin/env python3
"""Fix layout for article pages by applying template header/footer/assets."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Doctype

ROOT_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_FILE = ROOT_DIR / "blog.html"
REPORT_PATH = ROOT_DIR / "layout-fix-report.json"

ARTICLE_DIRS = ["posts", "blog"]


def get_article_paths() -> list[Path]:
    paths = set(ROOT_DIR.glob("artigo-*.html"))
    for folder in ARTICLE_DIRS:
        dir_path = ROOT_DIR / folder
        if dir_path.exists():
            for file_path in dir_path.rglob("*.html"):
                paths.add(file_path)
    return sorted(paths)


def normalize_path(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\./", "", value)
    return value


def is_relative_url(url: str) -> bool:
    if not url:
        return False
    if url.startswith(('#', 'mailto:', 'tel:', 'data:', 'javascript:')):
        return False
    if url.startswith('/'):
        return False
    if url.startswith('http://') or url.startswith('https://'):
        return False
    return True


def adjust_relative(value: str, prefix: str) -> str:
    if not value:
        return value
    if not is_relative_url(value):
        return value
    return f"{prefix}{value}"


def adjust_tag_paths(tag: BeautifulSoup, prefix: str) -> None:
    if tag.has_attr("href"):
        tag["href"] = adjust_relative(tag.get("href"), prefix)
    if tag.has_attr("src"):
        tag["src"] = adjust_relative(tag.get("src"), prefix)


def extract_assets(template_head: BeautifulSoup) -> list:
    assets = []
    for child in template_head.find_all(recursive=False):
        if child.name == "link":
            rel = child.get("rel", [])
            rel_list = rel if isinstance(rel, list) else [rel]
            allowed = {"preconnect", "stylesheet", "icon", "apple-touch-icon", "manifest"}
            if any(item in allowed for item in rel_list):
                assets.append(child)
        elif child.name == "script" and child.get("src"):
            assets.append(child)
        elif child.name == "style":
            assets.append(child)
    return assets


def collect_existing_assets(head: BeautifulSoup) -> dict:
    links = set()
    scripts = set()
    styles = set()

    for link in head.find_all("link", href=True):
        rel = link.get("rel", [])
        rel_list = rel if isinstance(rel, list) else [rel]
        rel_key = tuple(sorted(rel_list))
        links.add((rel_key, normalize_path(link["href"])))

    for script in head.find_all("script", src=True):
        scripts.add(normalize_path(script["src"]))

    for style in head.find_all("style"):
        text = style.get_text("\n", strip=True)
        if text:
            styles.add(text)

    return {"links": links, "scripts": scripts, "styles": styles}


def build_main(soup: BeautifulSoup, template_main_attrs: dict, article_content_html: str):
    new_main = soup.new_tag("main")
    for key, value in template_main_attrs.items():
        new_main.attrs[key] = value
    fragment = BeautifulSoup(article_content_html, "html.parser")
    for node in fragment.contents:
        new_main.append(node)
    return new_main


def find_article_content(soup: BeautifulSoup) -> str:
    main = soup.find("main")
    if main:
        return main.decode_contents()
    article = soup.find("article")
    if article:
        return str(article)
    h1 = soup.find("h1")
    if h1:
        container = h1.find_parent(["section", "div"]) or h1.parent
        return str(container)
    if soup.body:
        return soup.body.decode_contents()
    return ""


def collect_body_scripts(soup: BeautifulSoup) -> list:
    scripts = []
    if not soup.body:
        return scripts
    for script in soup.body.find_all("script"):
        if script.get("type") == "application/ld+json":
            continue
        scripts.append(script)
    return scripts


def update_head_assets(soup: BeautifulSoup, head: BeautifulSoup, template_assets: list, prefix: str) -> None:
    existing = collect_existing_assets(head)
    for asset in template_assets:
        cloned = BeautifulSoup(str(asset), "html.parser").find()
        if not cloned:
            continue
        adjust_tag_paths(cloned, prefix)

        if cloned.name == "link":
            rel = cloned.get("rel", [])
            rel_list = rel if isinstance(rel, list) else [rel]
            rel_key = tuple(sorted(rel_list))
            href = normalize_path(cloned.get("href", ""))
            if (rel_key, href) in existing["links"]:
                continue
            head.append(cloned)
            existing["links"].add((rel_key, href))
        elif cloned.name == "script" and cloned.get("src"):
            src = normalize_path(cloned.get("src", ""))
            if src in existing["scripts"]:
                continue
            head.append(cloned)
            existing["scripts"].add(src)
        elif cloned.name == "style":
            text = cloned.get_text("\n", strip=True)
            if text and text in existing["styles"]:
                continue
            head.append(cloned)
            if text:
                existing["styles"].add(text)


def has_css(head: BeautifulSoup) -> bool:
    if head.find("link", rel=lambda v: v and "stylesheet" in v):
        return True
    if head.find("style"):
        return True
    if head.find("script", src=lambda v: v and "tailwindcss" in v):
        return True
    return False


def resolve_local_path(base_dir: Path, value: str) -> Path | None:
    if not value or not is_relative_url(value):
        return None
    return (base_dir / value).resolve()


def collect_broken_assets(path: Path, soup: BeautifulSoup) -> list[str]:
    broken = []
    head = soup.head
    if not head:
        return broken
    for tag in head.find_all(["link", "script"]):
        attr = "href" if tag.name == "link" else "src"
        value = tag.get(attr)
        local_path = resolve_local_path(path.parent, value)
        if local_path and not local_path.exists():
            broken.append(value)
    for img in soup.find_all("img", src=True):
        value = img.get("src")
        local_path = resolve_local_path(path.parent, value)
        if local_path and not local_path.exists():
            broken.append(value)
    return broken


def main():
    if not TEMPLATE_FILE.exists():
        raise SystemExit(f"Template not found: {TEMPLATE_FILE}")

    template_html = TEMPLATE_FILE.read_text(encoding="utf-8", errors="ignore")
    template_soup = BeautifulSoup(template_html, "html.parser")

    template_head = template_soup.head
    template_body = template_soup.body
    template_main = template_soup.find("main")
    template_header = template_soup.find("header")
    template_footer = template_soup.find("footer")

    if not template_head or not template_body or not template_header or not template_footer:
        raise SystemExit("Template missing head/body/header/footer")

    template_assets = extract_assets(template_head)
    template_body_attrs = template_body.attrs.copy()
    template_main_attrs = template_main.attrs.copy() if template_main else {}

    article_paths = get_article_paths()
    report = {
        "totalArticles": len(article_paths),
        "fixedOK": 0,
        "skipped": [],
        "missingCSSAfterFix": [],
        "brokenAssetPathsSuspected": [],
        "templateUsed": str(TEMPLATE_FILE.relative_to(ROOT_DIR)),
    }

    for path in article_paths:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(raw, "html.parser")

            if not soup.head or not soup.body:
                report["skipped"].append({"file": str(path.relative_to(ROOT_DIR)), "reason": "missing head/body"})
                continue

            depth = len(path.parent.relative_to(ROOT_DIR).parts)
            prefix = "../" * depth if depth > 0 else ""

            update_head_assets(soup, soup.head, template_assets, prefix)

            article_content_html = find_article_content(soup)
            body_scripts = collect_body_scripts(soup)

            new_body = soup.new_tag("body")
            for key, value in template_body_attrs.items():
                new_body.attrs[key] = value

            header_clone = BeautifulSoup(str(template_header), "html.parser").find()
            footer_clone = BeautifulSoup(str(template_footer), "html.parser").find()
            if header_clone:
                for tag in header_clone.find_all(True):
                    adjust_tag_paths(tag, prefix)
                new_body.append(header_clone)
            new_main = build_main(soup, template_main_attrs, article_content_html)
            for tag in new_main.find_all(True):
                adjust_tag_paths(tag, prefix)
            new_body.append(new_main)
            if footer_clone:
                for tag in footer_clone.find_all(True):
                    adjust_tag_paths(tag, prefix)
                new_body.append(footer_clone)

            for script in body_scripts:
                new_body.append(script)

            soup.body.replace_with(new_body)

            if not has_css(soup.head):
                report["missingCSSAfterFix"].append(str(path.relative_to(ROOT_DIR)))

            broken_assets = collect_broken_assets(path, soup)
            for asset in broken_assets:
                report["brokenAssetPathsSuspected"].append({
                    "file": str(path.relative_to(ROOT_DIR)),
                    "asset": asset,
                })

            doctype = next((item for item in soup.contents if isinstance(item, Doctype)), None)
            output = soup.decode()
            if doctype and "<!DOCTYPE" not in output.upper():
                output = f"<!DOCTYPE html>\n{output}"
            path.write_text(output, encoding="utf-8")

            report["fixedOK"] += 1
        except Exception as exc:
            report["skipped"].append({"file": str(path.relative_to(ROOT_DIR)), "reason": str(exc)})

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
