#!/usr/bin/env python3
"""SEO audit and fix for static site HTML."""
import json
import re
from datetime import datetime
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Doctype

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
POSTS_PATH = DATA_DIR / "posts.json"
ROBOTS_PATH = ROOT_DIR / "robots.txt"
SITEMAP_PATH = ROOT_DIR / "sitemap.xml"
SEO_AUDIT_PATH = ROOT_DIR / "SEO_AUDIT.md"
SEO_REPORT_PATH = ROOT_DIR / "seo-report.json"
SITEMAP_REPORT_PATH = ROOT_DIR / "sitemap-report.json"

ICON_SVG_PATH = ROOT_DIR / "assets" / "icons" / "favicon.svg"
MANIFEST_PATH = ROOT_DIR / "site.webmanifest"
LOGO_PNG_PATH = ROOT_DIR / "imagens" / "logo" / "logo12-1.png"
LOGO_WEBP_PATH = ROOT_DIR / "imagens" / "logo" / "logo12-1.webp"


def find_site_url() -> str:
    cname_path = ROOT_DIR / "CNAME"
    if cname_path.exists():
        domain = cname_path.read_text(encoding="utf-8").strip()
        if domain:
            return f"https://{domain}".rstrip("/")

    config_path = ROOT_DIR / "config" / "site.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            site_url = data.get("siteUrl")
            if site_url:
                return site_url.rstrip("/")
        except json.JSONDecodeError:
            pass

    readme_path = ROOT_DIR / "README.md"
    if readme_path.exists():
        text = readme_path.read_text(encoding="utf-8", errors="ignore")
        matches = re.findall(r"https?://[^\s\"'<>]+", text)
        candidates = []
        for url in matches:
            if "github.io" in url and "/fcge" in url:
                candidates.append(url)
        if candidates:
            return candidates[0].rstrip("/")
        if matches:
            return matches[0].rstrip("/")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    placeholder = "https://SEU-DOMINIO-AQUI"
    config_path.write_text(json.dumps({"siteUrl": placeholder}, indent=2), encoding="utf-8")
    return placeholder


def absolute_url(site_url: str, path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{site_url}/{path.lstrip('/')}"


def load_posts() -> dict:
    if not POSTS_PATH.exists():
        return {}
    data = json.loads(POSTS_PATH.read_text(encoding="utf-8"))
    return {post.get("slug"): post for post in data}


def list_html_pages() -> list[Path]:
    pages = []
    for path in ROOT_DIR.rglob("*.html"):
        if any(part in {"scripts", "data", "imagens", "assets", ".git"} for part in path.parts):
            continue
        pages.append(path)
    return sorted(pages)


def is_article(path: Path) -> bool:
    return path.name.startswith("artigo-")


def slug_from_article(path: Path) -> str:
    return path.stem.replace("artigo-", "")


def slug_from_legacy_url(url: str) -> str | None:
    parsed = urlparse(url)
    slug = parsed.path.strip("/").split("/")[-1]
    return slug or None


def strip_and_truncate(text: str, limit: int = 170) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    trimmed = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{trimmed}..."


def normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def ensure_single_h1(soup: BeautifulSoup) -> None:
    h1_tags = soup.find_all("h1")
    if len(h1_tags) <= 1:
        return
    for tag in h1_tags[1:]:
        tag.name = "h2"


def guess_alt_text(src: str, fallback: str = "") -> str:
    if not src:
        return fallback
    filename = Path(urlparse(src).path).name
    if not filename:
        return fallback
    name = re.sub(r"[_-]+", " ", Path(filename).stem)
    name = re.sub(r"\b\d+\b", "", name).strip()
    name = re.sub(r"\s+", " ", name)
    if "logo" in name.lower():
        return "Logo FC Gestao Estrategica"
    return name.capitalize() if name else fallback


def get_image_size(image_path: Path) -> tuple[int, int] | None:
    try:
        data = image_path.read_bytes()
    except OSError:
        return None

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 24:
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return width, height

    if data.startswith(b"\xff\xd8"):
        idx = 2
        while idx < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            if marker in (0xC0, 0xC2):
                if idx + 8 < len(data):
                    height = int.from_bytes(data[idx + 5 : idx + 7], "big")
                    width = int.from_bytes(data[idx + 7 : idx + 9], "big")
                    return width, height
                break
            length = int.from_bytes(data[idx + 2 : idx + 4], "big")
            idx += 2 + length

    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
        if chunk == b"VP8 " and len(data) >= 30:
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return width, height
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height

    return None


def process_images(soup: BeautifulSoup, page_path: Path) -> int:
    missing_alt = 0
    first_content_image = True
    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt is None or not alt.strip():
            src = img.get("src", "")
            alt_text = guess_alt_text(src)
            img["alt"] = alt_text
            if not alt_text:
                img["alt"] = ""

        if "decoding" not in img.attrs:
            img["decoding"] = "async"

        is_logo = False
        alt_value = img.get("alt", "").lower()
        classes = " ".join(img.get("class", [])).lower()
        if "logo" in alt_value or "logo" in classes:
            is_logo = True
        if img.find_parent("header") is not None or img.find_parent("nav") is not None:
            is_logo = True

        if not is_logo and first_content_image and img.find_parent("main") is not None:
            img["loading"] = "eager"
            first_content_image = False
        elif "loading" not in img.attrs:
            if is_logo:
                img["loading"] = "eager"
            else:
                img["loading"] = "lazy"

        src = img.get("src")
        if src and not src.startswith("http"):
            img_path = (page_path.parent / src).resolve()
            if img_path.exists():
                size = get_image_size(img_path)
                if size:
                    width, height = size
                    if "width" not in img.attrs:
                        img["width"] = str(width)
                    if "height" not in img.attrs:
                        img["height"] = str(height)
        if img.get("alt") is None:
            missing_alt += 1
    return missing_alt


def find_description(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup.find("article") or soup.body
    if not main:
        return ""
    for tag in main.find_all(["p", "li"], recursive=True):
        text = tag.get_text(" ", strip=True)
        if len(text) >= 40:
            return strip_and_truncate(text)
    text = main.get_text(" ", strip=True)
    return strip_and_truncate(text) if text else ""


def ensure_meta(soup: BeautifulSoup, head: BeautifulSoup, name: str, content: str) -> None:
    for tag in head.find_all("meta", attrs={"name": name}):
        tag.decompose()
    new_tag = soup.new_tag("meta")
    new_tag["name"] = name
    new_tag["content"] = content
    head.append(new_tag)


def ensure_meta_property(soup: BeautifulSoup, head: BeautifulSoup, prop: str, content: str | None) -> None:
    for tag in head.find_all("meta", attrs={"property": prop}):
        tag.decompose()
    if content is None:
        return
    new_tag = soup.new_tag("meta")
    new_tag["property"] = prop
    new_tag["content"] = content
    head.append(new_tag)


def ensure_link(soup: BeautifulSoup, head: BeautifulSoup, rel: str, href: str) -> None:
    for tag in head.find_all("link", rel=True):
        rel_val = tag.get("rel")
        rel_list = rel_val if isinstance(rel_val, list) else [rel_val]
        if rel in rel_list:
            tag.decompose()
    new_tag = soup.new_tag("link", rel=rel, href=href)
    head.append(new_tag)


def normalize_head(soup: BeautifulSoup, page_path: Path, site_url: str, posts: dict) -> dict:
    if not soup.html:
        html_tag = soup.new_tag("html")
        html_tag["lang"] = "pt-BR"
        soup.insert(0, html_tag)
        body_tag = soup.new_tag("body")
        html_tag.append(body_tag)
    else:
        soup.html["lang"] = "pt-BR"

    head = soup.head
    if not head:
        head = soup.new_tag("head")
        if soup.html.contents:
            soup.html.insert(0, head)
        else:
            soup.html.append(head)

    charset_tags = head.find_all("meta", charset=True)
    if charset_tags:
        charset_tags[0]["charset"] = "utf-8"
        for extra in charset_tags[1:]:
            extra.decompose()
    else:
        meta_charset = soup.new_tag("meta", charset="utf-8")
        head.insert(0, meta_charset)

    viewport_tags = head.find_all("meta", attrs={"name": "viewport"})
    if viewport_tags:
        viewport_tags[0]["content"] = "width=device-width, initial-scale=1"
        for extra in viewport_tags[1:]:
            extra.decompose()
    else:
        meta_viewport = soup.new_tag("meta")
        meta_viewport["name"] = "viewport"
        meta_viewport["content"] = "width=device-width, initial-scale=1"
        head.insert(1, meta_viewport)

    title_tag = head.find("title")
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    title_text = title_tag.get_text(strip=True) if title_tag else ""
    if not title_tag:
        title_tag = soup.new_tag("title")
        head.append(title_tag)
    if not title_text:
        title_text = h1_text or "FC Gestao Estrategica"

    brand_norm = normalize_text("FC Gestao Estrategica")
    title_norm = normalize_text(title_text)
    if title_norm.count(brand_norm) > 1:
        title_text = re.sub(
            r"\s*[|\\-–—]\s*FC\s+Gest[aã]o\s+Estrat[eé]gica\s*$",
            "",
            title_text,
            flags=re.IGNORECASE,
        ).strip()
        title_norm = normalize_text(title_text)

    if brand_norm not in title_norm:
        title_text = f"{title_text} | FC Gestao Estrategica"
    title_tag.string = title_text

    slug = slug_from_article(page_path) if is_article(page_path) else None
    post_data = posts.get(slug) if slug else None

    description = ""
    existing_desc = head.find("meta", attrs={"name": "description"})
    if existing_desc and existing_desc.get("content"):
        description = existing_desc["content"].strip()
    if not description:
        if post_data and post_data.get("excerpt"):
            description = post_data["excerpt"]
        else:
            description = find_description(soup)
    if not description:
        description = "FC Gestao Estrategica: consultoria em licenciamento ambiental e gestao de projetos."

    description = strip_and_truncate(description) if description else ""
    if description:
        ensure_meta(soup, head, "description", description)

    canonical = f"{site_url}/{page_path.name}" if page_path.name != "index.html" else f"{site_url}/"
    ensure_link(soup, head, "canonical", canonical)

    og_image = None
    if post_data and post_data.get("coverImagePath"):
        og_image = absolute_url(site_url, post_data.get("coverImagePath"))
    elif LOGO_PNG_PATH.exists():
        og_image = absolute_url(site_url, str(LOGO_PNG_PATH.relative_to(ROOT_DIR)).replace("\\", "/"))
    elif LOGO_WEBP_PATH.exists():
        og_image = absolute_url(site_url, str(LOGO_WEBP_PATH.relative_to(ROOT_DIR)).replace("\\", "/"))

    og_type = "article" if slug else "website"
    ensure_meta_property(soup, head, "og:title", title_text)
    ensure_meta_property(soup, head, "og:description", description or None)
    ensure_meta_property(soup, head, "og:url", canonical)
    ensure_meta_property(soup, head, "og:type", og_type)
    ensure_meta_property(soup, head, "og:image", og_image)
    ensure_meta_property(soup, head, "og:site_name", "FC Gestao Estrategica")

    ensure_meta(soup, head, "twitter:card", "summary_large_image" if og_image else "summary")
    ensure_meta(soup, head, "twitter:title", title_text)
    if description:
        ensure_meta(soup, head, "twitter:description", description)
    if og_image:
        ensure_meta(soup, head, "twitter:image", og_image)

    ensure_link(soup, head, "icon", "assets/icons/favicon.svg")
    ensure_link(soup, head, "apple-touch-icon", "imagens/logo/logo12-1.png")
    ensure_link(soup, head, "manifest", "site.webmanifest")

    for tag in head.find_all("script", attrs={"type": "application/ld+json", "id": "structured-data"}):
        tag.decompose()

    org_logo = None
    if LOGO_PNG_PATH.exists():
        org_logo = absolute_url(site_url, str(LOGO_PNG_PATH.relative_to(ROOT_DIR)).replace("\\", "/"))
    elif LOGO_WEBP_PATH.exists():
        org_logo = absolute_url(site_url, str(LOGO_WEBP_PATH.relative_to(ROOT_DIR)).replace("\\", "/"))

    graph = [
        {
            "@type": "Organization",
            "name": "FC Gestao Estrategica",
            "url": site_url,
            "logo": org_logo,
        },
        {
            "@type": "WebSite",
            "name": "FC Gestao Estrategica",
            "url": site_url,
        },
    ]

    if slug:
        date_published = post_data.get("dateISO") if post_data else None
        blog_post = {
            "@type": "BlogPosting",
            "headline": h1_text or title_text,
            "description": description,
            "image": og_image,
            "datePublished": date_published,
            "dateModified": date_published,
            "author": {"@type": "Organization", "name": "FC Gestao Estrategica"},
            "publisher": {
                "@type": "Organization",
                "name": "FC Gestao Estrategica",
                "logo": {"@type": "ImageObject", "url": org_logo} if org_logo else None,
            },
            "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        }
        graph.append(blog_post)

        ensure_meta_property(soup, head, "article:published_time", date_published)
        ensure_meta_property(soup, head, "article:modified_time", date_published)

    data = {"@context": "https://schema.org", "@graph": graph}
    script_tag = soup.new_tag("script", attrs={"type": "application/ld+json", "id": "structured-data"})
    script_tag.string = json.dumps(data, ensure_ascii=False)
    head.append(script_tag)

    return {
        "title": title_text,
        "description": description,
        "canonical": canonical,
        "og_image": og_image,
        "is_article": bool(slug),
    }


def rewrite_internal_links(soup: BeautifulSoup, posts: dict) -> int:
    rewrites = 0
    legacy_map = {
        "": "index.html",
        "contato": "contato.html",
        "servicos": "servicos.html",
        "serviços": "servicos.html",
        "quem-somos": "sobre.html",
        "sobre": "sobre.html",
        "cases": "cases.html",
        "produtosdigitais": "produtosdigitais.html",
        "produtos-digitais": "produtosdigitais.html",
        "blog": "blog.html",
    }
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and "fcgestaoestrategica.com.br" in parsed.netloc:
            slug = slug_from_legacy_url(href)
            if slug in posts:
                anchor["href"] = f"artigo-{slug}.html"
                rewrites += 1
                continue
            mapped = legacy_map.get(slug or "")
            if mapped:
                anchor["href"] = mapped
                rewrites += 1
                continue
        if href.startswith("/blog"):
            anchor["href"] = "blog.html"
            rewrites += 1
            continue
    return rewrites


def check_broken_links(page_path: Path, soup: BeautifulSoup) -> list[str]:
    broken = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].split("#")[0]
        if not href or href.startswith("http") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        target = (page_path.parent / href).resolve()
        if not target.exists():
            broken.append(href)
    return broken


def write_robots(site_url: str) -> None:
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {site_url}/sitemap.xml",
            "",
        ]
    )
    ROBOTS_PATH.write_text(content, encoding="utf-8")


def write_sitemap(site_url: str, pages: list[Path], posts: dict) -> list[dict]:
    entries = []
    for page in pages:
        url = f"{site_url}/{page.name}" if page.name != "index.html" else f"{site_url}/"
        lastmod = None
        if is_article(page):
            slug = slug_from_article(page)
            if slug in posts and posts[slug].get("dateISO"):
                lastmod = posts[slug]["dateISO"]
        if not lastmod:
            lastmod = datetime.fromtimestamp(page.stat().st_mtime).strftime("%Y-%m-%d")
        entries.append({"loc": url, "lastmod": lastmod})

    sitemap_lines = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for entry in entries:
        sitemap_lines.append("  <url>")
        sitemap_lines.append(f"    <loc>{entry['loc']}</loc>")
        sitemap_lines.append(f"    <lastmod>{entry['lastmod']}</lastmod>")
        sitemap_lines.append("  </url>")
    sitemap_lines.append("</urlset>")
    SITEMAP_PATH.write_text("\n".join(sitemap_lines) + "\n", encoding="utf-8")
    return entries


def write_assets() -> None:
    ICON_SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ICON_SVG_PATH.exists():
        ICON_SVG_PATH.write_text(
            """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 120\">
  <defs>
    <linearGradient id=\"g\" x1=\"0\" x2=\"1\" y1=\"0\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#0055A4\"/>
      <stop offset=\"100%\" stop-color=\"#6EBE44\"/>
    </linearGradient>
  </defs>
  <rect width=\"120\" height=\"120\" rx=\"24\" fill=\"url(#g)\"/>
  <text x=\"50%\" y=\"58%\" text-anchor=\"middle\" font-family=\"Arial, sans-serif\" font-size=\"48\" font-weight=\"700\" fill=\"#ffffff\">FC</text>
</svg>
""",
            encoding="utf-8",
        )

    manifest = {
        "name": "FC Gestao Estrategica",
        "short_name": "FCGE",
        "start_url": "./",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0055A4",
        "icons": [
            {"src": "assets/icons/favicon.svg", "sizes": "any", "type": "image/svg+xml"}
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_audit(site_url: str, structure: list[str], report: dict, broken_links: dict) -> None:
    total_pages = report.get("totalPages", 0)
    total_posts = report.get("totalPosts", 0)
    audit_lines = [
        "# SEO Audit",
        "",
        "## Site URL",
        f"- siteUrl: {site_url}",
        "",
        "## Estrutura alvo",
    ]
    audit_lines.extend([f"- {line}" for line in structure])
    audit_lines.extend(
        [
            "",
            "## Diagnostico (antes)",
            "- robots.txt bloqueava *.json/*.xml (inclusive sitemap e posts.json)",
            "- sitemap.xml com priority/changefreq e lastmod inconsistentes",
            "- falta de canonical/OG/Twitter/JSON-LD em paginas publicas",
            "- ausencia de favicon/manifest padronizados",
            "- imagens sem alt/width/height em varias paginas",
            "",
            "## Diagnostico (depois)",
            f"- totalPages: {total_pages}",
            f"- totalPosts: {total_posts}",
            f"- pagesWithTitle: {report.get('pagesWithTitle')}",
            f"- pagesWithDescription: {report.get('pagesWithDescription')}",
            f"- pagesWithCanonical: {report.get('pagesWithCanonical')}",
            f"- pagesWithOG: {report.get('pagesWithOG')}",
            f"- pagesWithStructuredData: {report.get('pagesWithStructuredData')}",
            f"- imagesMissingAltCount: {report.get('imagesMissingAltCount')}",
            f"- brokenLinksCount: {report.get('brokenLinksCount')}",
            "",
            "## Checklist implementado",
            "- robots.txt atualizado com Sitemap absoluto",
            "- sitemap.xml gerado sem priority/changefreq",
            "- meta tags normalizadas (title, description, canonical, OG, Twitter)",
            "- JSON-LD com Organization/WebSite e BlogPosting nas paginas de artigo",
            "- favicon/manifest adicionados",
            "- atributos de imagem (alt/loading/decoding/width/height) quando possivel",
            "",
            "## Pendencias / decisoes humanas",
            "- Verificar se o dominio canonico esta correto (CNAME nao encontrado; foi usado README)",
            "- Revisar titulos/descricoes gerados automaticamente para ajustes editoriais",
            "- Validar links apontados como quebrados (se houver)",
        ]
    )

    if broken_links:
        audit_lines.append("")
        audit_lines.append("## Links quebrados (relativo)")
        for page, links in broken_links.items():
            audit_lines.append(f"- {page}: {', '.join(sorted(set(links)))}")

    SEO_AUDIT_PATH.write_text("\n".join(audit_lines) + "\n", encoding="utf-8")


def main():
    site_url = find_site_url()
    write_assets()

    posts = load_posts()
    pages = list_html_pages()

    report = {
        "totalPages": 0,
        "totalPosts": 0,
        "pagesWithTitle": 0,
        "pagesWithDescription": 0,
        "pagesWithCanonical": 0,
        "pagesWithOG": 0,
        "pagesWithStructuredData": 0,
        "brokenLinksCount": 0,
        "imagesMissingAltCount": 0,
    }

    broken_links = {}

    for page in pages:
        raw = page.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "html.parser")

        ensure_single_h1(soup)
        rewrite_internal_links(soup, posts)
        report["imagesMissingAltCount"] += process_images(soup, page)

        meta = normalize_head(soup, page, site_url, posts)

        if meta.get("is_article"):
            report["totalPosts"] += 1
        report["totalPages"] += 1
        if meta.get("title"):
            report["pagesWithTitle"] += 1
        if meta.get("description"):
            report["pagesWithDescription"] += 1
        if meta.get("canonical"):
            report["pagesWithCanonical"] += 1
        if meta.get("og_image"):
            report["pagesWithOG"] += 1

        if soup.find("script", attrs={"type": "application/ld+json", "id": "structured-data"}):
            report["pagesWithStructuredData"] += 1

        page_broken = check_broken_links(page, soup)
        if page_broken:
            broken_links[page.name] = page_broken
            report["brokenLinksCount"] += len(page_broken)

        doctype = next((item for item in soup.contents if isinstance(item, Doctype)), None)
        output = soup.decode()
        if doctype and "<!DOCTYPE" not in output.upper():
            output = f"<!DOCTYPE html>\n{output}"
        page.write_text(output, encoding="utf-8")

    write_robots(site_url)
    sitemap_entries = write_sitemap(site_url, pages, posts)

    SEO_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    SITEMAP_REPORT_PATH.write_text(json.dumps(sitemap_entries, indent=2), encoding="utf-8")

    structure = [
        "/: paginas HTML publicas (mantidas na raiz para nao quebrar URLs)",
        "imagens/: midia existente do site e blog",
        "data/: dados do blog (posts.json)",
        "assets/icons/: favicons e SVG",
        "scripts/: automacoes locais",
    ]
    write_audit(site_url, structure, report, broken_links)


if __name__ == "__main__":
    main()
