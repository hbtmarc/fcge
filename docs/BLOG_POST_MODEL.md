# Blog Post Model

This repository uses a single-page blog in `blog.html` backed by `data/posts.json`.
The reader template is standardized via the classes below and the content rules in this file.

## posts.json fields
- `slug`: URL-safe id (used in `#post-{slug}`).
- `title`: post title (used in gallery and reader).
- `dateISO`: ISO date string (`YYYY-MM-DD`).
- `dateHumanPTBR`: human date string (displayed in the reader).
- `category`: category label (default: `Blog`).
- `excerpt`: short summary for the card and reader header.
- `coverImagePath`: cover image path (rendered once at top of reader).
- `contentHtml`: body HTML (paragraphs, headings, lists, images).

## Reader template (single-page)
The reader section uses a consistent structure and classes:

```html
<article id="post-{slug}" data-post-article class="post-article post-reader ...">
  <div class="post-header ...">
    <div>
      <p>Category • Date</p>
      <h2>Title</h2>
      <p>Excerpt</p>
    </div>
    <a href="#blog" class="back-to-blog ...">Voltar ao Blog</a>
  </div>
  <img src="{coverImagePath}" class="post-cover ..." alt="Title">
  <div class="post-content ...">
    {contentHtml}
  </div>
  <a href="#blog" class="back-to-blog ...">Voltar ao Blog</a>
</article>
```

## Cover rules (mandatory)
- `coverImagePath` is rendered once at the top of the reader.
- Do not repeat the cover image inside `contentHtml`.
- Use local assets under `assets/blog/{slug}/`.

## Body content rules
- Use semantic HTML: `<p>`, `<h2>`, `<h3>`, `<h4>`, `<ul>`, `<ol>`, `<li>`.
- Do not use `<h1>` inside `contentHtml` (use `h2` or `h3` instead).
- Body images are `<img>` tags inside `contentHtml`. The normalizer will:
  - remove duplicate images (including cover duplicates),
  - wrap them in `<figure class="post-figure">`,
  - add `loading="lazy"` and `decoding="async"`.
- Avoid inline styles unless required by the original content.

## Adding a new post (recommended flow)
1) Add images under `assets/blog/{slug}/`.
2) Add the new entry to `data/posts.json`.
3) Ensure the cover image is only in `coverImagePath`, not in `contentHtml`.
4) Run `python scripts/normalize_posts_content.py`.
5) Update `blog.html` with the new post using the same reader template and classes.
