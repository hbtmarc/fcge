#!/usr/bin/env python3
import html
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup

BASE_URL = "https://www.fcgestaoestrategica.com.br"
BLOG_START = f"{BASE_URL}/blog/"

ROOT_DIR = Path(__file__).resolve().parents[1]
IMAGES_DIR = ROOT_DIR / "imagens" / "blog"
DATA_DIR = ROOT_DIR / "data"
BLOG_HTML_PATH = ROOT_DIR / "blog.html"
SITEMAP_PATH = ROOT_DIR / "sitemap.xml"
REPORT_PATH = ROOT_DIR / "migration-report.json"

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

MONTHS_PT_NAME = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def slug_from_url(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return None
    slug = path.split("/")[-1]
    if slug in {"blog", "contato", "servicos", "quem-somos", "sobre", "cases"}:
        return None
    return slug


def format_date_ptbr(date_obj: datetime) -> str:
    month_name = MONTHS_PT_NAME.get(date_obj.month, "")
    return f"{date_obj.day} de {month_name} de {date_obj.year}"


def parse_date_ptbr(text: str) -> datetime | None:
    if not text:
        return None
    match = re.search(r"(\d{1,2})\s+de\s+([A-Za-zÀ-ÿ]+)\s+de\s+(\d{4})", text)
    if not match:
        return None
    day = int(match.group(1))
    month_name = match.group(2).strip().lower()
    month = MONTHS_PT.get(month_name)
    if not month:
        return None
    year = int(match.group(3))
    return datetime(year, month, day)


def fetch(session: requests.Session, url: str, *, timeout: int = 30, retries: int = 3) -> requests.Response:
    backoff = 1
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout, verify=False)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} para {url}")
            return resp
        except Exception as err:
            last_err = err
            if attempt == retries:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise last_err


def safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = name.replace(" ", "-")
    name = re.sub(r"-+", "-", name)
    return name or "imagem"


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


def download_image(session: requests.Session, url: str, slug: str, report: dict, cache: dict) -> str | None:
    if not url:
        return None
    if slug not in cache:
        cache[slug] = {}
    if url in cache[slug]:
        return cache[slug][url]

    parsed = urlparse(url)
    filename = Path(parsed.path).name
    filename = safe_filename(filename)

    dest_dir = IMAGES_DIR / slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not filename or "." not in filename:
        filename = f"imagem-{int(time.time())}.jpg"

    dest_path = dest_dir / filename
    counter = 1
    while dest_path.exists() and dest_path.stat().st_size > 0:
        stem = dest_path.stem
        suffix = dest_path.suffix
        dest_path = dest_dir / f"{stem}-{counter}{suffix}"
        counter += 1

    try:
        resp = fetch(session, url)
    except Exception:
        return None

    content = resp.content
    if not content:
        return None

    dest_path.write_bytes(content)
    report["imagensBaixadas"] += 1
    rel_path = dest_path.relative_to(ROOT_DIR).as_posix()
    cache[slug][url] = rel_path
    return rel_path


def collect_index_posts(session: requests.Session) -> dict:
    posts = {}
    queue = [BLOG_START]
    visited = set()

    while queue:
        page_url = queue.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)

        resp = fetch(session, page_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        for article in soup.find_all("article"):
            link = (
                article.select_one("a.elementor-post__thumbnail__link")
                or article.select_one("h3.elementor-post__title a")
                or article.find("a", href=True)
            )
            if not link:
                continue
            post_url = link.get("href")
            slug = slug_from_url(post_url)
            if not slug:
                continue

            title_el = article.select_one("h3.elementor-post__title")
            title = title_el.get_text(strip=True) if title_el else ""

            excerpt_el = article.select_one("div.elementor-post__excerpt") or article.select_one("p.excerpt")
            excerpt = excerpt_el.get_text(" ", strip=True) if excerpt_el else ""

            date_el = article.select_one("span.elementor-post-date")
            date_text = date_el.get_text(strip=True) if date_el else ""

            category_el = article.select_one("div.elementor-post__badge")
            category = category_el.get_text(strip=True) if category_el else "Blog"

            img_el = article.select_one("div.elementor-post__thumbnail img") or article.find("img")
            cover_url = pick_image_url(img_el) if img_el else ""

            existing = posts.get(slug, {})
            posts[slug] = {
                "url": post_url,
                "title": title or existing.get("title", ""),
                "excerpt": excerpt or existing.get("excerpt", ""),
                "dateText": date_text or existing.get("dateText", ""),
                "category": category or existing.get("category", "Blog"),
                "coverFromIndex": cover_url or existing.get("coverFromIndex", ""),
            }

        next_link = None
        for anchor in soup.select("a.page-numbers"):
            text = anchor.get_text(strip=True).lower()
            if "próxima" in text or "proxima" in text or "next" in text:
                next_link = anchor.get("href")
                break
        if next_link:
            queue.append(urljoin(page_url, next_link))

    return posts


def extract_main_wrap(post_div):
    wraps = post_div.select(".elementor-widget-wrap") if post_div else []
    if not wraps:
        return post_div
    return max(wraps, key=lambda w: len(w.get_text(" ", strip=True)))


def extract_body_html(post_div):
    main_wrap = extract_main_wrap(post_div)
    if not main_wrap:
        return ""

    widgets = [
        child
        for child in main_wrap.find_all("div", recursive=False)
        if "elementor-element" in (child.get("class") or [])
    ]

    if not widgets:
        return main_wrap.decode_contents()

    pieces = []
    for widget in widgets:
        widget_type = widget.get("data-widget_type", "")
        if "text-editor" in widget_type or "elementor-widget-text-editor" in (widget.get("class") or []):
            editor = widget.select_one(".elementor-text-editor")
            if editor:
                pieces.append(editor.decode_contents())
                continue
        if "image" in widget_type or "elementor-widget-image" in (widget.get("class") or []):
            img = widget.find("img")
            if img:
                pieces.append(str(img))
                continue
        container = widget.select_one(".elementor-widget-container")
        if container:
            pieces.append(container.decode_contents())
        else:
            pieces.append(widget.decode_contents())

    return "\n".join(pieces)


def rewrite_internal_links(body_soup: BeautifulSoup, slug_to_local: dict) -> int:
    rewrites = 0
    for anchor in body_soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue

        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            if parsed.netloc and "fcgestaoestrategica.com.br" not in parsed.netloc:
                continue
            slug = slug_from_url(href)
        elif href.startswith("/"):
            slug = slug_from_url(href)
        else:
            continue

        if slug and slug in slug_to_local:
            anchor["href"] = slug_to_local[slug]
            rewrites += 1
    return rewrites


def clean_image_attrs(img_tag):
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
        if attr in img_tag.attrs:
            del img_tag.attrs[attr]


def build_article_html(title: str, excerpt: str, category: str, date_human: str, cover_path: str | None, body_html: str, header_html: str, footer_html: str, style_css: str) -> str:
    safe_title = html.escape(title)
    safe_excerpt = html.escape(excerpt or "")

    og_image = f"<meta property=\"og:image\" content=\"{cover_path}\" />" if cover_path else ""
    cover_block = ""
    if cover_path:
        cover_block = f"""
                <figure class=\"my-8\">
                    <img src=\"{cover_path}\" alt=\"{safe_title}\" class=\"w-full h-auto rounded-xl shadow-lg\" loading=\"lazy\">
                </figure>
        """

    article_html = f"""<!DOCTYPE html>
<html lang=\"pt-BR\" class=\"scroll-smooth\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{safe_title} | FC Gestão Estratégica</title>
    <meta name=\"description\" content=\"{safe_excerpt}\">
    <meta property=\"og:title\" content=\"{safe_title}\" />
    <meta property=\"og:description\" content=\"{safe_excerpt}\" />
    {og_image}

    <script src=\"https://cdn.tailwindcss.com\"></script>
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
    <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap\" rel=\"stylesheet\">

    <style>
{style_css}
        .article-meta {{ color: #64748b; font-size: 0.95rem; }}
        .prose h2, .prose h3 {{ font-size: 1.5em; font-weight: 700; margin-top: 2em; margin-bottom: 1em; color: #1e293b; }}
        .prose p {{ margin-bottom: 1.25em; line-height: 1.7; color: #475569; }}
        .prose ul, .prose ol {{ margin: 1.5em 0; padding-left: 1.5rem; }}
        .prose li {{ margin-bottom: 0.5em; line-height: 1.7; color: #475569; }}
        .prose blockquote {{ border-left: 4px solid var(--brand-blue); padding-left: 1.5rem; margin: 2rem 0; font-style: italic; color: #475569; background: #f8fafc; padding: 1.5rem; border-radius: 0 8px 8px 0; }}
        .prose strong {{ color: var(--brand-blue); font-weight: 700; }}
        .prose a {{ color: var(--brand-blue); text-decoration: underline; }}
        .prose img {{ max-width: 100%; height: auto; border-radius: 0.75rem; margin: 1.5rem 0; box-shadow: 0 10px 25px rgba(15, 23, 42, 0.1); }}
        .prose table {{ width: 100%; border-collapse: collapse; margin: 2rem 0; }}
        .prose th, .prose td {{ border: 1px solid #e2e8f0; padding: 0.75rem; text-align: left; }}
        .prose th {{ background: #f1f5f9; color: #0f172a; }}
    </style>
</head>
<body class=\"bg-slate-50 text-slate-700\">

{header_html}

    <main>
        <section class=\"py-16 sm:py-20\">
            <div class=\"container mx-auto px-6 max-w-4xl\">
                <p class=\"article-meta\">{html.escape(category)} • {html.escape(date_human)}</p>
                <h1 class=\"mt-3 text-3xl md:text-4xl font-black tracking-tight text-slate-900\">{safe_title}</h1>
{cover_block}
                <article class=\"prose max-w-none\">
{body_html}
                </article>
            </div>
        </section>
    </main>

{footer_html}

    <script>
        document.addEventListener("DOMContentLoaded", () => {{
            const mobileMenuButton = document.getElementById('mobile-menu-button');
            const closeMobileMenuButton = document.getElementById('close-mobile-menu');
            const mobileMenu = document.getElementById('mobile-menu');

            const openMenu = () => mobileMenu.classList.remove('-translate-x-full');
            const closeMenu = () => mobileMenu.classList.add('-translate-x-full');

            if(mobileMenuButton) mobileMenuButton.addEventListener('click', openMenu);
            if(closeMobileMenuButton) closeMobileMenuButton.addEventListener('click', closeMenu);
        }});
    </script>
</body>
</html>
"""
    return article_html


def update_blog_html_script() -> None:
    if not BLOG_HTML_PATH.exists():
        return

    text = BLOG_HTML_PATH.read_text(encoding="utf-8")
    start = text.rfind("<script>")
    end = text.rfind("</script>")
    if start == -1 or end == -1:
        return

    new_script = """
    <script>
        async function loadPosts() {
            const container = document.getElementById('posts-container');
            if (!container) return;

            try {
                const response = await fetch('data/posts.json', { cache: 'no-store' });
                if (!response.ok) throw new Error(`Falha ao carregar posts (${response.status})`);
                const posts = await response.json();

                posts.sort((a, b) => new Date(b.dateISO) - new Date(a.dateISO));
                container.innerHTML = '';

                posts.forEach((post) => {
                    const card = document.createElement('a');
                    card.href = post.localUrl;
                    card.className = 'post-card bg-white rounded-lg shadow-md overflow-hidden transition hover:shadow-xl';

                    if (post.coverImagePath) {
                        const img = document.createElement('img');
                        img.src = post.coverImagePath;
                        img.alt = post.title;
                        img.className = 'w-full h-48 object-cover';
                        card.appendChild(img);
                    } else {
                        const placeholder = document.createElement('div');
                        placeholder.className = 'w-full h-48 bg-gradient-to-r from-slate-200 via-slate-100 to-slate-200';
                        card.appendChild(placeholder);
                    }

                    const body = document.createElement('div');
                    body.className = 'p-6';

                    const meta = document.createElement('p');
                    meta.className = 'text-sm text-slate-500';
                    meta.textContent = `${post.category} • ${post.dateHumanPTBR}`;

                    const title = document.createElement('h3');
                    title.className = 'mt-2 text-xl font-bold text-slate-900';
                    title.textContent = post.title;

                    const excerpt = document.createElement('p');
                    excerpt.className = 'mt-2 text-slate-600';
                    excerpt.textContent = post.excerpt;

                    body.appendChild(meta);
                    body.appendChild(title);
                    body.appendChild(excerpt);
                    card.appendChild(body);
                    container.appendChild(card);
                });
            } catch (err) {
                console.error(err);
                container.innerHTML = '<p class="text-center text-slate-500">Não foi possível carregar os artigos no momento.</p>';
            }
        }

        document.addEventListener("DOMContentLoaded", () => {
            loadPosts();

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

            const openMenu = () => mobileMenu.classList.remove('-translate-x-full');
            const closeMenu = () => mobileMenu.classList.add('-translate-x-full');

            if(mobileMenuButton) mobileMenuButton.addEventListener('click', openMenu);
            if(closeMobileMenuButton) closeMobileMenuButton.addEventListener('click', closeMenu);
        });
    </script>
""".strip("\n")

    updated = text[:start] + new_script + text[end + len("</script>") :]
    BLOG_HTML_PATH.write_text(updated, encoding="utf-8")


def update_sitemap(posts: list[dict]) -> None:
    if not SITEMAP_PATH.exists():
        return
    text = SITEMAP_PATH.read_text(encoding="utf-8")
    if "</urlset>" not in text:
        return

    existing_locs = set(re.findall(r"<loc>([^<]+)</loc>", text))
    entries = []

    for post in posts:
        loc = f"https://hbtmarc.github.io/fcge/{post['localUrl']}"
        if loc in existing_locs:
            continue
        date_iso = post.get("dateISO") or datetime.utcnow().strftime("%Y-%m-%d")
        lastmod = f"{date_iso}T00:00:00+00:00"
        entries.append(
            "\n".join(
                [
                    "<url>",
                    f"  <loc>{loc}</loc>",
                    f"  <lastmod>{lastmod}</lastmod>",
                    "  <changefreq>monthly</changefreq>",
                    "  <priority>0.60</priority>",
                    "</url>",
                ]
            )
        )

    if not entries:
        return

    insertion = "\n" + "\n".join(entries) + "\n"
    updated = text.replace("</urlset>", insertion + "</urlset>")
    SITEMAP_PATH.write_text(updated, encoding="utf-8")


def main():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.headers.update(HEADERS)

    report = {
        "totalPostsEncontrados": 0,
        "totalMigradosComSucesso": 0,
        "listaDeFalhas": [],
        "imagensBaixadas": 0,
        "linksInternosReescritos": 0,
    }

    index_posts = collect_index_posts(session)
    report["totalPostsEncontrados"] = len(index_posts)

    slug_to_local = {slug: f"artigo-{slug}.html" for slug in index_posts}

    blog_html = BLOG_HTML_PATH.read_text(encoding="utf-8") if BLOG_HTML_PATH.exists() else ""
    blog_soup = BeautifulSoup(blog_html, "html.parser") if blog_html else None
    header_html = str(blog_soup.find("header")) if blog_soup and blog_soup.find("header") else ""
    footer_html = str(blog_soup.find("footer")) if blog_soup and blog_soup.find("footer") else ""
    style_css = ""
    if blog_soup:
        style_tag = blog_soup.find("style")
        if style_tag:
            style_css = style_tag.get_text("\n")

    posts_output = []
    image_cache = {}

    for slug, data in index_posts.items():
        url = data.get("url")
        try:
            resp = fetch(session, url)
            soup = BeautifulSoup(resp.text, "html.parser")

            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else data.get("title", slug)

            post_div = soup.find("div", attrs={"data-elementor-type": "wp-post"}) or soup.find("article")
            body_html_raw = extract_body_html(post_div)
            body_soup = BeautifulSoup(body_html_raw, "html.parser")

            rewrites = rewrite_internal_links(body_soup, slug_to_local)
            report["linksInternosReescritos"] += rewrites

            # Images in body
            for img in body_soup.find_all("img"):
                img_url = pick_image_url(img)
                if not img_url:
                    continue
                local_path = download_image(session, img_url, slug, report, image_cache)
                if local_path:
                    img["src"] = local_path
                    clean_image_attrs(img)

            cover_url = ""
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                cover_url = og_image["content"]
            elif body_soup.find("img"):
                cover_url = pick_image_url(body_soup.find("img")) or ""

            cover_path = None
            if cover_url:
                cover_path = download_image(session, cover_url, slug, report, image_cache)

            excerpt = ""
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                excerpt = og_desc["content"]
            if not excerpt:
                excerpt = data.get("excerpt", "")
            if not excerpt:
                text = body_soup.get_text(" ", strip=True)
                excerpt = text[:180].rsplit(" ", 1)[0] + ("..." if len(text) > 180 else "")
            excerpt = html.unescape(excerpt)

            category = data.get("category") or "Blog"

            date_iso = ""
            date_human = ""
            published_meta = soup.find("meta", property="article:published_time")
            if published_meta and published_meta.get("content"):
                try:
                    dt = datetime.fromisoformat(published_meta["content"].replace("Z", "+00:00"))
                    date_iso = dt.strftime("%Y-%m-%d")
                    date_human = format_date_ptbr(dt)
                except ValueError:
                    pass
            if not date_iso:
                dt = parse_date_ptbr(data.get("dateText", ""))
                if dt:
                    date_iso = dt.strftime("%Y-%m-%d")
                    date_human = format_date_ptbr(dt)
            if not date_iso:
                date_iso = datetime.utcnow().strftime("%Y-%m-%d")
                date_human = format_date_ptbr(datetime.utcnow())

            body_html = body_soup.decode_contents()
            article_html = build_article_html(
                title=title,
                excerpt=excerpt,
                category=category,
                date_human=date_human,
                cover_path=cover_path,
                body_html=body_html,
                header_html=header_html,
                footer_html=footer_html,
                style_css=style_css,
            )

            article_path = ROOT_DIR / slug_to_local[slug]
            article_path.write_text(article_html, encoding="utf-8")

            posts_output.append(
                {
                    "slug": slug,
                    "title": title,
                    "dateISO": date_iso,
                    "dateHumanPTBR": date_human,
                    "category": category,
                    "excerpt": excerpt,
                    "coverImagePath": cover_path,
                    "sourceUrl": url,
                    "localUrl": slug_to_local[slug],
                }
            )

            report["totalMigradosComSucesso"] += 1
        except Exception as err:
            report["listaDeFalhas"].append({"url": url, "motivo": str(err)})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    posts_output.sort(key=lambda p: p.get("dateISO", ""), reverse=True)
    (DATA_DIR / "posts.json").write_text(
        json.dumps(posts_output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    update_blog_html_script()
    update_sitemap(posts_output)

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
