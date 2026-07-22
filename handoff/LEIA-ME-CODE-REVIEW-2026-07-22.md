# Pacote para code review - 22/07/2026

Este pacote representa o estado local atual do Conciliador Pro. Ele inclui
alteracoes ainda nao commitadas nem publicadas. A producao permanece no commit
`c853b14`.

## Ordem de leitura sugerida

1. `PROJECT_CONTEXT.md`
2. `docs/ROADMAP-FINALIZACAO.md`
3. `docs/ANALISE-PERFORMANCE-E-ESCALABILIDADE-2026-07-22.md`
4. `docs/ARQUITETURA-WEB.md`
5. codigo e testes atuais

O codigo atual e a fonte principal da verdade. Documentos marcados como
historicos nao devem reintroduzir decisoes abandonadas.

## Escopo pedido ao revisor

- identificar gargalos que crescem com o volume de dados;
- revisar consultas PostgreSQL, indices, paginacao, N+1 e concorrencia;
- revisar o custo do vinculo com a base historica;
- revisar repeticao de requisicoes e invalidacoes no frontend;
- avaliar web e worker separados;
- propor uma sequencia incremental que preserve todos os dados existentes;
- apontar riscos de regressao financeira ou operacional.

## Validacao antes da geracao

- 95 testes Python aprovados; 1 integracao PostgreSQL local opcional ignorada;
- 8 jornadas Playwright aprovadas;
- `git diff --check` aprovado;
- nenhuma migration ou alteracao em dados de producao;
- nenhum commit, push ou deploy das mudancas locais.

## Exclusoes intencionais do ZIP

- `.git`;
- dependencias e builds regeneraveis: `node_modules`, `.next`, `.venv` e caches;
- arquivos `.env` locais e potenciais credenciais;
- bancos SQLite, backups e documentos financeiros locais;
- arquivos temporarios e resultados do Playwright;
- outros arquivos ZIP previamente gerados.

Essas exclusoes nao removem codigo-fonte, testes, migrations, workflows,
documentacao ou arquivos de configuracao versionaveis.
