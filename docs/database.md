# database.md — Modelo de Dados

## Entidades

---

### accounts (contas bancárias)

| Coluna | Tipo | Descrição |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(100) | Ex: "CONTA SANTANDER", "CARTÃO XP" |
| type | ENUM | checking, credit_card, savings |
| color | VARCHAR(7) | Hex color para UI |
| is_active | BOOLEAN | default true |
| created_at | TIMESTAMP | |

Índices: name (unique)

---

### categories (categorias)

| Coluna | Tipo | Descrição |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(100) | Ex: "GASTO PESSOAL" |
| color | VARCHAR(7) | Hex color |
| text_color | VARCHAR(7) | Hex color do texto |
| type | ENUM | expense, income |
| is_active | BOOLEAN | default true |
| created_at | TIMESTAMP | |

Índices: name (unique)

---

### subcategories (subcategorias / tags)

| Coluna | Tipo | Descrição |
|---|---|---|
| id | UUID PK | |
| name | VARCHAR(100) | Ex: "COMIDA/BEBIDA", "UBER" |
| is_active | BOOLEAN | default true |
| created_at | TIMESTAMP | |

Índices: name (unique)
Nota: subcategoria é independente de categoria (segundo filtro livre)

---

### imported_files (arquivos importados)

| Coluna | Tipo | Descrição |
|---|---|---|
| id | UUID PK | |
| filename | VARCHAR(255) | Nome original do arquivo |
| file_hash | VARCHAR(64) | SHA256 do conteúdo binário |
| file_type | ENUM | csv, xlsx, xls, pdf |
| account_id | UUID FK → accounts | Conta detectada ou informada |
| total_parsed | INTEGER | Total de linhas no arquivo |
| total_inserted | INTEGER | Lançamentos novos inseridos |
| total_duplicates | INTEGER | Duplicatas detectadas |
| total_errors | INTEGER | Linhas com erro de parse |
| imported_at | TIMESTAMP | |

Índices: file_hash (unique)

---

### transactions (lançamentos)

| Coluna | Tipo | Descrição |
|---|---|---|
| id | UUID PK | |
| tx_hash | VARCHAR(64) | SHA256 para deduplicação |
| date | DATE | Data do lançamento |
| competence_month | VARCHAR(7) | Ex: "2026/01" |
| description | TEXT | Descrição original do banco |
| description_normalized | TEXT | Normalizada (upper, sem acentos) |
| amount | NUMERIC(12,2) | Positivo=receita, Negativo=despesa |
| type | ENUM | income, expense |
| status | ENUM | pending, reconciled, duplicate, ignored |
| account_id | UUID FK → accounts | |
| category_id | UUID FK → categories | NULL se pendente |
| subcategory_id | UUID FK → subcategories | NULL |
| notes | TEXT | Observação livre do usuário |
| imported_file_id | UUID FK → imported_files | |
| raw_data | JSONB | Linha original do arquivo |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

Índices:
- tx_hash (unique)
- (date, account_id)
- (status, date)
- (competence_month, account_id)
- category_id
- imported_file_id

---

## Relacionamentos

```
accounts 1──N transactions
accounts 1──N imported_files
categories 1──N transactions
subcategories 1──N transactions
imported_files 1──N transactions
```

---

## Enums

```sql
CREATE TYPE account_type AS ENUM ('checking', 'credit_card', 'savings');
CREATE TYPE category_type AS ENUM ('expense', 'income');
CREATE TYPE file_type AS ENUM ('csv', 'xlsx', 'xls', 'pdf');
CREATE TYPE transaction_status AS ENUM ('pending', 'reconciled', 'duplicate', 'ignored');
CREATE TYPE transaction_type AS ENUM ('income', 'expense');
```

---

## Regras de Integridade

1. `transactions.category_id` pode ser NULL (lançamento pendente)
2. `transactions.status = 'reconciled'` exige `category_id NOT NULL`
3. `imported_files.file_hash` é unique — re-importar o mesmo arquivo retorna 409
4. `transactions.tx_hash` é unique — garante idempotência na importação
5. Deletar uma `imported_file` NÃO deleta os lançamentos (SET NULL)

---

## tx_hash — Algoritmo

```python
import hashlib, unicodedata, re

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\W+", " ", s).upper().strip()
    return s

def make_tx_hash(account_id: str, date: str, description: str, amount: float) -> str:
    amount_cents = int(round(abs(amount) * 100))
    raw = f"{account_id}|{date}|{normalize(description)}|{amount_cents}"
    return hashlib.sha256(raw.encode()).hexdigest()
```
