# Contrato da API - resumo vigente

Base: `/api/v1`. Atualizado em 22/07/2026. O mapa Flask e os testes prevalecem.

## Publicos

- `GET /health`
- `POST /auth/login`

`GET /health` responde `status`, `version`, `db`, `commit`, `schema_version`,
`worker_mode` e `worker_process`. Esses campos permitem conferir a revisao, o
schema e quem executa os jobs sem acessar dados financeiros.

Demais endpoints exigem `Authorization: Bearer <token>`. Escritas sao de admin
por padrao; rotas de trabalho cotidiano do colaborador sao marcadas
explicitamente no backend.

## Auth e auditoria

- `POST /auth/logout`, `GET /auth/me`
- `GET|POST /auth/users`, `PATCH /auth/users/<id>`
- `GET /audit`

## Importacao e jobs

- `POST /import/preview`, `POST /import/commit`, `GET /import/jobs/<id>`
- `GET /import/history`, `POST /import/seed`
- `GET /seed-import-jobs/<id>`, `GET /seed-import-jobs-active`
- `POST /import/scan-folder` retorna 410 por regra de produto.

O preview nao grava lancamentos. O commit retorna 202 e um job persistente. Um
duplicado existente no banco bloqueia o lote; `import_db_duplicates` nao autoriza
reinsercao.

## Transacoes, vinculos e sugestoes

- `GET /transactions`, `GET /transactions/months`
- `PATCH /transactions/<id>/classify`, `/flags`, `/unlink-history`
- `POST /transactions/<id>/unlock`
- `PATCH /transactions/bulk-classify`
- `POST /transactions/<id>/history-link`
- `POST /transactions/history-links/batch`
- `GET /transactions/<id>/suggestions`
- `POST /transactions/<id>/suggestions/dismiss`
- `POST /transactions/suggestions/jobs`, `/suggestions/batch`
- `GET /suggestion-jobs/<id>`, `/suggestion-jobs-active`
- `GET /transactions/suggestions/summary`, `/suggestions/evaluation`
- `POST /transactions/recalculate-probabilities`
- `POST /transactions/recalculate-history-links`
- `GET /recalculation-jobs/<id>`

## Cadastros, cofre e conciliacao

- Accounts, categories, subcategories e ledgers possuem rotas CRUD sob os nomes
  correspondentes.
- `GET /coverage`, `POST|DELETE /coverage/dispense`
- `GET|DELETE /coverage/files`, `GET /documents/<id>/download`
- `GET|POST /reconciliations`, `POST /reconciliations/<id>/undo`

## Relatorios e sistema

- `GET /reports/summary`, `/reports/by-category`, `/reports/monthly`
- `POST /system/reset` exige confirmacao literal e e exclusivo de admin.

## Erros relevantes

- `401 UNAUTHORIZED`, `403 FORBIDDEN`
- `409 FILE_ALREADY_IMPORTED` ou `DATABASE_DUPLICATES_FOUND`
- `423 TX_LOCKED`
- `429 LOGIN_RATE_LIMITED`
- `503 DATABASE_OVERLOADED`
