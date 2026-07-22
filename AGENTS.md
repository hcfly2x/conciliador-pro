# Conciliador Pro

## Contexto Fixo
- Projeto: conciliador financeiro pessoal.
- Stack: Flask com PostgreSQL hosted/SQLite local no backend, Next.js no frontend.
- Pasta oficial do projeto: `C:\Users\hcfly\Downloads\conciliador-pro-github`.
- Nao criar novas pastas de projeto fora da pasta oficial.
- Qualquer arquivo temporario, log, zip ou documentacao deve ficar dentro da pasta do projeto, salvo pedido explicito do usuario.

## Backend
- Entrada principal: `backend/app.py`; implementacao compartilhada atual em
  `backend/core/application.py`, em processo de separacao por blueprints.
- Banco local: `backend/data/conciliador_pro.db`.
- Dependencias Python devem ficar em `backend/.venv`. Nesta copia o ambiente pode
  estar ausente; nesse caso, registrar o desvio e usar o Python global somente
  para validacao local.
- Quando o ambiente existir, usar:
  `backend\.venv\Scripts\python.exe backend\app.py`
- `backend/run.bat` deve chamar diretamente `.venv\Scripts\python.exe app.py`.
- Backend atualmente sobe em `http://127.0.0.1:5061`.
- Em ambiente hospedado, jobs persistentes sao consumidos por
  `backend/worker.py`; localmente existe fallback inline.

## Frontend
- Frontend principal: `frontend`.
- Next.js 15.
- Tela de importacao: `frontend/components/import/ImportPage.tsx`.
- API client: `frontend/lib/api.ts`.
- Tipos: `frontend/types/index.ts`.
- Arquivo de ambiente: `frontend/.env.local`.
- O frontend deve usar `NEXT_PUBLIC_API_URL=http://127.0.0.1:5061/api/v1`.

## Regras De Produto
- O usuario classifica lancamentos do zero.
- Lancamentos reais so podem vir de extratos ou cartoes importados.
- Importar base historica serve apenas para sugestoes de categoria/subcategoria, nunca para criar lancamentos reais.
- Contas/tipos oficiais:
  - EXTRATO DA CONTA SANTANDER
  - EXTRATO DA CONTA XP
  - EXTRATO DA CONTA NUBANK
  - CARTAO SANTANDER
  - CARTAO XP
  - CARTAO NUBANK
- Cartao de credito e saida por padrao.
- Em cartao, receita apenas para estorno, reembolso, cashback, credito ou devolucao.
- Extratos podem ter entradas e saidas.

## Importacao E Deduplicacao
- O fluxo ideal de importacao tem pre-importacao, validacao visual e confirmacao final.
- Antes de salvar importacao, mostrar:
  - total lido
  - duplicados no banco
  - duplicados internos do arquivo
  - novos para inserir
  - warnings de baixa confianca ou poucos lancamentos
- Duplicado no mesmo arquivo pode ser legitimo e deve ser permitido.
- Duplicado contra o banco existente nunca deve ser reinserido por padrao.
- Nunca alterar regras de deduplicacao sem avisar o usuario.

## Estado Atual Importante
- Repositorio principal: branch `main` do projeto `conciliador-pro-github`.
- Backend usa PostgreSQL em producao e SQLite apenas no desenvolvimento/testes.
- Frontend Next.js compila normalmente no Windows e e publicado na Vercel.
- Backend e publicado no Render; o commit publicado deve ser registrado a cada release.

## Cuidados De Trabalho
- Nao criar copias paralelas do repositorio.
- Se precisar gerar entregaveis, criar uma subpasta dentro da pasta oficial.
- Nao remover dados do banco sem pedido explicito.
- Antes de limpar arquivos, conferir se nao sao usados pelo app.
- Preferir mudancas pequenas e verificaveis por patch.

## Versao Web (2026-07-13)
- Banco: `backend/db.py` decide entre Postgres hosted (`DATABASE_URL`) e SQLite local.
- Autenticacao: `backend/auth.py` + guard em `app.py`; perfis admin e colaborador.
- Protecao pos-classificacao: colunas `locked/classified_by/classified_at` em `transactions`; erro 423 TX_LOCKED; desbloqueio via `POST /transactions/<id>/unlock` (admin, auditado).
- Auditoria: tabela `audit_log`; consulta em `GET /api/v1/audit`.
- Frontend: pagina `/login`, token Bearer em `sessionStorage`, validacao por `/auth/me`, cadeado + Desbloquear na tabela de lancamentos.
- Dev local sem login: `AUTH_DISABLED=1` no backend e `NEXT_PUBLIC_AUTH_DISABLED=true` no frontend.
- Documentacao: `docs/ARQUITETURA-WEB.md` e `docs/DEPLOY.md`.
