# api-contract.md — Contrato de API

Base URL: `http://localhost:8000/api/v1`
Auth: JWT via httpOnly cookie (definido em /auth/login)
Todos os endpoints exceto /auth/login e /health exigem autenticação.

---

## Padrões

### Paginação
```json
// Query params: ?page=1&page_size=100
{
  "items": [...],
  "total": 342,
  "page": 1,
  "page_size": 100,
  "total_pages": 4
}
```

### Erros
```json
{
  "detail": "Mensagem do erro",
  "code": "ERROR_CODE"
}
```

Códigos HTTP usados:
- 200 OK
- 201 Created
- 400 Bad Request (validação)
- 401 Unauthorized
- 404 Not Found
- 409 Conflict (duplicata de arquivo)
- 422 Unprocessable Entity (parse falhou)
- 500 Internal Server Error

---

## AUTH

### POST /auth/login
```json
// Request
{ "username": "admin", "password": "senha" }

// Response 200
{ "message": "Login successful" }
// Set-Cookie: access_token=<jwt>; HttpOnly; SameSite=Strict
```

### POST /auth/logout
```json
// Response 200
{ "message": "Logged out" }
// Limpa o cookie
```

### GET /auth/me
```json
// Response 200
{ "username": "admin", "authenticated": true }
```

---

## ACCOUNTS

### GET /accounts
```json
// Response 200
[
  {
    "id": "uuid",
    "name": "CONTA SANTANDER",
    "type": "checking",
    "color": "#2563eb",
    "is_active": true,
    "created_at": "2026-01-01T00:00:00"
  }
]
```

### POST /accounts
```json
// Request
{ "name": "CARTÃO XP", "type": "credit_card", "color": "#7c3aed" }

// Response 201
{ "id": "uuid", "name": "CARTÃO XP", ... }
```

### PUT /accounts/{id}
```json
// Request
{ "name": "CARTÃO XP", "type": "credit_card", "color": "#7c3aed", "is_active": true }
// Response 200 — objeto atualizado
```

### DELETE /accounts/{id}
```json
// Response 200
{ "ok": true }
// REGRA: não deleta se houver transactions associadas → 400
```

---

## CATEGORIES

### GET /categories
```json
// Query: ?type=expense|income
// Response 200
[
  {
    "id": "uuid",
    "name": "GASTO PESSOAL",
    "color": "#dc2626",
    "text_color": "#ffffff",
    "type": "expense"
  }
]
```

### POST /categories
```json
// Request
{ "name": "GASTO PESSOAL", "color": "#dc2626", "text_color": "#fff", "type": "expense" }
// Response 201
```

### PUT /categories/{id}
```json
// Request — mesmos campos do POST
// Response 200
```

### DELETE /categories/{id}
```json
// Response 200 { "ok": true }
// REGRA: se houver transactions com essa categoria → 400 com contagem
```

---

## SUBCATEGORIES

### GET /subcategories
```json
// Response 200
[{ "id": "uuid", "name": "COMIDA/BEBIDA" }]
```

### POST /subcategories
```json
// Request: { "name": "UBER" }
// Response 201 — ou retorna existente se nome já existe (upsert)
```

### DELETE /subcategories/{id}
```json
// Response 200 { "ok": true }
```

---

## IMPORT

### POST /import/upload
```
Content-Type: multipart/form-data
Fields:
  file: arquivo (PDF, XLSX, XLS, CSV)
  account_id: UUID da conta (obrigatório)
```

```json
// Response 201
{
  "imported_file_id": "uuid",
  "filename": "extrato_santander_jan2026.csv",
  "account_name": "CONTA SANTANDER",
  "total_parsed": 45,
  "total_inserted": 43,
  "total_duplicates": 2,
  "total_errors": 0,
  "transactions_preview": [
    {
      "id": "uuid",
      "date": "2026-01-13",
      "description": "PIX PARA MARISA CARNEIRO",
      "amount": -11000.00,
      "type": "expense",
      "status": "pending"
    }
  ]
}

// Response 409 — arquivo já importado
{
  "detail": "Arquivo já importado em 13/01/2026 às 21:00 (45 lançamentos).",
  "code": "FILE_ALREADY_IMPORTED",
  "imported_file_id": "uuid"
}

// Response 422 — parse falhou
{
  "detail": "Não foi possível extrair lançamentos do arquivo.",
  "code": "PARSE_FAILED"
}
```

### GET /import/history
```json
// Response 200
[
  {
    "id": "uuid",
    "filename": "extrato_jan2026.csv",
    "file_type": "csv",
    "account_name": "CONTA SANTANDER",
    "total_parsed": 45,
    "total_inserted": 43,
    "total_duplicates": 2,
    "imported_at": "2026-01-13T21:00:00"
  }
]
```

---

## TRANSACTIONS

### GET /transactions
```
Query params:
  page          int     default 1
  page_size     int     default 100, max 500
  status        string  pending|reconciled|duplicate|ignored
  type          string  income|expense
  account_id    UUID
  category_id   UUID
  subcategory_id UUID
  competence_month string  ex: "2026/01"
  date_from     date    ex: "2026-01-01"
  date_to       date    ex: "2026-01-31"
  search        string  busca em description
  sort_by       string  date|amount|description|category  default: date
  sort_order    string  asc|desc  default: desc
```

```json
// Response 200
{
  "items": [
    {
      "id": "uuid",
      "date": "2026-01-13",
      "competence_month": "2026/01",
      "description": "PIX PARA MARISA CARNEIRO CAIXA",
      "amount": -11000.00,
      "type": "expense",
      "status": "pending",
      "account_id": "uuid",
      "account_name": "CONTA SANTANDER",
      "account_color": "#2563eb",
      "category_id": null,
      "category_name": null,
      "category_color": null,
      "subcategory_id": null,
      "subcategory_name": null,
      "notes": "",
      "imported_file_id": "uuid"
    }
  ],
  "total": 342,
  "page": 1,
  "page_size": 100,
  "total_pages": 4,
  "summary": {
    "total_income": 8500.00,
    "total_expense": -45230.50,
    "balance": -36730.50,
    "pending_count": 28,
    "reconciled_count": 314
  }
}
```

### GET /transactions/{id}
```json
// Response 200 — objeto completo com raw_data incluído
```

### PATCH /transactions/{id}/classify
```json
// Request
{
  "category_id": "uuid",
  "subcategory_id": "uuid",  // opcional
  "notes": "IMPLANTE DENTAL"  // opcional
}
// REGRA: status muda para "reconciled" automaticamente

// Response 200 — objeto atualizado
```

### PATCH /transactions/bulk-classify
```json
// Request
{
  "ids": ["uuid1", "uuid2", "uuid3"],
  "category_id": "uuid",
  "subcategory_id": "uuid"  // opcional
}

// Response 200
{ "updated": 3 }
```

### PATCH /transactions/{id}/status
```json
// Request
{ "status": "ignored" }
// Permite mudar para: ignored, pending
// NÃO permite mudar para reconciled via este endpoint (use /classify)

// Response 200 — objeto atualizado
```

### PATCH /transactions/{id}/unmark-duplicate
```json
// Desmarca uma duplicata, muda status para "pending"
// Response 200 — objeto atualizado
```

### DELETE /transactions/{id}
```json
// Response 200 { "ok": true }
```

### GET /transactions/months
```json
// Retorna lista de meses com lançamentos (para filtro)
// Response 200
["2026/01", "2025/12", "2025/11", ...]
```

---

### GET /transactions com filas de classificacao
```
Query params adicionais:
  classification_queue links|suggestions|none|waiting|dismissed|classified
  suggestion_strength  strong|weak
  sort_by               suggestion_confidence
```

Cada lancamento pode incluir `suggestion_state`, `suggestion_count`,
`suggestion_confidence`, `suggestion_dismissed` e `suggestion_calculated_at`.

### POST /transactions/suggestions/jobs
```json
// Request: incremental por padrao; full ignora o cache existente
{ "full": false }

// Response 202
{ "id": "uuid", "status": "queued", "mode": "incremental" }
```

### GET /suggestion-jobs/{id}

Retorna status, progresso, contagens, mensagem, erro e logs do job persistente.

### GET /suggestion-jobs-active

Retorna o job `queued` ou `running` mais recente. Responde 404 quando nao ha job ativo.

### GET /transactions/suggestions/summary
```json
{
  "pending": 12,
  "links": 2,
  "strong": 4,
  "weak": 3,
  "none": 1,
  "waiting": 2,
  "dismissed": 0,
  "classified": 80
}
```

### POST /transactions/suggestions/batch
```json
// Consulta apenas resultados persistidos; nao dispara calculo pesado.
// Request
{ "transaction_ids": ["uuid1", "uuid2"] }

// Response
{
  "items": { "uuid1": [{ "category_id": "uuid", "confidence": 84 }] },
  "states": { "uuid1": "completed", "uuid2": "pending" }
}
```

### GET /transactions/{id}/suggestions

Retorna `{ "items": [...], "state": "completed" }` a partir do cache persistente.

### POST /transactions/{id}/suggestions/dismiss

Mantem o lancamento na fila `Ignorados`; recalculos atualizam o cache, mas nao
aplicam nem reexibem a sugestao automaticamente.

---

## REPORTS

### GET /reports/summary
```
Query: ?competence_month=2026/01&date_from=...&date_to=...
```
```json
// Response 200
{
  "total_transactions": 342,
  "pending": 28,
  "reconciled": 314,
  "total_income": 8500.00,
  "total_expense": -45230.50,
  "balance": -36730.50
}
```

### GET /reports/by-category
```
Query: ?type=expense|income&competence_month=2026/01
```
```json
// Response 200
[
  {
    "category_id": "uuid",
    "category_name": "GASTO PESSOAL",
    "category_color": "#dc2626",
    "total": -12450.30,
    "count": 87,
    "percentage": 42.5
  }
]
```

### GET /reports/monthly
```
Query: ?months=12  (últimos N meses, default 12)
```
```json
// Response 200
[
  {
    "month": "2026/01",
    "income": 8500.00,
    "expense": -45230.50,
    "balance": -36730.50,
    "transaction_count": 342
  }
]
```

---

## HEALTH

### GET /health
```json
// Response 200 (sem auth)
{ "status": "ok", "version": "1.0.0", "db": "connected" }
```
