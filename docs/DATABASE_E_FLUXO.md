# Estrutura de Banco e Fluxo de Código

## 1) Banco local (SQLite)
Arquivo: `backend/data/conciliador_pro.db`

Tabelas principais:
- `accounts`
  - cadastro de contas/cartões (ex.: CONTA SANTANDER, CARTAO SANTANDER, CONTA XP, CARTAO XP)
- `categories`
  - categorias de centro de custo por tipo (`income` / `expense`)
- `subcategories`
  - subcategorias globais
- `transactions`
  - lançamentos importados de extratos/faturas (fonte oficial do app)
  - campos críticos:
    - `tx_key` (chave técnica única por ocorrência)
    - `date`, `description`, `description_norm`, `amount`, `type`, `status`
    - `account_id`, `category_id`, `subcategory_id`, `notes`
    - `imported_file_id`
- `classification_history`
  - base histórica de classificação (não cria lançamento financeiro)
  - usada para sugestão de categoria/subcategoria e probabilidades
- `imported_files`
  - trilha de importações
  - guarda contagens (`total_parsed`, `total_inserted`, `total_duplicates`, etc.)

## 2) Regras de Importação (estado atual)

### 2.1 Conta/Cartão obrigatório
- Endpoint `POST /api/v1/import/upload` exige `account_id`.
- O backend não tenta mais adivinhar conta por nome/conteúdo.

### 2.2 Duplicidade separada (regra chave)
- `duplicates_db_found`:
  - itens já existentes no banco.
  - nunca são reinseridos.
- `duplicates_internal_found`:
  - duplicidade dentro do mesmo arquivo importado.
  - pode ser legítima e é permitida.

### 2.3 Cartão de crédito
- Regra padrão: `expense`.
- Vira `income` apenas em casos de crédito/abatimento/reembolso (ex.: estorno, cashback, devolução).

### 2.4 Santander PDF
- `CONTA SANTANDER` (extrato): parser ignora lançamentos espelhados de comprovantes finais.
- `CARTAO SANTANDER` (fatura PDF): possui parser dedicado de detalhamento, com bloqueio de PDF sem detalhamento suficiente.
- Para cartão Santander, CSV continua sendo a fonte preferencial quando disponível.

### 2.5 Alerta de extrato curto
- Quando importação de conta (não cartão) vem com menos de 15 lançamentos, resposta inclui `warnings`.

## 3) Fluxo de classificação

### 3.1 Fluxo manual
- usuário importa arquivo -> lançamentos entram `pending`.
- edição inline em categoria/subcategoria/obs salva no backend e muda status para `reconciled`.

### 3.2 Sugestões por probabilidade
Baseadas em `classification_history`, com 4 sinais sempre combinados:
- data
- descrição aproximada
- valor
- conta

Exposição de probabilidades:
- célula categoria: `% categoria`
- célula subcategoria: `% subcategoria`
- coluna final: `% match perfeito do lançamento` (gatilho de auto classificar)

Filtros atuais:
- sugestões com aderência < 20% não são exibidas.
- auto classificar habilitado para match perfeito >= 70%.

## 4) Endpoints principais
- `GET /api/v1/health`
- `POST /api/v1/import/upload`
- `POST /api/v1/import/seed`
- `GET /api/v1/import/history`
- `GET /api/v1/transactions`
- `PATCH /api/v1/transactions/<id>/classify`
- `GET /api/v1/transactions/<id>/suggestions`
- `PATCH /api/v1/transactions/bulk-classify`
- `GET /api/v1/reports/*`

## 5) Frontend (Next.js)
- página de importação: `frontend/components/import/ImportPage.tsx`
- grid principal: `frontend/components/transactions/TransactionTable.tsx`
- cliente API: `frontend/lib/api.ts`

## 6) Ponto de atenção técnico
- ambiente Python local pode ter variação de interpretador/site-packages.
- se backend não subir por dependência, validar `py -m pip install -r backend/requirements.txt` no mesmo Python do `py app.py`.
