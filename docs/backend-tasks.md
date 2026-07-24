# backend-tasks.md — HISTÓRICO — Tarefas para o Codex

> Não vigente. A referência a FastAPI, SQLAlchemy e Alembic foi abandonada.
> Consulte `../ROADMAP.md` e `ARQUITETURA-WEB.md`.

Stack: FastAPI + PostgreSQL + SQLAlchemy + Alembic + Python 3.12
Leia architecture.md, database.md e api-contract.md antes de implementar.

---

## TASK-01 — Setup inicial do projeto

### Objetivo
Criar estrutura base do projeto FastAPI com PostgreSQL.

### Arquivos a criar
```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, CORS, routers
│   ├── core/
│   │   ├── config.py        # Settings via pydantic-settings
│   │   ├── database.py      # Engine, SessionLocal, Base, get_db
│   │   ├── security.py      # JWT create/verify, password hash
│   │   └── deps.py          # get_current_user dependency
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── router.py    # inclui todos os sub-routers
│   ├── models/
│   │   └── __init__.py
│   ├── schemas/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   └── parsers/
│       └── __init__.py
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── requirements.txt
├── .env.example
└── Dockerfile
```

### Variáveis de ambiente (.env.example)
```
DATABASE_URL=postgresql://user:password@localhost:5432/conciliador
SECRET_KEY=sua-chave-secreta-aqui-minimo-32-chars
ADMIN_USERNAME=admin
ADMIN_PASSWORD=senha-segura
ACCESS_TOKEN_EXPIRE_HOURS=24
LOG_LEVEL=INFO
```

### requirements.txt
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.0
alembic>=1.13.0
psycopg2-binary>=2.9.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
pdfplumber>=0.11.0
openpyxl>=3.1.0
pandas>=2.0.0
python-dateutil>=2.9.0
```

### Critérios de aceite
- [ ] `GET /health` retorna `{"status": "ok", "db": "connected"}`
- [ ] App inicia sem erros com `uvicorn app.main:app --reload`
- [ ] CORS configurado para `http://localhost:3000`

---

## TASK-02 — Models SQLAlchemy + Migration inicial

### Objetivo
Criar todos os models e migration Alembic.

### Arquivo: app/models/models.py
Criar as seguintes classes SQLAlchemy com Base:
- `Account`
- `Category`
- `Subcategory`
- `ImportedFile`
- `Transaction`

Seguir exatamente o schema em `docs/database.md`.

### Regras
- Usar UUID como PK em todos os models (`uuid.uuid4`)
- `Transaction.tx_hash` com índice único
- `ImportedFile.file_hash` com índice único
- `Transaction.updated_at` atualiza automaticamente com `onupdate`
- Todos os Enums devem ser nativos PostgreSQL (`sa.Enum`)

### Critérios de aceite
- [ ] `alembic upgrade head` cria todas as tabelas sem erro
- [ ] Todos os índices e constraints criados
- [ ] Enums criados como tipos nativos no PostgreSQL

---

## TASK-03 — Auth (login/logout/me)

### Objetivo
Implementar autenticação JWT com cookie httpOnly.

### Arquivo: app/api/v1/auth.py

### Endpoints
Ver `docs/api-contract.md` seção AUTH.

### Lógica
1. POST /auth/login
   - Valida username/password contra ADMIN_USERNAME/ADMIN_PASSWORD do .env
   - Gera JWT com `sub=username, exp=now+24h`
   - Seta cookie: `access_token`, httpOnly=True, samesite="strict", secure=False (local)
   - Retorna 401 se credenciais inválidas

2. POST /auth/logout
   - Deleta o cookie
   - Retorna 200

3. GET /auth/me
   - Lê token do cookie
   - Retorna username se válido, 401 se inválido/expirado

### Dependency: get_current_user
- Lê cookie `access_token`
- Verifica JWT
- Levanta 401 HTTPException se inválido
- Usado em todos os outros endpoints

### Critérios de aceite
- [ ] Login com credenciais corretas seta cookie e retorna 200
- [ ] Login com credenciais erradas retorna 401
- [ ] Cookie é httpOnly (não acessível via JS)
- [ ] Token expirado retorna 401
- [ ] /auth/me retorna username após login

---

## TASK-04 — CRUD Accounts

### Arquivo: app/api/v1/accounts.py + app/schemas/account.py + app/services/account_service.py

### Schemas Pydantic (account.py)
```python
class AccountCreate(BaseModel):
    name: str  # será salvo em uppercase
    type: AccountType
    color: str = "#2563eb"

class AccountUpdate(AccountCreate):
    is_active: bool = True

class AccountOut(BaseModel):
    id: UUID
    name: str
    type: AccountType
    color: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

### Endpoints
Ver api-contract.md seção ACCOUNTS.

### Regras
- name sempre salvo em UPPERCASE
- DELETE retorna 400 se houver transactions associadas (com contagem)

### Critérios de aceite
- [ ] CRUD completo funcionando
- [ ] Nomes em uppercase
- [ ] Delete bloqueado se tiver transactions

---

## TASK-05 — CRUD Categories + Subcategories

### Arquivo: app/api/v1/categories.py + schemas + service

### Regras
- `Category.name` em UPPERCASE
- `Subcategory.name` em UPPERCASE
- POST /subcategories faz upsert: se nome já existe, retorna o existente
- DELETE de categoria retorna 400 se houver transactions (com contagem)

### Seed inicial
Criar função `seed_defaults(db)` que popula as categorias padrão se o banco estiver vazio:
```python
CATEGORIAS = [
    ("GASTO PESSOAL",        "#dc2626", "#fff", "expense"),
    ("CASA NOVA",            "#16a34a", "#fff", "expense"),
    ("CASA ANTIGA",          "#15803d", "#fff", "expense"),
    ("COMPRA SPEED",         "#d97706", "#fff", "expense"),
    ("PAG CARTÃO",           "#7c3aed", "#fff", "expense"),
    ("REEMBOLSADO SMTK",     "#2563eb", "#fff", "income"),
    ("GASTO PESSOAL VIAGEM", "#db2777", "#fff", "expense"),
    ("INVESTIMENTO",         "#0d9488", "#fff", "expense"),
    ("RECEITA",              "#4ade80", "#111", "income"),
    ("SALÁRIO",              "#22c55e", "#fff", "income"),
    ("POKER",                "#f59e0b", "#111", "expense"),
    ("PAI",                  "#64748b", "#fff", "expense"),
    ("SMARTEK",              "#3b82f6", "#fff", "expense"),
    ("NÃO SEI",              "#6b7280", "#fff", "expense"),
    ("ENTRE CONTAS",         "#94a3b8", "#111", "income"),
    ("DEPOSITO SMTK",        "#06b6d4", "#111", "income"),
]
```

Chamar seed_defaults no startup da app (em main.py).

### Critérios de aceite
- [ ] CRUD categorias completo
- [ ] CRUD subcategorias com upsert
- [ ] Seed popula categorias padrão na primeira execução
- [ ] Filtro por type=expense|income funciona

---

## TASK-06 — Parsers de arquivo

### Arquivo: app/parsers/

#### app/parsers/utils.py
```python
def normalize_description(s: str) -> str:
    """Remove acentos, uppercase, colapsa espaços, remove chars especiais."""

def parse_money(raw) -> Optional[float]:
    """Converte string BR (R$ 1.234,56) para float. Retorna None se falhar."""

def parse_date_br(raw) -> Optional[date]:
    """Tenta múltiplos formatos: DD/MM/YYYY, DD/MM/YY, YYYY-MM-DD, Excel serial."""

def make_tx_hash(account_id: str, date: date, description: str, amount: float) -> str:
    """SHA256(account_id|date|normalize(description)|abs_cents)"""

def make_file_hash(content: bytes) -> str:
    """SHA256 do conteúdo binário."""
```

#### app/parsers/base.py
```python
@dataclass
class ParsedRow:
    date: date
    description: str
    amount: float  # positivo=receita, negativo=despesa
    type: str  # "income" | "expense"
    raw: dict  # linha original
```

#### app/parsers/csv_parser.py
- Detecta separador automaticamente (`;`, `,`, `\t`)
- Detecta encoding (utf-8, latin-1, cp1252)
- Detecta colunas por heurística de cabeçalho normalizado
  - DATE_HINTS: data, date, dt, lancamento, data_lancamento
  - DESC_HINTS: descricao, historico, memo, estabelecimento, beneficiario
  - AMOUNT_HINTS: valor, value, amount, vlr
  - CREDIT_HINTS: credito, credit, entrada
  - DEBIT_HINTS: debito, debit, saida
- Tenta offset de 0 a 9 linhas para encontrar cabeçalho
- Retorna List[ParsedRow]

#### app/parsers/excel_parser.py
- Usa openpyxl/pandas
- Percorre todas as sheets
- Mesma heurística de colunas do CSV
- Suporta Excel serial dates

#### app/parsers/pdf_parser.py
- Tentativa 1: extração de tabelas via pdfplumber
- Tentativa 2: parsing linha a linha do texto
  - Regex: `^(\d{2}/\d{2}/\d{4})` no início + valor no final
- Retorna List[ParsedRow]
- Lança ValueError se não encontrar nenhum lançamento

#### app/parsers/__init__.py
```python
def parse_file(content: bytes, filename: str) -> List[ParsedRow]:
    """Detecta tipo pelo filename e chama parser correto."""
```

### Critérios de aceite
- [ ] CSV com separador `;` e encoding latin-1 funciona
- [ ] Excel com data serial funciona
- [ ] PDF com tabela estruturada funciona
- [ ] PDF com texto livre funciona
- [ ] Arquivo inválido levanta ValueError com mensagem clara

---

## TASK-07 — Import endpoint

### Arquivo: app/api/v1/import_router.py + app/services/import_service.py

### POST /import/upload (multipart/form-data)
Campos: `file` (UploadFile), `account_id` (UUID str)

#### Lógica completa
```
1. Ler conteúdo do arquivo (await file.read())
2. Calcular file_hash = make_file_hash(content)
3. Verificar se file_hash já existe em imported_files
   → Se sim: retornar 409 com detalhes do import anterior
4. Validar account_id existe em accounts → 404 se não
5. Chamar parse_file(content, filename)
   → Se levantar ValueError: retornar 422 com mensagem
6. Para cada ParsedRow:
   a. Calcular tx_hash = make_tx_hash(account_id, row.date, row.description, row.amount)
   b. Verificar se tx_hash já existe em transactions
      → Se sim: incrementar duplicates_count, NÃO inserir
      → Se não: criar Transaction com status="pending"
7. Salvar ImportedFile com contagens
8. Commit tudo em uma transação
9. Retornar ImportResult com preview dos primeiros 20 lançamentos
```

#### ImportResult schema
```python
class ImportResult(BaseModel):
    imported_file_id: UUID
    filename: str
    account_name: str
    total_parsed: int
    total_inserted: int
    total_duplicates: int
    total_errors: int
    transactions_preview: List[TransactionOut]
```

### GET /import/history
- Retorna todos os ImportedFile ordenados por imported_at DESC
- Join com Account para incluir account_name

### Critérios de aceite
- [ ] Upload CSV funciona end-to-end
- [ ] Upload XLSX funciona end-to-end
- [ ] Upload PDF funciona end-to-end
- [ ] Re-upload do mesmo arquivo retorna 409
- [ ] Lançamentos com tx_hash repetido ficam como "pending" (não inseridos duas vezes)
- [ ] ImportedFile salvo com contagens corretas
- [ ] Tudo em uma transação DB (se falhar no meio, nada salvo)

---

## TASK-08 — Transactions CRUD + filtros

### Arquivo: app/api/v1/transactions.py + app/schemas/transaction.py + app/services/transaction_service.py

### Todos os endpoints de /transactions
Ver api-contract.md seção TRANSACTIONS.

### TransactionOut schema
```python
class TransactionOut(BaseModel):
    id: UUID
    date: date
    competence_month: str
    description: str
    amount: float
    type: str
    status: str
    account_id: UUID
    account_name: str
    account_color: str
    category_id: Optional[UUID]
    category_name: Optional[str]
    category_color: Optional[str]
    subcategory_id: Optional[UUID]
    subcategory_name: Optional[str]
    notes: str
    imported_file_id: UUID
    model_config = ConfigDict(from_attributes=True)
```

### Regras do classify
- PATCH /{id}/classify
  - Valida category_id existe
  - Seta category_id, subcategory_id, notes
  - Muda status para "reconciled"
  - Atualiza updated_at

### Regras do bulk-classify
- PATCH /bulk-classify
  - Aceita lista de ids
  - Aplica mesma categoria a todos
  - Retorna contagem de atualizados

### GET /transactions/months
- SELECT DISTINCT competence_month FROM transactions ORDER BY DESC
- Retorna lista de strings

### Critérios de aceite
- [ ] Listagem com todos os filtros combinados funciona
- [ ] Paginação funciona
- [ ] Sorting por todos os campos funciona
- [ ] classify muda status para reconciled
- [ ] bulk-classify funciona com 50+ ids
- [ ] summary sempre reflete o filtro ativo

---

## TASK-09 — Reports

### Arquivo: app/api/v1/reports.py + app/services/report_service.py

### Endpoints
Ver api-contract.md seção REPORTS.

### Regras
- /reports/by-category: apenas lançamentos com status != "ignored" e != "duplicate"
- percentage = (abs(categoria.total) / abs(total_geral)) * 100
- /reports/monthly: incluir meses sem lançamentos como zero (não omitir)

### Critérios de aceite
- [ ] summary retorna totais corretos
- [ ] by-category retorna ordenado por total DESC
- [ ] percentage soma 100%
- [ ] monthly retorna todos os meses no range

---

## TASK-10 — Docker Compose

### Arquivo: docker-compose.yml (na raiz)
```yaml
version: '3.9'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: conciliador
      POSTGRES_PASSWORD: conciliador123
      POSTGRES_DB: conciliador
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://conciliador:conciliador123@db:5432/conciliador
      SECRET_KEY: dev-secret-key-mude-em-producao
      ADMIN_USERNAME: admin
      ADMIN_PASSWORD: admin123
    depends_on:
      - db
    volumes:
      - ./backend:/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

volumes:
  postgres_data:
```

### Critérios de aceite
- [ ] `docker compose up` sobe DB + backend sem erro
- [ ] Migrations rodam automaticamente no startup
- [ ] `GET /health` retorna db: connected

---

## ORDEM DE EXECUÇÃO

Execute as tasks nesta ordem:
1. TASK-01 (setup)
2. TASK-02 (models)
3. TASK-03 (auth)
4. TASK-04 (accounts)
5. TASK-05 (categories)
6. TASK-06 (parsers) ← crítico, teste bem
7. TASK-07 (import) ← depende de parsers
8. TASK-08 (transactions)
9. TASK-09 (reports)
10. TASK-10 (docker)

Não pule tasks. Cada uma tem testes que validam a próxima.
