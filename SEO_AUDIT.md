# SEO Audit

## Site URL
- siteUrl: https://hbtmarc.github.io/fcge

## Estrutura alvo
- /: paginas HTML publicas (mantidas na raiz para nao quebrar URLs)
- imagens/: midia existente do site e blog
- data/: dados do blog (posts.json)
- assets/icons/: favicons e SVG
- scripts/: automacoes locais

## Diagnostico (antes)
- robots.txt bloqueava *.json/*.xml (inclusive sitemap e posts.json)
- sitemap.xml com priority/changefreq e lastmod inconsistentes
- falta de canonical/OG/Twitter/JSON-LD em paginas publicas
- ausencia de favicon/manifest padronizados
- imagens sem alt/width/height em varias paginas

## Diagnostico (depois)
- totalPages: 23
- totalPosts: 16
- pagesWithTitle: 23
- pagesWithDescription: 23
- pagesWithCanonical: 23
- pagesWithOG: 23
- pagesWithStructuredData: 23
- imagesMissingAltCount: 0
- brokenLinksCount: 0

## Checklist implementado
- robots.txt atualizado com Sitemap absoluto
- sitemap.xml gerado sem priority/changefreq
- meta tags normalizadas (title, description, canonical, OG, Twitter)
- JSON-LD com Organization/WebSite e BlogPosting nas paginas de artigo
- favicon/manifest adicionados
- atributos de imagem (alt/loading/decoding/width/height) quando possivel

## Pendencias / decisoes humanas
- Verificar se o dominio canonico esta correto (CNAME nao encontrado; foi usado README)
- Revisar titulos/descricoes gerados automaticamente para ajustes editoriais
- Validar links apontados como quebrados (se houver)
