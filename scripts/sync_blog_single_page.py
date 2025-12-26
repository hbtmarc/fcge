#!/usr/bin/env python3
"""Sync legacy blog posts into a single-page blog.html with local assets."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
import urllib3
from bs4 import BeautifulSoup

BASE_URL = "https://www.fcgestaoestrategica.com.br"
BLOG_INDEX = f"{BASE_URL}/blog/"
ROOT_DIR = Path(__file__).resolve().parents[1]
BLOG_HTML_PATH = ROOT_DIR / "blog.html"
POSTS_JSON_PATH = ROOT_DIR / "data" / "posts.json"
IMAGES_DIR = ROOT_DIR / "imagens" / "blog"
REPORT_PATH = ROOT_DIR / "blog-sync-report.json"
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
    "serviços",
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


def fetch(session: requests.Session, url: str, retries: int = 3) -> str:
    backoff = 1
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=30, verify=False)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
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
        year = int(year)
        if year < 100:
            year += 2000
        try:
            return datetime(year, int(month), int(day)).date().isoformat()
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


def extract_index_dates(soup: BeautifulSoup) -> dict[str, str]:
    date_map: dict[str, str] = {}
    for card in soup.select("article, .elementor-post, .post"):
        link = card.find("a", href=True)
        if not link:
            continue
        slug = slug_from_url(urljoin(BASE_URL, link["href"]))
        if not slug:
            continue
        date_text = ""
        time_tag = card.find("time")
        if time_tag:
            date_text = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
        if not date_text:
            date_el = card.find(class_=lambda c: c and "date" in c)
            if date_el:
                date_text = date_el.get_text(" ", strip=True)
        date_iso = parse_date_text(date_text)
        if date_iso and slug not in date_map:
            date_map[slug] = date_iso
    return date_map


def discover_post_urls(session: requests.Session) -> tuple[list[str], dict[str, str]]:
    urls: list[str] = []
    seen: set[str] = set()
    index_dates: dict[str, str] = {}
    empty_streak = 0
    for page_num in range(1, 8):
        url = BLOG_INDEX if page_num == 1 else f"{BLOG_INDEX}{page_num}/"
        try:
            html = fetch(session, url)
        except Exception:
            break

        soup = BeautifulSoup(html, "html.parser")
        index_dates.update(extract_index_dates(soup))

        page_urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            abs_url = urljoin(BASE_URL, anchor["href"])
            slug = slug_from_url(abs_url)
            if not slug:
                continue
            if slug in seen:
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

    return urls, index_dates


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


def download_image(session: requests.Session, url: str, slug: str, report: dict[str, Any]) -> str | None:
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
        report["imagensBaixadas"] += 1
        return dest_path.relative_to(ROOT_DIR).as_posix()
    except Exception:
        return None


def extract_body_html(post_div) -> str:
    if not post_div:
        return ""

    for tag in post_div.find_all(["script", "style", "noscript"]):
        tag.decompose()

    widgets = post_div.select(".elementor-widget")
    pieces: list[str] = []

    def append_html(html: str) -> None:
        if html and html.strip():
            pieces.append(html)

    def extract_from_container(container) -> str:
        if not container:
            return ""

        editor = container.select_one(".elementor-text-editor")
        if editor:
            return editor.decode_contents()

        allowed_tags = {
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "li",
            "table",
            "thead",
            "tbody",
            "tr",
            "td",
            "th",
            "blockquote",
            "figure",
            "img",
            "iframe",
            "hr",
        }
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


def rewrite_internal_links(body_soup: BeautifulSoup, slugs: set[str], report: dict[str, Any]) -> None:
    for anchor in body_soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"} and "fcgestaoestrategica.com.br" in parsed.netloc:
            slug = parsed.path.strip("/").split("/")[0]
            if slug in slugs:
                anchor["href"] = f"#post-{slug}"
                report["linksInternosConvertidos"] += 1
                continue
        if href.startswith("/blog"):
            anchor["href"] = "#blog-list"


def clean_content_html(
    session: requests.Session,
    html: str,
    slug: str,
    slugs: set[str],
    report: dict[str, Any],
) -> str:
    body_soup = BeautifulSoup(html, "html.parser")

    rewrite_internal_links(body_soup, slugs, report)

    for img in body_soup.find_all("img"):
        img_url = pick_image_url(img)
        local_path = download_image(session, img_url, slug, report) if img_url else None
        if local_path:
            img["src"] = local_path
        img["loading"] = "lazy"
        img["decoding"] = "async"
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

    for heading in body_soup.find_all("h1"):
        heading.name = "h2"

    return body_soup.decode_contents()


def make_excerpt(text: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1].rstrip() + "…"


def extract_post_data(
    session: requests.Session,
    url: str,
    slug: str,
    index_dates: dict[str, str],
    slugs: set[str],
    report: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        html = fetch(session, url)
    except Exception as exc:
        report["falhas"].append({"url": url, "motivo": f"fetch failed: {exc}"})
        return None

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        meta_title = soup.find("meta", property="og:title")
        title = meta_title.get("content", "").strip() if meta_title else slug

    meta_date = soup.find("meta", property="article:published_time")
    date_iso = None
    if meta_date and meta_date.get("content"):
        date_iso = parse_date_text(meta_date["content"])
    if not date_iso:
        date_iso = index_dates.get(slug)
    if not date_iso:
        date_iso = datetime.utcnow().date().isoformat()

    date_human = date_human_ptbr(date_iso)

    category = "Blog"
    meta_section = soup.find("meta", property="article:section")
    if meta_section and meta_section.get("content"):
        category = meta_section["content"].strip() or category

    og_image = soup.find("meta", property="og:image")
    cover_url = og_image.get("content") if og_image else None

    post_div = soup.find("div", attrs={"data-elementor-type": "wp-post"}) or soup.find("article")
    body_html = extract_body_html(post_div)
    if not body_html:
        report["falhas"].append({"url": url, "motivo": "conteudo vazio"})
        return None

    clean_html = clean_content_html(session, body_html, slug, slugs, report)

    body_text = BeautifulSoup(clean_html, "html.parser").get_text(" ", strip=True)
    meta_desc = soup.find("meta", attrs={"name": "description"})
    excerpt = meta_desc.get("content", "").strip() if meta_desc else ""
    if not excerpt:
        excerpt = make_excerpt(body_text)

    cover_path = download_image(session, cover_url, slug, report) if cover_url else None
    if not cover_path:
        first_img = BeautifulSoup(clean_html, "html.parser").find("img")
        if first_img and first_img.get("src"):
            cover_path = first_img.get("src")

    return {
        "slug": slug,
        "title": title,
        "dateISO": date_iso,
        "dateHumanPTBR": date_human,
        "category": category,
        "excerpt": excerpt,
        "coverImagePath": cover_path or "",
        "contentHtml": clean_html,
        "sourceUrl": url,
    }


def render_search_controls(categories: list[str]) -> str:
    options = ['<option value="all">Todas as categorias</option>']
    for category in categories:
        options.append(f'<option value="{category.lower()}">{category}</option>')
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
<p id="blog-results" class="text-sm text-slate-500 mb-8"></p>
""".strip()


def render_cards(posts: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for idx, post in enumerate(posts):
        delay = idx * 100
        category = post.get("category") or "Blog"
        data_search = f"{post['title']} {post['excerpt']} {category}".lower()
        image_html = ""
        if post.get("coverImagePath"):
            image_html = (
                f'<img src="{post["coverImagePath"]}" alt="{post["title"]}" '
                'class="w-full h-48 object-cover" decoding="async" loading="lazy"/>'
            )
        else:
            image_html = '<div class="w-full h-48 bg-gradient-to-r from-slate-200 via-slate-100 to-slate-200"></div>'

        cards.append(
            f"""
<a href="#post-{post['slug']}" class="post-card block bg-white rounded-lg shadow-md overflow-hidden transition hover:shadow-xl animated-item fade-in" style="transition-delay: {delay}ms;" data-post-card data-category="{category.lower()}" data-search="{data_search}">
  {image_html}
  <div class="p-6">
    <p class="text-sm text-slate-500">{category} • {post['dateHumanPTBR']}</p>
    <h3 class="mt-2 text-xl font-bold text-slate-900">{post['title']}</h3>
    <p class="mt-2 text-slate-600">{post['excerpt']}</p>
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


def render_details(posts: list[dict[str, Any]], site_url: str) -> str:
    details: list[str] = []
    total = len(posts)
    for idx, post in enumerate(posts):
        prev_slug = posts[idx - 1]["slug"] if idx > 0 else ""
        next_slug = posts[idx + 1]["slug"] if idx < total - 1 else ""
        nav_links = []
        if prev_slug:
            nav_links.append(f'<a href="#post-{prev_slug}" class="text-sm font-semibold text-[--brand-blue] hover:underline">Anterior</a>')
        if next_slug:
            nav_links.append(f'<a href="#post-{next_slug}" class="text-sm font-semibold text-[--brand-blue] hover:underline">Proximo</a>')
        nav_html = " ".join(nav_links) if nav_links else ""

        cover_html = ""
        if post.get("coverImagePath"):
            cover_html = (
                f'<img src="{post["coverImagePath"]}" alt="{post["title"]}" '
                'class="w-full h-auto rounded-xl shadow-lg my-8" decoding="async" loading="lazy"/>'
            )

        details.append(
            f"""
<article id="post-{post['slug']}" class="post-detail bg-white rounded-2xl shadow-lg p-8 md:p-10 animated-item fade-in">
  <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
    <div>
      <p class="text-sm text-slate-500">{post['category']} • {post['dateHumanPTBR']}</p>
      <h2 class="text-2xl md:text-3xl font-bold text-slate-900 mt-2">{post['title']}</h2>
      <p class="text-slate-600 mt-3">{post['excerpt']}</p>
    </div>
    <a href="contato.html" class="inline-flex items-center justify-center bg-[--brand-blue] text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:scale-105 transition-transform duration-300">Contato</a>
  </div>
  {cover_html}
  <div class="prose max-w-none text-slate-600">
    {post['contentHtml']}
  </div>
  <div class="mt-8 flex flex-col sm:flex-row justify-between gap-4">
    <a href="#blog-list" class="text-sm font-semibold text-[--brand-blue] hover:underline">Voltar para o topo</a>
    <div class="flex gap-4">
      {nav_html}
    </div>
  </div>
  <script type="application/ld+json">{render_post_jsonld(post, site_url)}</script>
</article>
""".strip()
        )
    return "\n".join(details)


def get_site_url() -> str:
    if not BLOG_HTML_PATH.exists():
        return "https://hbtmarc.github.io/fcge"
    soup = BeautifulSoup(BLOG_HTML_PATH.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        href = canonical["href"].rstrip("/")
        if href.endswith("/blog.html"):
            return href[: -len("/blog.html")]
    return "https://hbtmarc.github.io/fcge"


def update_blog_html(posts: list[dict[str, Any]]) -> None:
    html = BLOG_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    modal = soup.find(id="article-modal")
    if modal:
        modal.decompose()

    script_data = soup.find("script", id="posts-data")
    if script_data:
        script_data.decompose()

    for script in soup.find_all("script"):
        if script.get("id") == "blog-interactions":
            script.decompose()
            continue
        if script.get("src"):
            continue
        if "loadPosts" in script.get_text():
            script.decompose()

    list_section = soup.find("section", class_=lambda c: c and "py-20" in c and soup.find(id="posts-container"))
    if list_section:
        list_section["id"] = "blog-list"
        container = list_section.find("div", class_=lambda c: c and "container" in c)
        grid = list_section.find(id="posts-container")
        if container and grid:
            filters = container.find(id="blog-filters")
            if filters:
                filters.decompose()
            results_line = container.find(id="blog-results")
            if results_line:
                results_line.decompose()
            filters_html = render_search_controls(sorted({p["category"] for p in posts if p.get("category")}))
            filters_fragment = BeautifulSoup(filters_html, "html.parser")
            container.insert(0, filters_fragment)

            grid.clear()
            cards_html = render_cards(posts)
            cards_fragment = BeautifulSoup(cards_html, "html.parser")
            for child in list(cards_fragment.contents):
                grid.append(child)

            results_fragment = BeautifulSoup('<p id="blog-results" class="text-sm text-slate-500 mb-8"></p>', "html.parser")
            container.insert(2, results_fragment)

    details_section = soup.find("section", id="blog-details")
    site_url = get_site_url()
    details_html = f"""
<section id="blog-details" class="py-20 sm:py-28 bg-slate-50 hidden">
  <div class="container mx-auto px-6">
    <div class="text-center mb-12 animated-item fade-in">
      <span class="font-bold text-[--brand-blue]">DETALHES</span>
      <h2 class="text-3xl md:text-4xl font-bold text-slate-900 mt-2">Conteudo completo</h2>
      <p class="mt-4 text-lg text-slate-600 max-w-3xl mx-auto">Explore os artigos completos e aprofunde nos temas do blog.</p>
    </div>
    <div class="space-y-12">
      {render_details(posts, site_url)}
    </div>
  </div>
</section>
""".strip()
    details_fragment = BeautifulSoup(details_html, "html.parser")
    if details_section:
        details_section.replace_with(details_fragment)
    elif list_section:
        list_section.insert_after(details_fragment)

    back_button = soup.find(id="blog-back-to-top")
    if back_button:
        back_button.decompose()
    back_html = """
<section class="py-12">
  <div class="container mx-auto px-6 text-center">
    <a href="#blog-list" id="blog-back-to-top" class="inline-flex items-center justify-center text-white font-bold py-3 px-8 rounded-lg cta-button cta-button-standard hidden">Voltar ao topo</a>
  </div>
</section>
""".strip()
    back_fragment = BeautifulSoup(back_html, "html.parser")
    if soup.main:
        soup.main.append(back_fragment)

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

  if(mobileMenuButton) mobileMenuButton.addEventListener('click', openMenu);
  if(closeMobileMenuButton) closeMobileMenuButton.addEventListener('click', closeMenu);

  const searchInput = document.getElementById('blog-search');
  const categorySelect = document.getElementById('blog-category');
  const cards = Array.from(document.querySelectorAll('[data-post-card]'));
  const results = document.getElementById('blog-results');

  const normalize = (value) => (value || '')
    .toString()
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '');

  const applyFilters = () => {
    const query = normalize(searchInput ? searchInput.value : '');
    const category = categorySelect ? categorySelect.value : 'all';
    let visible = 0;

    cards.forEach(card => {
      const text = normalize(card.getAttribute('data-search'));
      const cardCategory = card.getAttribute('data-category') || '';
      const matchesQuery = !query || text.includes(query);
      const matchesCategory = category === 'all' || cardCategory === category;
      const show = matchesQuery && matchesCategory;
      card.classList.toggle('hidden', !show);
      if (show) visible += 1;
    });

    if (results) {
      results.textContent = visible ? `${visible} artigo(s) encontrados` : 'Nenhum artigo encontrado.';
    }
  };

  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (categorySelect) categorySelect.addEventListener('change', applyFilters);
  applyFilters();

  const detailSection = document.getElementById('blog-details');
  if (!detailSection) return;
  const detailItems = Array.from(detailSection.querySelectorAll('.post-detail'));
  const backToTop = document.getElementById('blog-back-to-top');
  const header = document.getElementById('header') || document.querySelector('header');
  if (!detailItems.length) return;

  const hideSection = () => detailSection.classList.add('hidden');
  const showSection = () => detailSection.classList.remove('hidden');
  const showOnly = (id) => detailItems.forEach(item => item.classList.toggle('hidden', item.id !== id));
  const scrollToElement = (element) => {
    const headerOffset = header ? header.offsetHeight + 16 : 80;
    const top = element.getBoundingClientRect().top + window.pageYOffset - headerOffset;
    window.scrollTo({ top, behavior: 'smooth' });
  };

  const handleHash = () => {
    const hash = (location.hash || '').replace('#', '');
    const match = detailItems.find(item => item.id === hash);
    if (match) {
      showSection();
      showOnly(hash);
      if (backToTop) backToTop.classList.remove('hidden');
      requestAnimationFrame(() => {
        requestAnimationFrame(() => scrollToElement(match));
      });
    } else {
      hideSection();
      detailItems.forEach(item => item.classList.add('hidden'));
      if (backToTop) backToTop.classList.add('hidden');
    }
  };

  handleHash();
  window.addEventListener('hashchange', handleHash);
});
""".strip()
    script_tag = soup.new_tag("script", id="blog-interactions")
    script_tag.string = script_text
    if soup.body:
        soup.body.append(script_tag)

    BLOG_HTML_PATH.write_text(soup.decode(), encoding="utf-8")


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


def main() -> None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.headers.update(HEADERS)

    report = {
        "totalPostsEncontrados": 0,
        "totalRenderizadosNoHTML": 0,
        "imagensBaixadas": 0,
        "linksInternosConvertidos": 0,
        "falhas": [],
    }

    post_urls, index_dates = discover_post_urls(session)
    report["totalPostsEncontrados"] = len(post_urls)
    slugs = {slug_from_url(url) for url in post_urls}
    posts: list[dict[str, Any]] = []

    for url in post_urls:
        slug = slug_from_url(url)
        if not slug:
            continue
        post = extract_post_data(session, url, slug, index_dates, slugs, report)
        if post:
            posts.append(post)

    posts.sort(key=lambda item: item.get("dateISO", ""), reverse=True)
    report["totalRenderizadosNoHTML"] = len(posts)

    POSTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTS_JSON_PATH.write_text(json.dumps(posts, indent=2, ensure_ascii=False), encoding="utf-8")

    update_blog_html(posts)
    update_sitemap()

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
