# Índice da documentação

Atualizado em 24/07/2026. O código da `main` é a fonte técnica principal;
`PROJECT_CONTEXT.md` consolida as regras do produto. Em caso de divergência,
não implemente a partir de documento histórico.

## Fontes vigentes — ordem de leitura

1. `../PROJECT_CONTEXT.md`: escopo, regras financeiras, decisões e itens
   abandonados.
2. `../ROADMAP.md`: prioridades confirmadas, ordenadas por impacto e risco.
3. `ARQUITETURA-WEB.md`: topologia e responsabilidades técnicas atuais.
4. `api-contract.md`: mapa de rotas e contratos de integração.
5. `database.md`: persistência, migrations e regras de integridade.
6. `DEPLOY.md` e `VARIAVEIS-AMBIENTE.md`: operação, deploy, backup e rollback.
7. `RELEASES.md`: releases confirmadas em produção.
8. `../CODE_REVIEW_2026-07-23.md`: revisão estática anterior; ler junto do Git
   e dos commits posteriores.

## Evidências e critérios de decisão

- `REGRESSAO-FINANCEIRA-2026-07-22.md`: matriz anonimizada de parsers.
- `HOMOLOGACAO-AMBIENTES-2026-07-22.md`: evidência pontual de ambiente; as
  versões nela registradas não substituem o health atual.
- `AMOSTRAS-HOMOLOGACAO.md`: inventário agregado, sem documentos privados.
- `AVALIACOES-POS-ESTABILIZACAO.md`: critérios para mudanças ainda não
  autorizadas, como NUMERIC, FKs e object storage.

## Históricos — não são especificação

`ROADMAP-FINALIZACAO.md`, `ROADMAP-MELHORIAS.md`, `CODE-REVIEW.md`,
`architecture.md`, `DATABASE_E_FLUXO.md`, `CONTEXTO_IMPORTANTE_PROJETO.md`,
`backend-tasks.md`, `PLANO_ACAO_REVISADO_2026-05-08.md`,
`PROMPT_PARA_CLAUDE.md` e os documentos de análise/review datados registram
estados anteriores. Alguns citam FastAPI, SQLAlchemy, SQLite-only, schema 2 ou
commits antigos: não são a arquitetura vigente.
