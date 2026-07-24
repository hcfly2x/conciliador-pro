# Pacote para code review — 24/07/2026

Este ZIP é um retrato limpo da `main` do Conciliador Pro no commit `86150c5`.
Ele não inclui banco, documentos financeiros, backups, credenciais, builds ou
dependências regeneráveis.

## Ordem de leitura obrigatória

1. `PROJECT_CONTEXT.md`
2. `ROADMAP.md`
3. `docs/README.md`
4. `docs/ARQUITETURA-WEB.md`, `docs/api-contract.md` e `docs/database.md`
5. `docs/DEPLOY.md`, `docs/VARIAVEIS-AMBIENTE.md` e `docs/RELEASES.md`
6. Código e testes atuais, começando por `backend/core/application.py`,
   `backend/parsers/engine.py` e `frontend/components/transactions/`.

O código é a fonte técnica principal. Não reintroduza itens marcados como
abandonados e não use arquivos históricos como especificação. Se houver
contradição, registre-a antes de sugerir implementação.

## Estado confirmado

- Produção: Vercel + Render + PostgreSQL/Supabase, schema 3.
- Health confirmado em 24/07/2026: `86150c5fc422`, `worker_mode: inline`.
- O web processa jobs persistidos; não há Background Worker ativo no Render.
- 113 testes Python identificados no repositório; o último workflow direcionado
  executou 19 testes e o build de produção do Next.js foi aprovado.
- A classificação em lote pergunta se itens já classificados devem ser
  preservados ou atualizados; atualizar itens protegidos exige admin e é
  auditado.

## Escopo desejado da revisão

1. Procurar defeitos que possam alterar, duplicar, omitir ou descaracterizar
   lançamentos financeiros, documentos ou auditoria.
2. Revisar contratos entre frontend e backend, principalmente importação,
   deduplicação, classificação, vínculos e conciliação.
3. Apontar riscos de segurança, concorrência e recuperação operacional.
4. Avaliar desempenho somente com proposta de medição antes de índices, cache
   ou migrações estruturais.
5. Priorizar recomendações por impacto, risco e esforço (Pareto 80/20).

## Limites confirmados

- Lançamentos reais só entram por importação com preview confirmado.
- Não há autoclassificação sem ação humana.
- Dados existentes, classificações, vínculos, conciliações, auditoria e cofre
  devem ser preservados.
- Não propor FastAPI, SQLAlchemy, Alembic, Docker Compose, SQLite em produção,
  importação por pasta, importação sem preview ou worker separado como mudança
  automática.
- Backup/restauração e rotação de credenciais exigem acesso externo e decisão
  do proprietário.

## Entrega esperada do revisor

Para cada achado: severidade, arquivo/trecho, cenário reproduzível, impacto
financeiro/operacional, correção mínima e teste recomendado. Diferencie
defeito comprovado, risco e oportunidade futura.
