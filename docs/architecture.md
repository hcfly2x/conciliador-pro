# architecture.md — Conciliador Financeiro Pessoal

## 1. Visão Geral

Aplicação web pessoal para conciliação bancária. O usuário faz upload de extratos e faturas (PDF, XLSX, CSV), o sistema extrai os lançamentos, detecta duplicatas, e deixa os lançamentos pendentes de classificação manual por categoria e subcategoria.

---

## 2. Stack

| Camada | Tecnologia |
|---|---|
| Frontend | Next.js 15 + TypeScript + Tailwind + shadcn/ui |
| Estado global | Zustand |
| Formulários | React Hook Form + Zod |
| Backend | FastAPI (Python) |
| Banco de dados | PostgreSQL |
| ORM | SQLAlchemy + Alembic |
| Auth | JWT (single user, sem OAuth) |
| Parsing de arquivos | pdfplumber, openpyxl, pandas |
| Infra | Docker Compose (local) |
| Docs API | Swagger automático via FastAPI |

---

## 3. Arquitetura

```
conciliador-pro/
├── frontend/          # Next.js 15
│   ├── app/           # App Router
│   ├── components/    # UI components
│   ├── lib/           # api client, utils
│   ├── store/         # Zustand stores
│   └── types/         # TypeScript types
│
├── backend/           # FastAPI
│   ├── app/
│   │   ├── api/       # routers
│   │   ├── models/    # SQLAlchemy models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # business logic
│   │   ├── parsers/   # file parsers
│   │   └── core/      # config, db, auth
│   ├── alembic/       # migrations
│   └── tests/
│
└── docs/              # documentação
```

---

## 4. Fluxo Principal

```
1. Usuário faz upload de arquivo (PDF/XLSX/CSV)
2. Backend detecta formato e chama parser correto
3. Parser extrai lançamentos brutos (data, descrição, valor)
4. Sistema gera tx_hash para cada lançamento
   hash = SHA256(data + descricao_normalizada + valor + conta_id)
5. Verifica duplicatas no banco pelo tx_hash
   - Hash já existe → marca como "duplicata"
   - Hash novo → insere com status "pendente"
6. Retorna resumo: total, inseridos, duplicatas
7. Usuário acessa aba Pendentes e classifica manualmente
8. Ao classificar: status muda para "conciliado"
```

---

## 5. Autenticação

- Single user — sem cadastro público
- Login via usuário/senha configurados em variável de ambiente
- JWT com expiração de 24h
- Token armazenado em httpOnly cookie
- Middleware de auth em todas as rotas do backend exceto /auth/login e /health

---

## 6. Módulos

| Módulo | Responsabilidade |
|---|---|
| auth | login, refresh token, logout |
| transactions | CRUD de lançamentos, filtros, paginação |
| import | upload de arquivo, parsing, detecção de duplicatas |
| categories | CRUD de categorias e subcategorias |
| accounts | CRUD de contas bancárias |
| reports | relatórios por categoria, período, conta |

---

## 7. Regras de Negócio Críticas

### Detecção de Duplicata
- Gerada no momento do parse, antes de salvar
- tx_hash = SHA256(conta_id + data + descricao_normalizada + valor_centavos)
- descricao_normalizada = upper + remove acentos + colapsa espaços + remove caracteres especiais
- Se tx_hash já existe no banco → status = "duplicata"
- Duplicatas aparecem separadas na UI com indicação visual clara
- Usuário pode confirmar ou desmarcar uma duplicata manualmente

### Status dos Lançamentos
```
pendente     → importado, sem categoria
conciliado   → categoria definida pelo usuário
duplicata    → hash já existia no banco
ignorado     → usuário decidiu ignorar (não conta em relatórios)
```

### Importação Idempotente
- Re-importar o mesmo arquivo não cria novos lançamentos
- Arquivo é identificado por SHA256 do conteúdo binário
- Se file_hash já existe → retorna 409 com detalhe do import anterior

---

## 8. Segurança
- Roda local, sem exposição pública
- JWT em httpOnly cookie (não localStorage)
- CORS restrito a localhost
- Rate limiting simples em /auth/login (5 req/min)

---

## 9. Observabilidade
- Logs estruturados em JSON via Python logging
- Nível configurável via variável de ambiente LOG_LEVEL
- Cada import gera um log com: filename, total_parsed, inserted, duplicates, errors
