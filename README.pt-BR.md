# Startup India GOAT

`startup-india-goat` é uma skill de agente para pesquisa baseada em evidências citadas sobre uma startup indiana ou um grupo limitado. Aceita linguagem natural, mostra um contrato de pesquisa antes da coleta e separa fontes públicas de sessões explicitamente autorizadas.

Conforme a disponibilidade, cobre GitHub, Reddit, X, YouTube, Web, YourStory, Screener, The Ken, Inc42, Startup India, Tracxn e LinkedIn. Paywalls, CAPTCHA, limites, autenticação e mudanças de esquema são informados com honestidade.

Cada execução salva Markdown, HTML, JSON versionado, evidências brutas sanitizadas e um manifesto em `STARTUP_GOAT_MEMORY_DIR` (padrão `~/Documents/StartupIndiaGOAT/`). A rubrica GOAT é qualitativa e não cria uma pontuação composta opaca.

Veja [`skills/startup-india-goat/SKILL.md`](skills/startup-india-goat/SKILL.md) e [`CONFIGURATION.md`](CONFIGURATION.md).