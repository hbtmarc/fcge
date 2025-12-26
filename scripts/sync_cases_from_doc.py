#!/usr/bin/env python3
"""Sync cases content from an attached document into HTML pages and JSON."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
ASSETS_DIR = ROOT_DIR / "assets" / "cases"
REPORT_PATH = ROOT_DIR / "cases-migration-report.json"
CASES_JSON_PATH = DATA_DIR / "cases.json"
CASES_HTML_PATH = ROOT_DIR / "cases.html"

SEARCH_DIRS = [ROOT_DIR, ROOT_DIR / "docs", ROOT_DIR / "assets", ROOT_DIR / "content"]
EXTENSIONS = {".pdf", ".docx", ".md"}
NAME_HINTS = ("case", "cases", "portfolio", "portfólio", "projetos", "projeto")
SINGLE_PAGE_MODE = True


@dataclass
class CaseItem:
    slug: str
    client: str
    segment: str
    title: str
    excerpt: str
    bullets: list[str]
    detail_sections: list[dict[str, str]]
    cover_image: str
    gallery_images: list[str]
    results: list[str]
    source_refs: list[str]
    scope: str
    deliverables: list[str]


def strip_accents(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn"
    )


def slugify(text: str) -> str:
    text = strip_accents(text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "case"


def find_source_doc() -> Path | None:
    candidates: list[Path] = []
    for base in SEARCH_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in EXTENSIONS:
                continue
            candidates.append(path)

    if not candidates:
        return None

    def score(path: Path) -> tuple[int, float]:
        name = strip_accents(path.name.lower())
        hint = 1 if any(h in name for h in NAME_HINTS) else 0
        return (hint, path.stat().st_mtime)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def extract_text_from_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines()]
    merged: list[str] = []
    for line in lines:
        if not line:
            if merged and merged[-1] != "":
                merged.append("")
            continue
        if merged and merged[-1] != "":
            prev = merged[-1]
            merged[-1] = prev + " " + line
        else:
            merged.append(line)
    cleaned = []
    for line in merged:
        if line == "":
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)

    fixes = {
        "ident ificação": "identificação",
        "fornecer am": "forneceram",
        "dado s": "dados",
        "ge ração": "geração",
        "me teorológicas": "meteorológicas",
        "ope ração": "operação",
        "esp acial": "espacial",
        "poluentes A modelagem": "poluentes. A modelagem",
    }
    for bad, good in fixes.items():
        text = text.replace(bad, good)
    text = re.sub(r"\bd\s+o\b", "do", text)
    text = re.sub(r"\bd\s+a\b", "da", text)
    text = re.sub(r"\bd\s+os\b", "dos", text)
    text = re.sub(r"\bd\s+as\b", "das", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def infer_segment(title: str, context: str) -> str:
    text = strip_accents(f"{title} {context}".lower())
    if "energia solar" in text or "fotovoltaic" in text:
        return "Energia Solar"
    if "trafego" in text or "vias urbanas" in text or "veiculos" in text:
        return "Mobilidade Urbana"
    if "termel" in text:
        return "Energia"
    if "producao de cal" in text:
        return "Industria de Cal"
    return ""


def parse_cases_from_text(text: str, source_ref: str) -> list[CaseItem]:
    normalized = normalize_text(text)
    normalized = re.sub(r"^Cases de sucesso.*?Case:\s*", "Case: ", normalized, flags=re.I | re.S)
    blocks = re.split(r"\bCase:\s*", normalized)
    cases: list[CaseItem] = []
    used_slugs: set[str] = set()

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if "Contexto:" not in block:
            continue

        title = block.split("Contexto:")[0].strip()
        if not title:
            continue

        context = ""
        methodology = ""
        results = ""

        context_match = re.search(r"Contexto:\s*(.*?)(?=Metodologia aplicada:|Resultados:?|$)", block, re.S)
        if context_match:
            context = context_match.group(1).strip()
        method_match = re.search(r"Metodologia aplicada:\s*(.*?)(?=Resultados:?|$)", block, re.S)
        if method_match:
            methodology = method_match.group(1).strip()
        results_match = re.search(r"Resultados:?\s*(.*)$", block, re.S)
        if results_match:
            results = results_match.group(1).strip()

        context = " ".join(context.split())
        methodology = " ".join(methodology.split())
        results = " ".join(results.split())

        excerpt = ""
        context_sentences = split_sentences(context)
        if context_sentences:
            excerpt = context_sentences[0]

        bullets: list[str] = []
        method_sentences = split_sentences(methodology)
        results_sentences = split_sentences(results)
        if method_sentences:
            bullets.append(method_sentences[0])
        if results_sentences:
            bullets.append(results_sentences[0])
        while len(bullets) < 2:
            bullets.append("Saiba mais")
        bullets = bullets[:2]

        slug = slugify(title)
        base_slug = slug
        counter = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1
        used_slugs.add(slug)

        segment = infer_segment(title, context)
        case_item = CaseItem(
            slug=slug,
            client="",
            segment=segment,
            title=title,
            excerpt=excerpt,
            bullets=bullets,
            detail_sections=[
                {"title": "Descrição completa", "content": context},
                {"title": "Metodologia aplicada", "content": methodology},
                {"title": "Resultados", "content": results},
            ],
            cover_image="",
            gallery_images=[],
            results=results_sentences[:4],
            source_refs=[source_ref],
            scope="",
            deliverables=[],
        )
        cases.append(case_item)

    return cases


def build_cases_json(cases: list[CaseItem], kpis: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kpis": kpis,
        "cases": [
            {
                "slug": case.slug,
                "client": case.client,
                "segment": case.segment,
                "title": case.title,
                "excerpt": case.excerpt,
                "bullets": case.bullets,
                "detailSections": case.detail_sections,
                "coverImage": case.cover_image,
                "galleryImages": case.gallery_images,
                "results": case.results,
                "sourceRefs": case.source_refs,
                "scope": case.scope,
                "deliverables": case.deliverables,
            }
            for case in cases
        ],
    }


def render_case_cards(cases: list[CaseItem]) -> str:
    cards = []
    for idx, case in enumerate(cases):
        delay = idx * 100
        card_href = f"#case-{case.slug}" if SINGLE_PAGE_MODE else f"case-{case.slug}.html"
        image_html = ""
        if case.cover_image:
            image_html = (
                f'<img src="{case.cover_image}" alt="{case.title}" '
                'class="w-full h-48 object-cover" decoding="async" loading="lazy"/>'
            )
        else:
            image_html = (
                '<div class="w-full h-48 bg-gradient-to-r from-slate-200 via-slate-100 to-slate-200"></div>'
            )

        segment_html = (
            f'<span class="inline-block px-3 py-1 text-xs font-semibold bg-blue-100 text-[--brand-blue] rounded-full">{case.segment}</span>'
            if case.segment
            else ""
        )
        client_html = (
            f'<span class="text-sm font-bold text-slate-700">{case.client}</span>' if case.client else ""
        )
        card = f"""
<a href="{card_href}" class="block" aria-label="Ver detalhes de {case.title}">
  <div class="bg-white rounded-xl shadow-lg overflow-hidden case-card animated-item fade-in" style="transition-delay: {delay}ms;">
    {image_html}
    <div class="p-6">
      <div class="flex items-center gap-3 mb-3">
        {segment_html}
        {client_html}
      </div>
      <h3 class="text-xl font-bold text-slate-900 mb-2">{case.title}</h3>
      <p class="text-slate-600 mb-4">{case.excerpt}</p>
      <ul class="space-y-2 text-sm text-slate-600">
        <li class="flex items-start">
          <svg class="w-5 h-5 text-[--brand-green] mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"></path>
          </svg>
          <span>{case.bullets[0]}</span>
        </li>
        <li class="flex items-start">
          <svg class="w-5 h-5 text-[--brand-green] mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" clip-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"></path>
          </svg>
          <span>{case.bullets[1]}</span>
        </li>
      </ul>
    </div>
  </div>
</a>
""".strip()
        cards.append(card)
    return "\n".join(cards)


def render_case_details(cases: list[CaseItem]) -> str:
    items = []
    for idx, case in enumerate(cases):
        delay = idx * 100
        client_segment = " • ".join(part for part in [case.client, case.segment] if part)
        cover_html = ""
        if case.cover_image:
            cover_html = (
                f'<img src="{case.cover_image}" alt="{case.title}" '
                'class="w-full h-auto rounded-xl shadow-lg my-6" decoding="async" loading="lazy"/>'
            )

        sections_html = []
        for section in case.detail_sections:
            content = section.get("content", "")
            paragraphs = paragraphs_from_text(content)
            if not paragraphs:
                continue
            body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
            sections_html.append(
                f"""
<div>
  <h4 class="text-xl font-bold text-slate-900 mb-3">{section.get("title")}</h4>
  <div class="prose max-w-none text-slate-600">{body}</div>
</div>
""".strip()
            )

        results_html = ""
        if case.results:
            items_html = "\n".join(f"<li>{item}</li>" for item in case.results)
            results_html = f"""
<div>
  <h4 class="text-xl font-bold text-slate-900 mb-3">Resultados e indicadores</h4>
  <ul class="list-disc pl-6 text-slate-600">{items_html}</ul>
</div>
""".strip()

        detail_blocks = "\n".join(sections_html)
        if results_html:
            detail_blocks = f"{detail_blocks}\n{results_html}"

        items.append(
            f"""
<article id="case-{case.slug}" class="case-detail bg-white rounded-2xl shadow-lg p-8 md:p-10 animated-item fade-in" style="transition-delay: {delay}ms;">
  <div class="flex items-center justify-between mb-4">
    <a href="#case-list" data-case-back class="text-sm font-semibold text-[--brand-blue] hover:underline">Voltar aos cases</a>
  </div>
  <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
    <div>
      <p class="text-xs uppercase tracking-widest text-slate-500">{client_segment}</p>
      <h3 class="text-2xl md:text-3xl font-bold text-slate-900 mt-2">{case.title}</h3>
      <p class="text-slate-600 mt-3">{case.excerpt}</p>
    </div>
    <a href="contato.html" class="inline-flex items-center justify-center bg-[--brand-blue] text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:scale-105 transition-transform duration-300">Contato</a>
  </div>
  {cover_html}
  <div class="mt-6 space-y-6">
    {detail_blocks}
  </div>
</article>
""".strip()
        )

    return "\n".join(items)


def update_cases_html(cases: list[CaseItem]) -> None:
    html = CASES_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.find("h2", string=lambda s: s and "Estudos Realizados" in s)
    if heading:
        section = heading.find_parent("section")
        if section:
            section["id"] = "case-list"
        grid = section.find("div", class_=lambda c: c and "grid" in c and "md:grid-cols-2" in c)
        if grid:
            grid.clear()
            cards_html = render_case_cards(cases)
            cards_fragment = BeautifulSoup(cards_html, "html.parser")
            for child in list(cards_fragment.contents):
                grid.append(child)

        details_section = soup.find("section", id="case-details")
        details_html = f"""
<section id="case-details" class="py-20 sm:py-28 bg-slate-50 hidden">
  <div class="container mx-auto px-6">
    <div class="text-center mb-12 animated-item fade-in">
      <span class="font-bold text-[--brand-blue]">DETALHES</span>
      <h2 class="text-3xl md:text-4xl font-bold text-slate-900 mt-2">Detalhes dos Cases</h2>
      <p class="mt-4 text-lg text-slate-600 max-w-3xl mx-auto">Confira o escopo, metodologia e resultados de cada projeto.</p>
    </div>
    <div class="space-y-10">
      {render_case_details(cases)}
    </div>
  </div>
</section>
""".strip()
        details_fragment = BeautifulSoup(details_html, "html.parser")
        if details_section:
            details_section.replace_with(details_fragment)
        else:
            section.insert_after(details_fragment)

    CASES_HTML_PATH.write_text(soup.decode(), encoding="utf-8")


def paragraphs_from_text(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"\n{2,}", text)
    return [part.strip() for part in parts if part.strip()]


def build_case_page_html(
    case: CaseItem,
    site_url: str,
    header_html: str,
    footer_html: str,
    assets_html: str,
    html_class: str,
) -> str:
    canonical_url = f"{site_url}/case-{case.slug}.html"
    description = case.excerpt or case.title
    og_image = case.cover_image
    twitter_card = "summary_large_image" if og_image else "summary"

    sections_html = []
    for section in case.detail_sections:
        content = section.get("content", "")
        paragraphs = paragraphs_from_text(content)
        if not paragraphs:
            continue
        body = "\n".join(f"<p>{p}</p>" for p in paragraphs)
        sections_html.append(
            f"""
<section class="py-10">
  <h2 class="text-2xl font-bold text-slate-900 mb-4">{section.get("title")}</h2>
  <div class="prose max-w-none text-slate-600">{body}</div>
</section>
""".strip()
        )

    results_html = ""
    if case.results:
        items = "\n".join(f"<li>{item}</li>" for item in case.results)
        results_html = f"""
<section class="py-10">
  <h2 class="text-2xl font-bold text-slate-900 mb-4">Resultados e indicadores</h2>
  <ul class="list-disc pl-6 text-slate-600">{items}</ul>
</section>
""".strip()

    cover_html = ""
    if case.cover_image:
        cover_html = (
            f'<img src="{case.cover_image}" alt="{case.title}" '
            'class="w-full h-auto rounded-xl shadow-lg my-8" decoding="async" loading="lazy"/>'
        )

    client_segment = " ".join(part for part in [case.client, case.segment] if part)

    sections_html_output = "\n".join(sections_html)
    if results_html:
        sections_html_output = f"{sections_html_output}\n{results_html}"

    return f"""<!DOCTYPE html>
<html class="{html_class}" lang="pt-BR">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1" name="viewport"/>
<title>{case.title} | FC Gestão Estratégica</title>
<meta content="{description}" name="description"/>
<link href="{canonical_url}" rel="canonical"/>
<meta content="{case.title} | FC Gestão Estratégica" property="og:title"/>
<meta content="{description}" property="og:description"/>
<meta content="{canonical_url}" property="og:url"/>
<meta content="article" property="og:type"/>
{f'<meta content="{site_url}/{og_image.lstrip("/")}" property="og:image"/>' if og_image else ''}
<meta content="{twitter_card}" name="twitter:card"/>
<meta content="{case.title} | FC Gestão Estratégica" name="twitter:title"/>
<meta content="{description}" name="twitter:description"/>
{f'<meta content="{site_url}/{og_image.lstrip("/")}" name="twitter:image"/>' if og_image else ''}
{assets_html}
</head>
<body class="bg-slate-50 text-slate-700">
{header_html}
<main>
  <section class="relative page-header text-center py-20 sm:py-24" style="background-image: url('https://images.unsplash.com/photo-1552664730-d307ca884978?q=80&amp;w=2070&amp;auto=format&amp;fit=crop');">
    <div class="absolute inset-0 bg-slate-900/60 z-0"></div>
    <div class="relative z-10 container mx-auto px-6">
      <p class="text-sm text-slate-200 tracking-wide uppercase">{client_segment}</p>
      <h1 class="text-3xl md:text-5xl font-black tracking-tighter text-white mt-3">{case.title}</h1>
      <p class="mt-4 text-lg text-slate-200 max-w-3xl mx-auto">{description}</p>
    </div>
  </section>

  <section class="py-16 sm:py-20">
    <div class="container mx-auto px-6 max-w-4xl">
      {cover_html}
      {sections_html_output}
    </div>
  </section>

  <section class="py-16 sm:py-20">
    <div class="container mx-auto px-6">
      <div class="bg-gradient-to-r from-[--brand-blue] to-[--brand-green] rounded-2xl p-8 text-white text-center">
        <h2 class="text-2xl md:text-3xl font-bold mb-4">Leve nossas soluções para o seu projeto</h2>
        <p class="text-lg mb-6 max-w-2xl mx-auto">Entre em contato e descubra como podemos ajudar sua organização com soluções ambientais especializadas.</p>
        <a href="contato.html" class="inline-block bg-white text-[--brand-blue] font-bold py-3 px-8 rounded-lg hover:scale-105 transition-transform duration-300 shadow-lg">Fale Conosco</a>
      </div>
    </div>
  </section>
</main>
{footer_html}
<script>
  document.addEventListener("DOMContentLoaded", () => {{
    const mobileMenuButton = document.getElementById('mobile-menu-button');
    const closeMobileMenuButton = document.getElementById('close-mobile-menu');
    const mobileMenu = document.getElementById('mobile-menu');
    const openMenu = () => mobileMenu && mobileMenu.classList.remove('-translate-x-full');
    const closeMenu = () => mobileMenu && mobileMenu.classList.add('-translate-x-full');
    if (mobileMenuButton) mobileMenuButton.addEventListener('click', openMenu);
    if (closeMobileMenuButton) closeMobileMenuButton.addEventListener('click', closeMenu);
  }});
</script>
</body>
</html>
"""


def get_site_url_from_cases() -> str:
    html = CASES_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        href = canonical["href"].rstrip("/")
        if href.endswith("/cases.html"):
            return href[: -len("/cases.html")]
    return "https://hbtmarc.github.io/fcge"


def extract_template_assets() -> tuple[str, str, str, str]:
    html = CASES_HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    header = soup.find("header")
    footer = soup.find("footer")
    assets = []
    for tag in soup.head.find_all(["script", "link", "style"], recursive=False):
        if tag.name == "script" and tag.get("id") == "structured-data":
            assets.append(str(tag))
            continue
        if tag.name == "script" and tag.get("src") == "https://cdn.tailwindcss.com":
            assets.append(str(tag))
            continue
        if tag.name == "style":
            assets.append(str(tag))
            continue
        if tag.name == "link":
            rel = tag.get("rel") or []
            rel = [item.lower() for item in rel]
            if "canonical" in rel:
                continue
            if any(item in rel for item in ["stylesheet", "preconnect", "icon", "apple-touch-icon", "manifest"]):
                assets.append(str(tag))
    html_class = " ".join(soup.html.get("class", [])) if soup.html else ""
    return (str(header), str(footer), "\n".join(assets), html_class)


def write_case_pages(cases: list[CaseItem], site_url: str) -> list[str]:
    header_html, footer_html, assets_html, html_class = extract_template_assets()
    pages = []
    for case in cases:
        html = build_case_page_html(case, site_url, header_html, footer_html, assets_html, html_class)
        filename = f"case-{case.slug}.html"
        (ROOT_DIR / filename).write_text(html, encoding="utf-8")
        pages.append(filename)
    return pages


def build_report(cases: list[CaseItem], pages: list[str], kpis: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields: dict[str, list[str]] = {}
    for case in cases:
        missing = []
        if not case.client:
            missing.append("client")
        if not case.segment:
            missing.append("segment")
        if not case.cover_image:
            missing.append("coverImage")
        if not case.gallery_images:
            missing.append("galleryImages")
        if not case.scope:
            missing.append("scope")
        if not case.deliverables:
            missing.append("deliverables")
        if not case.results:
            missing.append("results")
        if missing:
            missing_fields[case.slug] = missing

    avisos = []
    if not kpis:
        avisos.append("KPIs nao encontrados no documento.")
    if not any(case.cover_image for case in cases):
        avisos.append("Nenhuma imagem encontrada no documento.")
    if SINGLE_PAGE_MODE:
        avisos.append("Detalhes dos cases inseridos em cases.html (modo pagina unica).")

    return {
        "totalCasesNoDocumento": len(cases),
        "totalCasesGerados": len(cases),
        "paginasCriadas": pages,
        "imagensCopiadas": [],
        "camposAusentes": missing_fields,
        "avisos": avisos,
    }


def main() -> None:
    source_doc = find_source_doc()
    if not source_doc:
        raise SystemExit("Documento de cases nao encontrado.")

    text = ""
    if source_doc.suffix.lower() == ".pdf":
        text = extract_text_from_pdf(source_doc)
    else:
        text = source_doc.read_text(encoding="utf-8", errors="ignore")

    cases = parse_cases_from_text(text, source_doc.as_posix())
    kpis: list[dict[str, Any]] = []

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cases_payload = build_cases_json(cases, kpis)
    CASES_JSON_PATH.write_text(json.dumps(cases_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    update_cases_html(cases)

    site_url = get_site_url_from_cases()
    pages: list[str] = []
    if not SINGLE_PAGE_MODE:
        pages = write_case_pages(cases, site_url)

    report = build_report(cases, pages, kpis)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
