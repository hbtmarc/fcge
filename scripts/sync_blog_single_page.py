
#!/usr/bin/env python3
"""Sync legacy blog posts into a single-page blog.html and clean article files."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import ssl
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


BASE_URL = "https://www.fcgestaoestrategica.com.br"
BLOG_INDEX = f"{BASE_URL}/blog/"
ROOT_DIR = Path(__file__).resolve().parents[1]
BLOG_HTML_PATH = ROOT_DIR / "blog.html"
POSTS_JSON_PATH = ROOT_DIR / "data" / "posts.json"
ASSETS_DIR = ROOT_DIR / "assets" / "blog"
REPORT_PATH = ROOT_DIR / "blog-singlepage-report.json"
SITEMAP_PATH = ROOT_DIR / "sitemap.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

EXCLUDE_SLUGS = {
    "",
    "blog",
    "contato",
    "servicos",
    "sobre",
    "quem-somos",
    "cases",
    "produtosdigitais",
    "produtos-digitais",
    "index",
    "wp-content",
    "wp-json",
    "category",
    "tag",
    "author",
}

MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

SSL_CONTEXT = ssl._create_unverified_context()


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[bytes, str | None, str]:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type")
        encoding = response.headers.get_content_charset() or "utf-8"
    return data, content_type, encoding


def fetch(url: str, retries: int = 3) -> str:
    backoff = 1
    for attempt in range(retries):
        try:
            data, _, encoding = http_get(url, headers=HEADERS, timeout=30)
            return data.decode(encoding, errors="replace")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise RuntimeError(f"Failed to fetch {url}")


def slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc and "fcgestaoestrategica.com.br" not in parsed.netloc:
        return ""
    path = parsed.path.strip("/")
    if not path:
        return ""
    parts = [part for part in path.split("/") if part]
    if len(parts) != 1:
        return ""
    slug = parts[0]
    if slug in EXCLUDE_SLUGS:
        return ""
    if "." in slug:
        return ""
    return slug


def parse_date_text(text: str) -> str | None:
    if not text:
        return None
    value = text.strip()
    try:
        iso_val = value.replace("Z", "+00:00")
        return datetime.fromisoformat(iso_val).date().isoformat()
    except Exception:
        pass

    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if match:
        day, month, year = match.groups()
        year_int = int(year)
        if year_int < 100:
            year_int += 2000
        try:
            return datetime(year_int, int(month), int(day)).date().isoformat()
        except Exception:
            return None

    lowered = value.lower()
    match = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", lowered)
    if match:
        day, month_name, year = match.groups()
        month = MONTHS_PT.get(month_name)
        if month:
            try:
                return datetime(int(year), month, int(day)).date().isoformat()
            except Exception:
                return None
    return None


def date_human_ptbr(date_iso: str) -> str:
    try:
        date_obj = datetime.fromisoformat(date_iso).date()
    except Exception:
        return date_iso
    months = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    return f"{date_obj.day} de {months[date_obj.month - 1]} de {date_obj.year}"


def discover_post_urls() -> tuple[list[str], dict[str, str]]:
    urls: list[str] = []
    seen: set[str] = set()
    empty_streak = 0
    for page_num in range(1, 10):
        url = BLOG_INDEX if page_num == 1 else f"{BLOG_INDEX}{page_num}/"
        try:
            html_text = fetch(url)
        except Exception:
            break

        page_urls: list[str] = []
        for href in re.findall(r'href=["\\\']([^"\\\']+)["\\\']', html_text, flags=re.IGNORECASE):
            abs_url = urljoin(BASE_URL, href)
            slug = slug_from_url(abs_url)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            page_urls.append(f"{BASE_URL}/{slug}/")

        if not page_urls:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
            urls.extend(page_urls)

    return urls, {}


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
            return val
    srcset = img_tag.get("srcset") or img_tag.get("nitro-lazy-srcset") or img_tag.get("data-srcset")
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        if first and not first.startswith("data:"):
            return first
    return None


def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[<>:\"/\\|?*]", "-", name)
    name = name.replace(" ", "-")
    name = re.sub(r"-+", "-", name)
    return name or "imagem"


def ensure_extension(filename: str, content_type: str | None) -> str:
    if "." in filename:
        return filename
    if not content_type:
        return f"{filename}.jpg"
    if "png" in content_type:
        return f"{filename}.png"
    if "webp" in content_type:
        return f"{filename}.webp"
    if "gif" in content_type:
        return f"{filename}.gif"
    return f"{filename}.jpg"


def copy_local_asset(src_path: Path, slug: str, report: dict[str, Any]) -> str | None:
    if not src_path.exists():
        return None
    dest_dir = ASSETS_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(src_path.name)
    dest_path = dest_dir / filename
    if not dest_path.exists():
        shutil.copy2(src_path, dest_path)
        report["totalImagesDownloaded"] += 1
    return dest_path.relative_to(ROOT_DIR).as_posix()


def download_asset(url: str, slug: str, report: dict[str, Any]) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    filename = safe_filename(Path(parsed.path).name or "imagem")
    dest_dir = ASSETS_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return dest_path.relative_to(ROOT_DIR).as_posix()

    try:
        data, content_type, _ = http_get(url, headers=HEADERS, timeout=30)
        filename = ensure_extension(dest_path.name, content_type)
        dest_path = dest_dir / filename
        dest_path.write_bytes(data)
        report["totalImagesDownloaded"] += 1
        return dest_path.relative_to(ROOT_DIR).as_posix()
    except Exception:
        return None


def localize_image(src: str, slug: str, report: dict[str, Any]) -> str | None:
    if not src or src.startswith("data:"):
        return None
    if src.startswith("assets/blog/"):
        return src

    if src.startswith("//"):
        src = f"https:{src}"

    if src.startswith("http://") or src.startswith("https://"):
        return download_asset(src, slug, report)

    if src.startswith("/"):
        local_path = ROOT_DIR / src.lstrip("/")
        if local_path.exists():
            return copy_local_asset(local_path, slug, report)
        return download_asset(urljoin(BASE_URL, src), slug, report)

    local_path = ROOT_DIR / src
    if local_path.exists():
        return copy_local_asset(local_path, slug, report)

    return download_asset(urljoin(BASE_URL, src), slug, report)

def extract_body_html(html_text: str) -> str:
    if not html_text:
        return ""

    widgets = re.findall(
        r'<div[^>]+class=["\'][^"\']*elementor-widget-container[^"\']*["\'][^>]*>(.*?)</div>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if widgets:
        return "\n".join(widgets)

    for pattern in [
        r"<article[^>]*>(.*?)</article>",
        r'<div[^>]+class=["\'][^"\']*entry-content[^"\']*["\'][^>]*>(.*?)</div>',
    ]:
        match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)

    return ""


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def find_first_img_url(html_text: str) -> str | None:
    match = re.search(r"<img[^>]+(?:data-src|data-lazy-src|nitro-lazy-src|data-original|src)=[\"']([^\"']+)[\"']", html_text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def rewrite_images_in_html(html_text: str, slug: str, report: dict[str, Any]) -> str:
    def replace_img(match: re.Match) -> str:
        tag = match.group(0)
        attrs = dict(re.findall(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']', tag))
        src = (
            attrs.get("data-src")
            or attrs.get("data-lazy-src")
            or attrs.get("nitro-lazy-src")
            or attrs.get("data-original")
            or attrs.get("src")
        )
        if not src or src.startswith("data:"):
            return tag
        marker = "blog.html#post-"
        if marker in src:
            tail = src.split(marker, 1)[1]
            if tail.startswith(slug):
                filename = tail[len(slug):].lstrip("/").lstrip("-")
                src = f"imagens/blog/{slug}/{filename}"
        local_path = localize_image(src, slug, report)
        if not local_path:
            return tag
        kept_keys = ["alt", "title", "class", "width", "height", "id", "style"]
        kept_attrs = []
        for key in kept_keys:
            if key in attrs:
                kept_attrs.append(f'{key}="{html.escape(attrs[key], quote=True)}"')
        extra = f" {' '.join(kept_attrs)}" if kept_attrs else ""
        return f'<img src="{local_path}" loading="lazy" decoding="async"{extra}>'

    return re.sub(r"<img\b[^>]*>", replace_img, html_text, flags=re.IGNORECASE)


def replace_post_href_links(html_text: str, slug_map: dict[str, str]) -> tuple[str, int]:
    total = 0
    updated = html_text
    for slug, target in slug_map.items():
        patterns = [
            rf'href=["\']https?://(?:www\\.)?fcgestaoestrategica\\.com\\.br/{re.escape(slug)}/?["\']',
            rf'href=["\']/{re.escape(slug)}/?["\']',
        ]
        for pattern in patterns:
            updated, count = re.subn(pattern, f'href="{target}"', updated, flags=re.IGNORECASE)
            total += count
    return updated, total


def clean_content_html(
    html_text: str,
    slug: str,
    slug_map: dict[str, str],
    report: dict[str, Any],
) -> str:
    cleaned = re.sub(r"<(script|style|noscript)[^>]*>.*?</\\1>", "", html_text, flags=re.IGNORECASE | re.DOTALL)
    cleaned, count = replace_article_links_in_text(cleaned, slug_map)
    report["brokenInternalRefsFixedCount"] += count
    cleaned, count = replace_post_href_links(cleaned, slug_map)
    report["brokenInternalRefsFixedCount"] += count
    cleaned = rewrite_images_in_html(cleaned, slug, report)
    cleaned = re.sub(r"<h1(\b[^>]*)>", r"<h2\\1>", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</h1>", "</h2>", cleaned, flags=re.IGNORECASE)
    return cleaned


def make_excerpt(text: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def extract_tag_text(html_text: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return strip_tags(match.group(1))


def extract_meta_content(html_text: str, attr: str, key: str) -> str:
    pattern = re.compile(
        rf"<meta[^>]+{attr}=[\"']{re.escape(key)}[\"'][^>]*content=[\"']([^\"']+)[\"']",
        flags=re.IGNORECASE,
    )
    match = pattern.search(html_text)
    return match.group(1).strip() if match else ""


def extract_post_data(
    url: str,
    slug: str,
    index_dates: dict[str, str],
    slug_map: dict[str, str],
    report: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        html_text = fetch(url)
    except Exception as exc:
        report["falhas"].append({"url": url, "motivo": f"fetch failed: {exc}"})
        return None

    title = extract_tag_text(html_text, "h1") or extract_meta_content(html_text, "property", "og:title") or slug

    meta_date = extract_meta_content(html_text, "property", "article:published_time")
    date_iso = parse_date_text(meta_date) if meta_date else None
    if not date_iso:
        date_iso = index_dates.get(slug)
    if not date_iso:
        date_iso = datetime.utcnow().date().isoformat()

    date_human = date_human_ptbr(date_iso)

    category = extract_meta_content(html_text, "property", "article:section") or "Blog"
    cover_url = extract_meta_content(html_text, "property", "og:image")

    body_html = extract_body_html(html_text)
    if not body_html:
        report["falhas"].append({"url": url, "motivo": "conteudo vazio"})
        return None

    clean_html = clean_content_html(body_html, slug, slug_map, report)

    body_text = strip_tags(clean_html)
    excerpt = extract_meta_content(html_text, "name", "description")
    if not excerpt:
        excerpt = make_excerpt(body_text)

    cover_path = None
    if cover_url:
        cover_path = localize_image(cover_url, slug, report)
    if not cover_path:
        first_img = find_first_img_url(clean_html)
        if first_img:
            cover_path = localize_image(first_img, slug, report) or first_img

    return {
        "slug": slug,
        "title": title,
        "dateISO": date_iso,
        "dateHumanPTBR": date_human,
        "category": category,
        "excerpt": excerpt,
        "coverImagePath": cover_path or "",
        "contentHtml": clean_html,
    }


def load_or_sync_posts(refresh: bool, slug_map: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = {
        "totalPosts": 0,
        "totalImagesDownloaded": 0,
        "brokenInternalRefsFixedCount": 0,
        "falhas": [],
    }

    if POSTS_JSON_PATH.exists() and not refresh:
        posts = json.loads(POSTS_JSON_PATH.read_text(encoding="utf-8"))
        return posts, report

    post_urls, index_dates = discover_post_urls()
    posts: list[dict[str, Any]] = []
    for url in post_urls:
        slug = slug_from_url(url)
        if not slug:
            continue
        post = extract_post_data(url, slug, index_dates, slug_map, report)
        if post:
            posts.append(post)

    posts.sort(key=lambda item: item.get("dateISO", ""), reverse=True)
    return posts, report


def process_existing_posts(
    posts: list[dict[str, Any]],
    slug_map: dict[str, str],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    processed: list[dict[str, Any]] = []
    for post in posts:
        slug = post.get("slug", "")
        if not slug:
            continue
        content_html = post.get("contentHtml", "")
        cleaned_html = clean_content_html(content_html, slug, slug_map, report)
        post["contentHtml"] = cleaned_html

        cover_path = post.get("coverImagePath", "")
        if cover_path:
            if "blog.html#post-" in cover_path:
                tail = cover_path.split("blog.html#post-", 1)[1]
                if tail.startswith(slug):
                    filename = tail[len(slug):].lstrip("/").lstrip("-")
                    cover_path = f"imagens/blog/{slug}/{filename}"
            post["coverImagePath"] = localize_image(cover_path, slug, report) or cover_path
        else:
            first_img = find_first_img_url(cleaned_html)
            if first_img:
                post["coverImagePath"] = first_img

        if not post.get("excerpt"):
            post["excerpt"] = make_excerpt(strip_tags(cleaned_html))

        if post.get("dateISO") and not post.get("dateHumanPTBR"):
            post["dateHumanPTBR"] = date_human_ptbr(post["dateISO"])

        processed.append(post)

    processed.sort(key=lambda item: item.get("dateISO", ""), reverse=True)
    return processed

def render_search_controls(categories: list[str]) -> str:
    options = ['<option value="all">Todas as categorias</option>']
    for category in categories:
        options.append(f'<option value="{html.escape(category.lower())}">{html.escape(category)}</option>')
    return f"""
<div id="blog-filters" class="mb-10 flex flex-col md:flex-row gap-4 items-start md:items-end">
  <div class="w-full md:flex-1">
    <label class="text-sm font-semibold text-slate-700" for="blog-search">Buscar</label>
    <input id="blog-search" type="search" placeholder="Buscar por titulo ou texto" class="mt-2 w-full rounded-lg border border-slate-200 px-4 py-3 text-slate-700 focus:border-[--brand-blue] focus:outline-none focus:ring-2 focus:ring-[--brand-blue]/20"/>
  </div>
  <div class="w-full md:w-64">
    <label class="text-sm font-semibold text-slate-700" for="blog-category">Categoria</label>
    <select id="blog-category" class="mt-2 w-full rounded-lg border border-slate-200 px-4 py-3 text-slate-700 focus:border-[--brand-blue] focus:outline-none focus:ring-2 focus:ring-[--brand-blue]/20">
      {"".join(options)}
    </select>
  </div>
</div>
""".strip()


def render_cards(posts: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for idx, post in enumerate(posts):
        delay = idx * 100
        category = post.get("category") or "Blog"
        data_search = f"{post.get('title','')} {post.get('excerpt','')} {category}".strip().lower()
        image_html = ""
        if post.get("coverImagePath"):
            image_html = (
                f'<img src="{html.escape(post["coverImagePath"])}" alt="{html.escape(post["title"])}" '
                'class="w-full h-48 object-cover" decoding="async" loading="lazy"/>'
            )
        else:
            image_html = '<div class="w-full h-48 bg-gradient-to-r from-slate-200 via-slate-100 to-slate-200"></div>'

        cards.append(
            f"""
<a href="#post-{html.escape(post['slug'])}" class="post-card block bg-white rounded-lg shadow-md overflow-hidden transition hover:shadow-xl animated-item fade-in" style="transition-delay: {delay}ms;" data-post-card data-category="{html.escape(category.lower())}" data-search="{html.escape(data_search)}">
  {image_html}
  <div class="p-6">
    <p class="text-sm text-slate-500">{html.escape(category)} • {html.escape(post.get("dateHumanPTBR",""))}</p>
    <h3 class="mt-2 text-xl font-bold text-slate-900">{html.escape(post["title"])}</h3>
    <p class="mt-2 text-slate-600">{html.escape(post.get("excerpt",""))}</p>
  </div>
</a>
""".strip()
        )
    return "\n".join(cards)


def render_post_jsonld(post: dict[str, Any], site_url: str) -> str:
    logo_url = f"{site_url}/imagens/logo/logo12-1.png"
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "datePublished": post["dateISO"],
        "dateModified": post["dateISO"],
        "author": {"@type": "Organization", "name": "FC Gestao Estrategica"},
        "publisher": {
            "@type": "Organization",
            "name": "FC Gestao Estrategica",
            "logo": {"@type": "ImageObject", "url": logo_url},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{site_url}/blog.html#post-{post['slug']}"},
    }
    if post.get("coverImagePath"):
        data["image"] = [f"{site_url}/{post['coverImagePath'].lstrip('/')}"]
    return json.dumps(data, ensure_ascii=False)


def render_gallery_section(posts: list[dict[str, Any]]) -> str:
    categories = sorted({p.get("category", "Blog") for p in posts if p.get("category")})
    return f"""
<section id="blog-gallery" class="py-20 sm:py-28 animated-item fade-in">
  <div class="container mx-auto px-6">
    <div id="blog"></div>
    {render_search_controls(categories)}
    <p id="blog-results" class="text-sm text-slate-500 mb-8"></p>
    <div class="grid md:grid-cols-2 lg:grid-cols-3 gap-8" id="posts-container">
      {render_cards(posts)}
    </div>
  </div>
</section>
""".strip()


def render_reader_section(posts: list[dict[str, Any]], site_url: str) -> str:
    articles: list[str] = []
    for post in posts:
        cover_html = ""
        if post.get("coverImagePath"):
            cover_html = (
                f'<img src="{html.escape(post["coverImagePath"])}" alt="{html.escape(post["title"])}" '
                'class="w-full h-auto rounded-xl shadow-lg my-8" decoding="async" loading="lazy"/>'
            )

        articles.append(
            f"""
<article id="post-{html.escape(post['slug'])}" data-post-article class="post-article bg-white rounded-2xl shadow-lg p-8 md:p-10 animated-item fade-in is-hidden">
  <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
    <div>
      <p class="text-sm text-slate-500">{html.escape(post.get("category","Blog"))} • {html.escape(post.get("dateHumanPTBR",""))}</p>
      <h2 class="text-2xl md:text-3xl font-bold text-slate-900 mt-2" tabindex="-1">{html.escape(post["title"])}</h2>
      <p class="text-slate-600 mt-3">{html.escape(post.get("excerpt",""))}</p>
    </div>
    <a href="#blog" class="inline-flex items-center justify-center text-white font-bold py-3 px-6 rounded-lg cta-button cta-button-standard">Voltar ao Blog</a>
  </div>
  {cover_html}
  <div class="prose max-w-none text-slate-600">
    {post.get("contentHtml", "")}
  </div>
  <div class="mt-8">
    <a href="#blog" class="text-sm font-semibold text-[--brand-blue] hover:underline">Voltar ao Blog</a>
  </div>
  <script type="application/ld+json">{render_post_jsonld(post, site_url)}</script>
</article>
""".strip()
        )

    return f"""
<section id="blog-reader" class="py-20 sm:py-28 bg-slate-50 is-hidden">
  <div class="container mx-auto px-6">
    <div id="blog-reader-container" class="space-y-12">
      {"".join(articles)}
    </div>
  </div>
</section>
""".strip()


def get_site_url() -> str:
    if not BLOG_HTML_PATH.exists():
        return "https://hbtmarc.github.io/fcge"
    html_text = BLOG_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html_text,
        flags=re.IGNORECASE,
    )
    if match:
        href = match.group(1).rstrip("/")
        if href.endswith("/blog.html"):
            return href[: -len("/blog.html")]
    return "https://hbtmarc.github.io/fcge"


def ensure_hidden_style(html_text: str) -> str:
    if ".is-hidden" in html_text:
        return html_text
    if re.search(r"</style>", html_text, flags=re.IGNORECASE):
        return re.sub(
            r"</style>",
            "\n        .is-hidden { display: none !important; }\n</style>",
            html_text,
            count=1,
            flags=re.IGNORECASE,
        )
    return re.sub(
        r"</head>",
        "<style>\n        .is-hidden { display: none !important; }\n    </style>\n</head>",
        html_text,
        count=1,
        flags=re.IGNORECASE,
    )


def replace_section(html_text: str, section_id: str, new_html: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"<section[^>]*\bid=[\"']{re.escape(section_id)}[\"'][^>]*>.*?</section>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if pattern.search(html_text):
        return pattern.sub(new_html, html_text, count=1), True
    return html_text, False


def update_blog_html(posts: list[dict[str, Any]]) -> None:
    html_text = BLOG_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    html_text = ensure_hidden_style(html_text)

    html_text = re.sub(
        r"<script[^>]*id=[\"']blog-(interactions|spa)[\"'][^>]*>.*?</script>",
        "",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"<script[^>]*id=[\"']posts-data[\"'][^>]*>.*?</script>",
        "",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"<section[^>]*id=[\"']blog-back-to-top[\"'][^>]*>.*?</section>",
        "",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"<section[^>]*>.*?id=[\"']blog-back-to-top[\"'].*?</section>",
        "",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    site_url = get_site_url()
    gallery_html = render_gallery_section(posts)
    reader_html = render_reader_section(posts, site_url)

    html_text, gallery_replaced = replace_section(html_text, "blog-gallery", gallery_html)
    if not gallery_replaced:
        html_text, gallery_replaced = replace_section(html_text, "blog-list", gallery_html)

    html_text, reader_replaced = replace_section(html_text, "blog-reader", reader_html)
    if not reader_replaced:
        html_text, reader_replaced = replace_section(html_text, "blog-details", reader_html)

    if not gallery_replaced:
        hero_match = re.search(
            r"(<section\b[^>]*class=[\"'][^\"']*page-header[^\"']*[\"'][^>]*>.*?</section>)",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if hero_match:
            hero_block = hero_match.group(1)
            html_text = html_text.replace(
                hero_block,
                f"{hero_block}\n{gallery_html}\n{reader_html}",
                1,
            )

    if "id=\"blog-gallery\"" not in html_text or "id=\"blog-reader\"" not in html_text:
        main_match = re.search(r"(<main[^>]*>)(.*?)(</main>)", html_text, flags=re.IGNORECASE | re.DOTALL)
        if main_match:
            html_text = html_text.replace(
                main_match.group(0),
                f"{main_match.group(1)}\n{gallery_html}\n{reader_html}\n{main_match.group(3)}",
                1,
            )

    script_text = """
document.addEventListener("DOMContentLoaded", () => {
  const animationObserver = new IntersectionObserver(entries => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
      }
    });
  }, {
    threshold: 0.15,
    rootMargin: "0px 0px -50px 0px"
  });

  document.querySelectorAll('.animated-item').forEach(item => {
    animationObserver.observe(item);
  });

  const mobileMenuButton = document.getElementById('mobile-menu-button');
  const closeMobileMenuButton = document.getElementById('close-mobile-menu');
  const mobileMenu = document.getElementById('mobile-menu');

  const openMenu = () => mobileMenu && mobileMenu.classList.remove('-translate-x-full');
  const closeMenu = () => mobileMenu && mobileMenu.classList.add('-translate-x-full');

  if (mobileMenuButton) mobileMenuButton.addEventListener('click', openMenu);
  if (closeMobileMenuButton) closeMobileMenuButton.addEventListener('click', closeMenu);

  const gallery = document.getElementById('blog-gallery');
  const reader = document.getElementById('blog-reader');
  const cards = Array.from(document.querySelectorAll('[data-post-card]'));
  const articles = Array.from(document.querySelectorAll('[data-post-article]'));
  const header = document.getElementById('header') || document.querySelector('header');

  const searchInput = document.getElementById('blog-search');
  const categorySelect = document.getElementById('blog-category');
  const results = document.getElementById('blog-results');

  const normalize = (value) => (value || '')
    .toString()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

  const applyFilters = () => {
    if (!cards.length) return;
    const query = normalize(searchInput ? searchInput.value : '');
    const category = categorySelect ? categorySelect.value : 'all';
    let visible = 0;

    cards.forEach(card => {
      const text = normalize(card.getAttribute('data-search'));
      const cardCategory = card.getAttribute('data-category') || '';
      const matchesQuery = !query || text.includes(query);
      const matchesCategory = category === 'all' || cardCategory === category;
      const show = matchesQuery && matchesCategory;
      card.classList.toggle('is-hidden', !show);
      if (show) visible += 1;
    });

    if (results) {
      results.textContent = visible ? `${visible} artigo(s) encontrados` : 'Nenhum artigo encontrado.';
    }
  };

  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (categorySelect) categorySelect.addEventListener('change', applyFilters);
  applyFilters();

  const scrollToElement = (element) => {
    if (!element) return;
    const headerOffset = header ? header.offsetHeight + 16 : 80;
    const top = element.getBoundingClientRect().top + window.pageYOffset - headerOffset;
    window.scrollTo({ top, behavior: 'smooth' });
  };

  const showGallery = () => {
    if (gallery) gallery.classList.remove('is-hidden');
    if (reader) reader.classList.add('is-hidden');
    articles.forEach(article => article.classList.add('is-hidden'));
    scrollToElement(gallery || document.body);
  };

  const showPost = (slug) => {
    if (!slug) return showGallery();
    const targetId = `post-${slug}`;
    const target = document.getElementById(targetId);
    if (!target) return showGallery();
    if (gallery) gallery.classList.add('is-hidden');
    if (reader) reader.classList.remove('is-hidden');
    articles.forEach(article => article.classList.toggle('is-hidden', article !== target));
    const title = target.querySelector('h2');
    if (title) {
      title.setAttribute('tabindex', '-1');
      title.focus({ preventScroll: true });
    }
    scrollToElement(target);
  };

  const handleHash = () => {
    const hash = (location.hash || '').replace('#', '');
    if (!hash || hash === 'blog') {
      showGallery();
      return;
    }
    if (hash.startsWith('post-')) {
      showPost(hash.replace('post-', ''));
      return;
    }
    showGallery();
  };

  handleHash();
  window.addEventListener('hashchange', handleHash);
});
""".strip()
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", f"<script id=\"blog-spa\">{script_text}</script></body>", 1)
    else:
        html_text += f"\n<script id=\"blog-spa\">{script_text}</script>\n"

    BLOG_HTML_PATH.write_text(html_text, encoding="utf-8")

def update_sitemap() -> None:
    if not SITEMAP_PATH.exists():
        return
    tree = ET.parse(SITEMAP_PATH)
    root = tree.getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    removed = False
    for url in list(root.findall("sm:url", ns)):
        loc = url.find("sm:loc", ns)
        if loc is not None and "/artigo-" in (loc.text or ""):
            root.remove(url)
            removed = True
    if removed:
        tree.write(SITEMAP_PATH, encoding="utf-8", xml_declaration=True)


def collect_article_files() -> list[Path]:
    article_files: list[Path] = []
    for path in ROOT_DIR.rglob("*.html"):
        if path.name == "blog.html":
            continue
        stem = path.stem.lower()
        if stem.startswith("artigo-") or stem.startswith("post-"):
            article_files.append(path)
            continue
        if "artigo" in stem and path.name.endswith(".html"):
            article_files.append(path)
            continue
        if path.parent.name.lower() in {"blog", "posts"}:
            article_files.append(path)
    return sorted(set(article_files))


def slug_from_article_path(path: Path) -> str:
    name = path.stem
    if name.startswith("artigo-"):
        return name.replace("artigo-", "", 1)
    if name.startswith("post-"):
        return name.replace("post-", "", 1)
    if path.parent.name.lower() in {"blog", "posts"}:
        return name
    if name.startswith("artigo"):
        return name.replace("artigo", "", 1).lstrip("-_")
    return name


def replace_article_links_in_text(text: str, slug_map: dict[str, str]) -> tuple[str, int]:
    total = 0
    updated = text
    for slug, target in slug_map.items():
        patterns = [
            rf"(https?://[^\s\"'>]+/)?artigo-{re.escape(slug)}\.html",
            rf"(https?://[^\s\"'>]+/)?post-{re.escape(slug)}\.html",
            rf"(https?://[^\s\"'>]+/)?blog/{re.escape(slug)}\.html",
            rf"(https?://[^\s\"'>]+/)?posts/{re.escape(slug)}\.html",
        ]
        for pattern in patterns:
            updated, count = re.subn(pattern, target, updated, flags=re.IGNORECASE)
            total += count

    def replace_generic(match: re.Match) -> str:
        nonlocal total
        total += 1
        return f"blog.html#post-{match.group('slug')}"

    generic_patterns = [
        r"(?:https?://[^\s\"'>]+/)?(?:artigo-|post-)(?P<slug>[^\"'>\s]+)\.html",
        r"(?:https?://[^\s\"'>]+/)?(?:blog|posts)/(?P<slug>[^\"'>\s]+)\.html",
    ]
    for pattern in generic_patterns:
        updated = re.sub(pattern, replace_generic, updated, flags=re.IGNORECASE)
    return updated, total


def update_internal_references(slug_map: dict[str, str]) -> list[str]:
    updated_files: list[str] = []
    for path in ROOT_DIR.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".html", ".md", ".json", ".xml"}:
            continue
        if path.name.startswith("artigo-") or path.name.startswith("post-"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        new_text, count = replace_article_links_in_text(text, slug_map)
        if count:
            path.write_text(new_text, encoding="utf-8")
            updated_files.append(f"{path.as_posix()} ({count})")
    return updated_files


def cleanup_articles(slug_map: dict[str, str]) -> tuple[list[str], list[str]]:
    updated_files = update_internal_references(slug_map)
    removed_files: list[str] = []
    for path in collect_article_files():
        try:
            path.unlink()
            removed_files.append(path.as_posix())
        except Exception:
            continue
    return updated_files, removed_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync blog single page and clean old article files.")
    parser.add_argument("--refresh", action="store_true", help="Forcar sincronizacao do legado.")
    args = parser.parse_args()

    article_files = collect_article_files()
    slug_map = {slug_from_article_path(path): f"blog.html#post-{slug_from_article_path(path)}" for path in article_files}

    posts, report = load_or_sync_posts(args.refresh, slug_map)
    posts = process_existing_posts(posts, slug_map, report)

    POSTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTS_JSON_PATH.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")

    update_blog_html(posts)
    update_sitemap()

    updated_files, removed_files = cleanup_articles(slug_map)

    remaining_articles = collect_article_files()
    report_payload = {
        "totalPosts": len(posts),
        "totalImagesDownloaded": report["totalImagesDownloaded"],
        "articleHtmlFilesRemovedCount": len(removed_files),
        "removedFiles": removed_files,
        "brokenInternalRefsFixed": updated_files,
        "remainingArticleHtmlFiles": len(remaining_articles),
    }
    REPORT_PATH.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
