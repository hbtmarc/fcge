Projeto de Revitalização do Site | FC Gestão Estratégica

1. Visão Geral do Projeto

Este repositório contém os arquivos da revitalização completa do site da FC Gestão Estratégica.
O projeto foi concebido para modernizar a presença digital da empresa, migrando de uma plataforma WordPress para uma arquitetura estática, focada em performance, segurança e uma experiência de usuário (UX) de alto nível.

O objetivo principal é transformar o site em uma poderosa ferramenta de negócios, otimizada para conversão e com excelente posicionamento em mecanismos de busca para o termo estratégico "Estudo de Dispersão Atmosférica".

2. Objetivos Estratégicos

    UX/UI Profissional: Implementar um design moderno, limpo e intuitivo, seguindo as melhores práticas de mercado para transmitir profissionalismo e confiança.

    Landing Page Focada em Conversão: Transformar a index.html em uma landing page que guia o usuário de forma clara, desde a apresentação dos diferenciais até a chamada para ação (contato).

    Otimização para SEO: Estruturar todo o conteúdo e código do site para maximizar o ranqueamento orgânico. Isso inclui o uso de tags semânticas, meta-informações detalhadas, um sitemap.xml bem definido e um arquivo robots.txt otimizado.

    Alta Performance e Segurança: Ao utilizar uma arquitetura estática, eliminamos as vulnerabilidades e a lentidão associadas a bancos de dados e plugins do WordPress, resultando em um site extremamente rápido e seguro.

    Responsividade Total: Garantir uma experiência de navegação perfeita em todos os dispositivos, de desktops a smartphones.

    Compatibilidade de Hospedagem: A estrutura simples permite que o site seja hospedado em qualquer serviço de hospedagem comum, sem a necessidade de configurações complexas.

3. Tecnologias Utilizadas

A simplicidade e a performance foram os pilares da escolha tecnológica.

    HTML5: Para a estruturação semântica de todo o conteúdo.

    Tailwind CSS: Um framework CSS utility-first para a criação de um design moderno e responsivo de forma rápida e consistente, diretamente no HTML.

    CSS3 Customizado: Estilos personalizados para animações avançadas, efeitos de hover, gradientes e o efeito parallax, que não são cobertos nativamente pelo Tailwind.

    JavaScript (Vanilla): Utilizado para adicionar interatividade e dinamismo, como as animações de scroll, o contador de números e a funcionalidade do menu mobile e do modal de vídeo. Nenhuma biblioteca ou framework pesado foi necessário, garantindo o carregamento rápido da página.

4. Estrutura de Arquivos

O projeto está organizado de forma lógica e clara, facilitando a manutenção futura.

/
|-- index.html            # [Landing Page principal]([url](https://hbtmarc.github.io/fcge/))
|-- servicos.html         # Página detalhada de serviços (foco em SEO)
|-- sobre.html            # Página institucional da empresa (foco em SEO)
|-- contato.html          # Página de contato com formulário
|-- blog.html             # Página agregadora para os posts do blog
|-- sitemap.xml           # Mapa do site para os buscadores
|-- robots.txt            # Diretrizes para os robôs de busca
|-- README.md             # Esta documentação

5. Funcionalidades e Destaques

    Animações de Scroll: Elementos surgem suavemente na tela (fade-in, fade-in-left, fade-in-right) à medida que o usuário rola a página, criando uma experiência de navegação dinâmica e engajante.

    Efeito Parallax: Seções de fundo com imagens fixas que criam uma percepção de profundidade durante o scroll, notavelmente na seção "Nosso Processo".

    Microinterações: Efeitos sutis de hover em botões, links e cards que fornecem feedback visual ao usuário, melhorando a usabilidade.

    Header Fixo e Inteligente: O cabeçalho permanece no topo da página durante a navegação, com um efeito de backdrop-blur para manter a legibilidade.

    Modal de Vídeo: Um player de vídeo que abre em um modal sobre a página, evitando que o usuário precise sair do site para assistir a um conteúdo institucional.

    Design Responsivo Mobile-First: O layout foi pensado primeiramente para telas pequenas e depois adaptado para telas maiores, garantindo uma usabilidade impecável no mobile.

6. Manutenção e Atualizações

    Conteúdo de Texto: Para alterar textos, basta editar diretamente o conteúdo dentro das tags HTML nos arquivos correspondentes (ex: <p>Altere este texto aqui</p>).

    Imagens: As imagens são carregadas a partir de URLs. Para alterá-las, substitua o link no atributo src da tag <img> ou no background-image do estilo CSS.

    Cores e Fontes: As cores principais (--brand-blue, --brand-green) e a fonte principal (Inter) estão definidas no bloco <style> no <head> de cada arquivo HTML, facilitando a alteração global da identidade visual.
