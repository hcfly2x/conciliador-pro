# Architecture - HISTORICO

> Documento supersedido. Consulte `PROJECT_CONTEXT.md` e
> `docs/ARQUITETURA-WEB.md`. Nao use decisoes de autoclassificacao, importacao por
> pasta ou SQLite-only descritas abaixo como regras vigentes.

Data: 2026-05-08

## Visao Geral

O Conciliador Pro e um sistema financeiro pessoal para importar extratos bancarios e faturas de cartao, revisar visualmente todos os lancamentos antes de salvar e classificar cada lancamento com categoria, subcategoria, observacao e tags.

O principio central do produto e que lancamentos reais so entram no sistema por importacao de extratos ou cartoes. A base historica nao cria lancamentos reais. Ela alimenta apenas sugestoes de classificacao e probabilidades.

O fluxo de trabalho principal e:

1. O usuario cadastra ou usa contas/cartoes oficiais.
2. O usuario importa uma fatura ou extrato.
3. O backend detecta o tipo de arquivo, faz parsing, normaliza os lancamentos, identifica parcelas, flags/tags e duplicados.
4. A tela de pre-validacao mostra totais, duplicados internos, duplicados contra o banco, novos para inserir, warnings e sugestoes historicas.
5. O usuario confirma a importacao.
6. Os lancamentos entram em `transactions` como `pending`, com sugestoes e probabilidade preenchidas quando houver match na base historica.
7. O usuario classifica manualmente ou usa auto-classificacao acima de uma probabilidade minima.
8. Relatorios e filtros permitem analisar periodo, conta, categoria, subcategoria, tipo, status, parcelamento e tags.

O sistema tem duas interfaces:

- Frontend principal em Next.js, com layout completo, tabela, filtros, importacao, cofre de arquivos, base historica, categorias, contas e relatorios.
- UIs HTML alternativas servidas diretamente pelo Flask em `/ui/*`, mantidas porque o Next.js ja apresentou problemas de `spawn EPERM` no Windows.

## Stack

### Backend

- Linguagem: Python.
- Runtime local atual validado: Python 3.14.3 no venv `backend/.venv`.
- Framework HTTP: Flask 3.1.3.
- Banco: SQLite, arquivo `backend/data/conciliador_pro.db`.
- Leitura de Excel:
  - `openpyxl` 3.1.5 para `.xlsx`.
  - `xlrd` 2.0.2 para `.xls`.
- Leitura de PDF:
  - `pypdf` 6.10.2.
- Bibliotecas Flask instaladas no venv:
  - blinker 1.9.0
  - click 8.3.3
  - colorama 0.4.6
  - itsdangerous 2.2.0
  - Jinja2 3.1.6
  - MarkupSafe 3.0.3
  - Werkzeug 3.1.8

### Frontend

- Linguagem: TypeScript.
- Runtime Node atual do sistema: Node v24.14.0.
- npm atual do sistema: 11.9.0.
- Framework: Next.js 15.5.15.
- React: 19.1.0.
- React DOM: 19.1.0.
- Estado global: Zustand 5.0.13.
- Icones: lucide-react 1.14.0.
- Datas: date-fns 4.1.0.
- CSS:
  - Tailwind CSS 4.
  - `@tailwindcss/postcss`.
  - CSS global em `frontend/app/globals.css`.
- Utilitarios:
  - `clsx`.
  - `tailwind-merge`.

## Estrutura De Pastas

### Raiz

- `AGENTS.md`
  - Contexto operacional fixo do projeto para agentes.
  - Define pasta oficial, stack, regras de produto, regras de importacao/deduplicacao e cuidados.

- `Iniciar Conciliador.bat`
  - Iniciador Windows principal.
  - Prepara Python/venv se necessario, verifica `node_modules`, sobe backend em `5055`, tenta subir Next em `3010` e abre o app.
  - Se o Next falhar, abre a importacao alternativa servida pelo Flask.

- `Iniciar Importacao Alternativa.bat`
  - Iniciador simples que sobe o backend Flask em `5055` e abre `/ui/importar`.

- `CLEANUP_REPORT.md`
  - Relatorio da limpeza de codigo feita em 2026-05-08.

- `ARCHITECTURE.md`
  - Este documento.

### `backend/`

- `backend/app.py`
  - Aplicacao Flask principal.
  - Define schema SQLite, migrations leves, seed inicial, endpoints REST, endpoints de UI alternativa, importacao, classificacao, relatorios e cofre de arquivos.
  - Tambem contem alguns parsers legados usados em deteccao/scan.

- `backend/parsers/engine.py`
  - Motor principal de importacao.
  - Detecta formato, parseia CSV/XLS/XLSX/PDF, aplica enriquecimento, identifica parcelas, flags/tags, valida qualidade e retorna `ImportResult`.

- `backend/parsers/__init__.py`
  - Pacote Python para parsers.

- `backend/requirements.txt`
  - Dependencias Python minimas.

- `backend/run.bat`
  - Inicia `app.py` usando `backend/.venv/Scripts/python.exe`.

- `backend/.venv/`
  - Ambiente virtual Python local. Nao e parte logica da aplicacao.

- `backend/data/`
  - Dados locais persistidos.
  - `conciliador_pro.db`: SQLite principal.
  - `backups/`: backups manuais antes de resets/importacoes.
  - `uploads/`: arquivos temporarios recebidos por upload/previews/importacao de seed.
  - `documents/`: cofre de arquivos arquivados por ano/mes/conta.

### `frontend/`

- `frontend/app/`
  - Rotas App Router do Next.js.
  - `layout.tsx`: layout global com `Sidebar`, `Topbar`, `DataLoader` e `Toasts`.
  - `page.tsx`: lista principal de lancamentos.
  - `pendentes/page.tsx`: lista filtrada para pendentes, ordenada por probabilidade.
  - `importar/page.tsx`: importacao de extratos/faturas.
  - `arquivos/page.tsx`: cofre/controle mensal de arquivos.
  - `base-historica/page.tsx`: consulta da base historica.
  - `importar-historico/page.tsx`: importacao da base historica.
  - `categorias/page.tsx`: CRUD de categorias.
  - `contas/page.tsx`: CRUD de contas.
  - `relatorios/page.tsx`: relatorios.
  - `globals.css`: CSS global, fontes e Tailwind.

- `frontend/components/`
  - Componentes de UI por dominio:
    - `layout/`: `Sidebar`, `Topbar`, `DataLoader`.
    - `transactions/`: tabela principal.
    - `import/`: fluxo de importacao principal.
    - `categories/`: categorias e contas.
    - `reports/`: relatorios.
    - `ui/`: toasts.

- `frontend/lib/api.ts`
  - Cliente HTTP para todos os endpoints Flask.
  - Tambem contem modo mock opcional controlado por `NEXT_PUBLIC_USE_MOCK`.

- `frontend/lib/mock-data.ts`
  - Dados mock usados apenas se `NEXT_PUBLIC_USE_MOCK=true`.

- `frontend/lib/utils.ts`
  - Helpers compartilhados de classe CSS e formatacao.

- `frontend/store/app.ts`
  - Store global Zustand com contas, categorias, subcategorias, meses, toasts, refresh key e contador de pendentes.

- `frontend/types/index.ts`
  - Tipos TypeScript do dominio e respostas da API.

- `frontend/.env.local`
  - Deve conter `NEXT_PUBLIC_API_URL=http://127.0.0.1:5061/api/v1` para o fluxo Next normal descrito no AGENTS.
  - O iniciador alternativo usa backend em `5055` e proxy do `next.config.ts` para `/api/v1`.

### `tools/`

- `tools/import-preview/index.html`
  - UI alternativa para importacao/pre-validacao servida pelo Flask em `/ui/importar`.

- `tools/import-files/index.html`
  - UI alternativa/cofre de arquivos servida em `/ui/arquivos`.

- `tools/import-scan/index.html`
  - UI alternativa de varredura servida em `/ui/varredura`.

- `tools/node-v22.14.0-win-x64.zip`
  - Artefato mantido para diagnostico/recuperacao do problema Windows/Next/Node.

### `docs/`

Documentacao historica do projeto, incluindo contrato de API, banco, design system, contexto para outros agentes e tarefas backend. Parte dela pode estar defasada em relacao ao estado atual.

### `deliverables/`

Pacotes zip, revisoes e insumos usados para code review ou transferencia para outros agentes. Nao participa do runtime.

### `logs/`

Logs de tentativas de backend/frontend/npm. Nao participa do runtime, mas ajuda a diagnosticar falhas Windows/Next.

## Camadas Da Aplicacao

### UI Principal

A UI principal esta no Next.js.

- Rotas em `frontend/app`.
- Componentes reutilizaveis em `frontend/components`.
- Estado global em `frontend/store/app.ts`.
- Comunicacao com backend por `frontend/lib/api.ts`.

A tabela principal (`TransactionTable.tsx`) concentra a experiencia de classificacao:

- Carrega transacoes paginadas.
- Aplica filtros.
- Exibe totais calculados pelo backend.
- Permite classificar categoria/subcategoria/observacao inline.
- Permite editar tags.
- Mostra probabilidade historica e acao de auto-classificacao.
- Permite auto-classificar em lote por probabilidade minima.

### UI Alternativa

As UIs alternativas sao arquivos HTML em `tools/` e sao servidas pelo Flask. Elas existem para manter um caminho funcional quando o Next.js falha no Windows. Essas telas usam chamadas diretas aos endpoints Flask.

### API Backend

O backend Flask concentra:

- Schema e migrations.
- CRUD de contas, categorias e subcategorias.
- Importacao e pre-validacao.
- Confirmacao de importacao.
- Base historica.
- Motor de sugestao/probabilidade.
- Listagem e filtros de transacoes.
- Relatorios.
- Cofre de arquivos.

### Motor De Importacao

O motor moderno esta em `backend/parsers/engine.py`. Ele retorna objetos enriquecidos e nao grava diretamente no banco. A persistencia fica em `backend/app.py`.

### Persistencia

SQLite em arquivo local. Nao ha ORM. Todas as queries sao SQL direto via `sqlite3`.

## Modelos De Dados

### `accounts`

Contas e cartoes oficiais.

Campos:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL UNIQUE`
- `type TEXT NOT NULL`
  - Valores usados: `checking`, `credit_card`, possivelmente `savings`.
- `color TEXT NOT NULL`
- `is_active INTEGER NOT NULL DEFAULT 1`
- `created_at TEXT NOT NULL`

Relacoes:

- `transactions.account_id` aponta logicamente para `accounts.id`.
- `classification_history.account_id` pode apontar para `accounts.id`.
- `account_file_coverage.account_id` aponta logicamente para `accounts.id`.

Observacao: o SQLite nao declarou foreign keys formais no schema atual.

### `categories`

Categorias principais.

Campos:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL`
- `color TEXT NOT NULL`
- `text_color TEXT NOT NULL`
- `type TEXT NOT NULL`
  - `income` ou `expense`.

Relacoes:

- `transactions.category_id`.
- `transactions.suggested_category_id`.
- `classification_history.category_id`.

### `subcategories`

Subcategorias globais.

Campos:

- `id TEXT PRIMARY KEY`
- `name TEXT NOT NULL UNIQUE`

Relacoes:

- `transactions.subcategory_id`.
- `transactions.suggested_subcategory_id`.
- `classification_history.subcategory_id`.

### `transactions`

Lancamentos reais importados.

Campos:

- `id TEXT PRIMARY KEY`
- `tx_key TEXT NOT NULL UNIQUE`
  - Chave tecnica da transacao no banco.
- `date TEXT NOT NULL`
  - Data ISO `YYYY-MM-DD`.
- `competence_month TEXT NOT NULL`
  - Competencia `YYYY/MM`.
  - Pode ser diferente do mes da data do lancamento. Isso e esperado em faturas de cartao, onde compras de fevereiro/marco podem pertencer a fatura de abril.
  - Na importacao, a competencia pode ser sugerida pelo sistema e alterada pelo usuario antes do commit.
- `description TEXT NOT NULL`
- `description_norm TEXT NOT NULL`
  - Descricao normalizada para comparacao e busca.
- `amount REAL NOT NULL`
  - Valor assinado: receitas positivas, despesas negativas.
- `type TEXT NOT NULL`
  - `income` ou `expense`.
- `status TEXT NOT NULL`
  - Valores observados: `pending`, `reconciled`, `auto_classified`, `duplicate`, `ignored`.
- `account_id TEXT NOT NULL`
- `category_id TEXT`
- `subcategory_id TEXT`
- `notes TEXT NOT NULL DEFAULT ''`
- `suggested_category_id TEXT`
- `suggested_subcategory_id TEXT`
- `installment_current INTEGER`
  - Numero da parcela atual.
- `installment_total INTEGER`
  - Total de parcelas.
- `flags TEXT NOT NULL DEFAULT ''`
  - CSV de flags/tags.
- `match_probability REAL NOT NULL DEFAULT 0.0`
- `match_notes TEXT NOT NULL DEFAULT ''`
- `imported_file_id TEXT NOT NULL`

Indices:

- `idx_tx_desc_norm` em `description_norm`.
- `idx_tx_status` em `status`.
- Unique automatico em `id`.
- Unique automatico em `tx_key`.

### `classification_history`

Base historica usada para sugestao. Nao cria lancamentos reais.

Campos:

- `id TEXT PRIMARY KEY`
- `source_file_id TEXT NOT NULL`
- `account_id TEXT`
- `date TEXT`
- `description TEXT NOT NULL`
- `description_norm TEXT NOT NULL`
- `amount REAL NOT NULL`
- `type TEXT NOT NULL`
- `category_id TEXT NOT NULL`
- `subcategory_id TEXT`

Regra importante:

- A importacao historica atual preserva ocorrencias reais da planilha. Isso permite que frequencia influencie probabilidade.
- Linhas historicas sem categoria sao ignoradas.

Indice:

- `idx_hist_desc_norm` em `description_norm`.

### `imported_files`

Auditoria de arquivos importados.

Campos:

- `id TEXT PRIMARY KEY`
- `filename TEXT NOT NULL`
- `file_type TEXT NOT NULL`
- `file_hash TEXT NOT NULL`
- `source_path TEXT NOT NULL`
- `account_id TEXT NOT NULL`
- `account_name TEXT NOT NULL`
- `total_parsed INTEGER NOT NULL`
- `total_inserted INTEGER NOT NULL`
- `total_duplicates INTEGER NOT NULL`
- `total_errors INTEGER NOT NULL`
- `year TEXT NOT NULL DEFAULT ''`
- `month TEXT NOT NULL DEFAULT ''`
  - Ano e mes de controle do arquivo/cofre.
  - Quando o usuario informa `competence_month` no commit, estes campos seguem a competencia escolhida.
- `source_kind TEXT NOT NULL DEFAULT ''`
- `bank TEXT NOT NULL DEFAULT ''`
- `imported_at TEXT NOT NULL`

Uso:

- Historico de importacao.
- Controle do cofre.
- Evita/identifica arquivos ja importados por hash.

### `import_previews`

Previews temporarios antes da confirmacao final.

Campos:

- `id TEXT PRIMARY KEY`
- `filename TEXT NOT NULL`
- `temp_path TEXT NOT NULL`
- `account_id TEXT NOT NULL`
- `detected_type TEXT NOT NULL`
- `detection_confidence REAL NOT NULL`
- `created_at TEXT NOT NULL`

Uso:

- Criado por `/api/v1/import/preview`.
- Consumido por `/api/v1/import/commit`.
- Removido apos commit.

### `account_file_coverage`

Controle manual de cobertura de arquivos por conta/mes.

Campos:

- `id TEXT PRIMARY KEY`
- `account_id TEXT NOT NULL`
- `year_month TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'dispensed'`
- `reason TEXT NOT NULL DEFAULT ''`
- `created_at TEXT NOT NULL`
- Unique em `(account_id, year_month)`.

Uso:

- Permite marcar um mes como dispensado quando nao ha arquivo esperado.

## Fluxo De Importacao

### 1. Upload Para Preview

Frontend chama:

- `POST /api/v1/import/preview`

Payload:

- `multipart/form-data`
- `file`
- `account_id`

Backend:

1. Valida arquivo e conta.
2. Gera `preview_id`.
3. Salva arquivo temporario em `backend/data/uploads/preview-<id>-<filename>`.
4. Busca conta no banco.
5. Chama `build_import_preview(path, acc)`.

### 2. Parsing E Enriquecimento

`build_import_preview` chama o motor:

- `run_import_pipeline(path, account_name, account_type)`

No motor:

1. `detect_format(path, account_name)`
   - Detecta banco, tipo de documento, formato e encoding.
   - Tipos: CSV, XLSX, XLS, PDF.
   - Documentos: extrato corrente, fatura cartao, comprovante/generico.

2. Parser por formato:
   - CSV: `parse_csv`.
   - XLSX: `parse_xlsx`.
   - XLS: `parse_xls`.
   - PDF extrato: `parse_pdf_statement`.
   - PDF cartao: `parse_pdf_credit_card`.
   - Santander conta usa `_parse_santander_movement_statement` para ler o bloco de movimentacao, nao comprovantes.
   - Santander cartao usa o vencimento (`Vencimento DD/MM/YYYY`) como fonte preferencial para inferir ano/mes da fatura. Isso evita que um arquivo `04-25` seja arquivado como `04/2026` quando ha parcelas futuras ou datas ambigueas no PDF.

3. Enriquecimento:
   - Normaliza data.
   - Normaliza descricao.
   - Define valor assinado.
   - Define `type`.
   - Detecta parcelas por padroes como `Parcela 3 de 12`, `3/5`, etc.
   - Calcula `installment_current`, `installment_total`, `installment_label`, `is_installment`.
   - Detecta flags/tags automaticas.

4. Validacao:
   - Gera warnings para arquivos pequenos ou suspeitos.
   - Faz balance check quando o extrato fornece saldo inicial/final.

### 3. Competencia Sugerida E Override Manual

A competencia e o mes/ano operacional usado para agrupar importacao, cofre e relatorios. Ela nao substitui a data real do lancamento.

O backend calcula uma sugestao em `suggested_competence_month`:

1. Primeiro tenta inferir pelo nome do arquivo com padrao `MM-YY`, `MM_YY` ou `MM/YY`.
   - Exemplo: `Cartao - 04-25 - Santander - Comprovante.pdf` -> `2025/04`.
2. Para PDF de cartao, o parser tambem usa o vencimento da fatura quando presente.
   - Exemplo: `Vencimento 12/04/2025` -> `2025/04`.
3. Se nao houver informacao confiavel no nome/PDF, o sistema pode cair para as datas parseadas.

No frontend:

- A tela de importacao mostra um campo `Competencia` no preview.
- O Cofre de Arquivos preenche a competencia com a celula selecionada (`ano/mes`) e permite alterar antes de confirmar.
- O usuario pode corrigir a sugestao antes do commit. Isso e importante para faturas de cartao com compras em meses anteriores ou parcelas futuras.

No commit:

- `POST /api/v1/import/commit` aceita `competence_month` em formato `YYYY/MM`.
- `POST /api/v1/import/upload` tambem aceita `competence_month` em `multipart/form-data`.
- Se informado e valido, o valor controla:
  - `transactions.competence_month`;
  - `imported_files.year`;
  - `imported_files.month`;
  - destino fisico em `backend/data/documents/<ano>/<mes>/<conta>/`.
- A data real de cada lancamento continua vindo do arquivo parseado.

### 4. Tags Automaticas

As tags sao armazenadas em `transactions.flags` como CSV.

Regras atuais:

- `APLICACAO CDB/RDB`, `RESGATE CDB/RDB` -> `investimento`
- `IOF IMPOSTO OPERACOES`, `IOF ADICIONAL`, `TARIFA MENSALIDADE`, `DEBITO CONTRIBUICAO PREVIDENCIA` -> `tax`
- `REMUNERACAO APLICACAO AUTOMATICA` -> `rendimento`
- `PAGAMENTO CARTAO CREDITO BCE`, `DEBITO AUT. FATURA CARTAO VISA` -> `fatura`
- `DEBITO VISA ELECTRON BRASIL` -> `cartao_debito`

Compatibilidade:

- Flags antigas como `INTER_ACCOUNT`, `CARD_PAYMENT`, `TAX` e `CASHBACK` ainda sao lidas e exibidas.
- `INSTALLMENT` nao e exibida como tag, pois a parcela ja tem visual proprio.

### 5. Duplicacao Interna

O preview monta uma assinatura por linha parseada. Duplicados dentro do mesmo arquivo sao contados, mas podem ser legitimos e nao impedem importacao por padrao.

Regra de produto:

- Duplicado interno pode ser legitimo.
- Nao deve ser descartado automaticamente.

### 6. Duplicacao Contra Banco

A deduplicacao contra banco considera:

- `account_id`
- `date`
- `amount`
- `description_norm`
- `type`
- `installment_current`
- `installment_total`

Isso evita tratar parcelas diferentes da mesma compra como duplicadas. Uma compra parcelada com parcela `3/10` nao deve bloquear a parcela `4/10`.

No preview, o backend calcula quantas ocorrencias iguais ja existem no banco e marca as correspondentes como `duplicate_db`.

### 7. Sugestao Historica

Para cada linha parseada, o backend chama `best_history_match_for_tx`.

O algoritmo considera:

- Similaridade de descricao.
- Similaridade de valor.
- Similaridade de data/recorrencia.
- Similaridade de conta.
- Frequencia historica.
- Categoria/subcategoria historica.
- Observacoes historicas.

Resultado salvo/exibido:

- `match_probability`
- `match_category_id/name`
- `match_subcategory_id/name`
- `match_notes`

### 8. Resposta Do Preview

O endpoint retorna:

- `preview_id`
- `filename`
- `account_name`
- `detected_type`
- `detection_confidence`
- `total_parsed`
- `duplicates_db`
- `duplicates_internal`
- `new_records`
- `warnings`
- `balance_check`
- `import_meta`
- `rows`

`import_meta` inclui informacoes operacionais do arquivo, incluindo:

- `suggested_year`
- `suggested_month`
- `suggested_competence_month`
- `source_kind`
- `bank`

Cada linha de `rows` inclui:

- data
- descricao
- valor
- tipo
- parcela
- flags/tags
- duplicado interno
- duplicado no banco
- probabilidade e sugestao historica

### 9. Commit

Frontend chama:

- `POST /api/v1/import/commit`

Payload:

- `preview_id`
- `confirm_duplicates`
- `import_db_duplicates`
- `competence_month`

Backend:

1. Busca o preview em `import_previews`.
2. Reabre o arquivo temporario.
3. Chama `import_document`.
4. Reprocessa o arquivo com o mesmo motor.
5. Calcula duplicados no banco por ocorrencia.
6. Insere apenas novos quando `import_db_duplicates=false`.
7. Aplica `competence_month` quando enviado e valido.
8. Persiste o arquivo em `imported_files`.
9. Move/copia o documento para o cofre em `backend/data/documents`.
10. Remove o preview.

### 10. Persistencia Da Transacao

Cada lancamento salvo em `transactions` recebe:

- `id`
- `tx_key`
- data real do lancamento
- competencia operacional `YYYY/MM`
- descricao original e normalizada
- valor assinado
- tipo
- status `pending`
- conta
- sugestoes historicas
- parcela
- flags/tags
- arquivo importado

## Fluxo De Classificacao

### Classificacao Manual

Na tabela principal:

1. Usuario escolhe categoria.
2. Usuario escolhe subcategoria opcional.
3. Usuario edita observacao opcional.
4. Frontend chama `PATCH /api/v1/transactions/<id>/classify`.

Backend:

1. Valida `category_id`.
2. Atualiza `category_id`, `subcategory_id`, `notes`.
3. Define status:
   - `reconciled` para classificacao manual.
   - `auto_classified` se `classification_source='auto'`.
4. Se manual, grava/atualiza uma evidencia em `classification_history` com `source_file_id=manual:<transaction_id>`.

### Auto-Classificacao Por Linha

Se a transacao tem sugestao historica (`match_category_id`), a tabela mostra:

- categoria sugerida
- probabilidade
- observacao sugerida

Ao clicar em auto-classificar:

- Frontend chama o mesmo endpoint de classificacao com `classification_source='auto'`.
- Status vira `auto_classified`.

### Auto-Classificacao Em Lote

Na tabela existe controle de probabilidade minima.

Endpoint:

- `POST /api/v1/transactions/auto-classify`

Payload:

- `min_probability`
- `filters`

Backend:

1. Seleciona `pending`.
2. Exige `match_probability >= min_probability`.
3. Exige `suggested_category_id IS NOT NULL`.
4. Respeita filtros de tipo, conta, categoria sugerida, subcategoria sugerida, competencia, periodo, parcelamento, tags e busca.
5. Copia sugestoes para campos reais.
6. Preenche observacao com `match_notes` se a observacao estiver vazia.
7. Define status `auto_classified`.

### Tags

Tags automaticas entram na importacao.

Depois de importado:

- A tabela principal mostra badges.
- O usuario pode editar o CSV de tags por linha.
- Frontend chama `PATCH /api/v1/transactions/<id>/flags`.
- Backend sanitiza as tags:
  - normaliza acentos e caixa.
  - troca espacos por `_`.
  - remove caracteres fora de `[a-z0-9_]`.
  - remove duplicatas.

Tags nao substituem categoria ou subcategoria. Elas sao eixo ortogonal de filtro.

## Filtros E Relatorios

### Filtros De Transacoes

Endpoint:

- `GET /api/v1/transactions`

Filtros suportados:

- `page`
- `page_size`
- `status`
- `type`
- `account_id`
- `category_id`
- `subcategory_id`
- `is_installment`
- `competence_month`
- `date_from`
- `date_to`
- `tags`
- `tag_mode`
- `search`
- `sort_by`
- `sort_order`

### Filtro De Tags

`tags` e uma lista CSV.

Exemplos:

- `tags=investimento`
- `tags=tax,fatura`
- `tags=__empty__`

`tag_mode`:

- `include`: mostra transacoes que tenham qualquer uma das tags selecionadas.
- `exclude`: mostra transacoes que nao tenham as tags selecionadas.

Aliases preservados:

- `fatura` tambem casa com `CARD_PAYMENT`.
- `tax` tambem casa com `TAX`.
- `cashback` tambem casa com `CASHBACK`.
- `movimentacao_interna` tambem casa com `INTER_ACCOUNT`.

### Busca Textual

`search` compara contra:

- descricao normalizada
- nome da conta
- categoria
- subcategoria
- observacao
- data
- competencia
- valor textual
- status
- tipo

### Totais

A resposta de `/api/v1/transactions` inclui `summary` calculado com o mesmo `WHERE` dos filtros:

- `total_income`
- `total_expense`
- `balance`
- `pending_count`
- `reconciled_count`

Como os totais usam o mesmo filtro SQL, mudancas em periodo/categoria/tag afetam imediatamente os cards superiores.

### Relatorios

Endpoints:

- `GET /api/v1/reports/summary`
  - Totais gerais ou por competencia.

- `GET /api/v1/reports/by-category`
  - Agrupa por categoria.
  - Aceita `type` e `competence_month`.

- `GET /api/v1/reports/monthly`
  - Agrega por competencia.

## Persistencia E Migrations

O banco e SQLite em:

- `backend/data/conciliador_pro.db`

Nao ha Alembic nem sistema formal de migrations. A funcao `init_db()` em `backend/app.py` faz:

1. `CREATE TABLE IF NOT EXISTS` para todas as tabelas.
2. `CREATE INDEX IF NOT EXISTS`.
3. Verificacoes com `PRAGMA table_info`.
4. `ALTER TABLE ADD COLUMN` para colunas adicionadas em versoes posteriores.

Colunas adicionadas por migration leve:

- `classification_history.account_id`
- `transactions.installment_current`
- `transactions.installment_total`
- `transactions.flags`
- `transactions.match_probability`
- `transactions.match_notes`
- `imported_files.year`
- `imported_files.month`
- `imported_files.source_kind`
- `imported_files.bank`

Limite da abordagem:

- Nao ha rollback.
- Nao ha versionamento formal de schema.
- Alteracoes destrutivas exigem script manual e backup.

Backups manuais ficam em:

- `backend/data/backups/`

## Endpoints Principais

Saude/UI:

- `GET /api/v1/health`
- `GET /ui/importar`
- `GET /ui/varredura`
- `GET /ui/arquivos`

Cadastros:

- `GET, POST /api/v1/accounts`
- `PUT, DELETE /api/v1/accounts/<account_id>`
- `GET, POST /api/v1/categories`
- `PUT, DELETE /api/v1/categories/<cat_id>`
- `GET, POST /api/v1/subcategories`

Importacao:

- `POST /api/v1/import/upload`
  - Importacao direta sem preview completo.
  - Aceita `file`, `account_id`, `confirm_duplicates`, `import_db_duplicates` e `competence_month`.
- `POST /api/v1/import/preview`
  - Cria preview temporario e retorna `import_meta.suggested_competence_month`.
- `POST /api/v1/import/commit`
  - Confirma preview.
  - Aceita `preview_id`, controles de duplicados e `competence_month`.
- `GET /api/v1/import/history`
- `POST /api/v1/import/scan-folder`
- `POST /api/v1/import/seed`

Cofre/cobertura:

- `GET /api/v1/coverage`
- `POST, DELETE /api/v1/coverage/dispense`
- `GET /api/v1/coverage/files`
- `DELETE /api/v1/coverage/files`

Transacoes:

- `GET /api/v1/transactions`
- `PATCH /api/v1/transactions/<tx_id>/classify`
- `PATCH /api/v1/transactions/<tx_id>/flags`
- `GET /api/v1/transactions/<tx_id>/suggestions`
- `POST /api/v1/transactions/recalculate-probabilities`
- `POST /api/v1/transactions/auto-classify`
- `PATCH /api/v1/transactions/bulk-classify`
- `GET /api/v1/transactions/months`

Base historica:

- `GET /api/v1/history`
- `POST /api/v1/import/seed`

Relatorios:

- `GET /api/v1/reports/summary`
- `GET /api/v1/reports/by-category`
- `GET /api/v1/reports/monthly`

Sistema:

- `POST /api/v1/system/reset`

## Pontos De Extensao

### Adicionar Novo Banco Ou Tipo De Arquivo

Arquivo principal:

- `backend/parsers/engine.py`

Pontos:

1. Atualizar `detect_format`.
   - Identificar banco, formato e tipo de documento.

2. Criar parser especifico se necessario.
   - Para PDF conta: funcao estilo `_parse_santander_movement_statement`.
   - Para PDF cartao: expandir `parse_pdf_credit_card`.
   - Para CSV/XLS/XLSX: adaptar `parse_csv` ou `_parse_tabular_rows`.

3. Garantir que o parser retorne `RawTx`.

4. Ajustar inferencia de competencia quando o novo formato tiver uma fonte melhor que nome do arquivo.
   - Faturas normalmente devem preferir vencimento/fechamento.
   - Extratos de conta normalmente devem preferir periodo do extrato ou nome do arquivo.

5. Validar no `run_import_pipeline`.

6. Adicionar warnings especificos, se fizer sentido.

7. Testar:
   - total lido.
   - saldo, se houver.
   - parcelas.
   - tags.
   - duplicados.
   - competencia sugerida.
   - override manual de competencia no commit.

### Adicionar Nova Tag Automatica

Arquivo:

- `backend/parsers/engine.py`

Passos:

1. Adicionar marcador em constantes como `TAX_MARKERS`, `CARD_PAYMENT_MARKERS` ou criar nova constante.
2. Atualizar `detect_transaction_flags`.
3. Se a tag precisar aparecer nos filtros principais, atualizar:
   - `TAG_FILTER_ALIASES` em `backend/app.py`.
   - `TAG_OPTIONS` em `frontend/components/transactions/TransactionTable.tsx`.
   - mapeamento de exibicao em `flagLabels`.
4. Testar preview e commit.

### Adicionar Novo Campo Em Transacoes

Passos:

1. Alterar `CREATE TABLE IF NOT EXISTS transactions` em `init_db`.
2. Adicionar bloco de migration com `PRAGMA table_info` e `ALTER TABLE ADD COLUMN`.
3. Atualizar inserts em `import_document`.
4. Atualizar select de `/api/v1/transactions`.
5. Atualizar tipos em `frontend/types/index.ts`.
6. Atualizar UI se necessario.

### Adicionar Novo Relatorio

Passos:

1. Criar endpoint em `backend/app.py`.
2. Escrever SQL agregando em `transactions`.
3. Adicionar funcao em `frontend/lib/api.ts`.
4. Criar ou atualizar componente em `frontend/components/reports`.
5. Atualizar tipos em `frontend/types/index.ts`.

### Adicionar Nova Tela

Passos:

1. Criar rota em `frontend/app/<rota>/page.tsx`.
2. Criar componente em `frontend/components/<dominio>`.
3. Adicionar link no `nav` de `Sidebar.tsx`.
4. Adicionar titulo em `Topbar.tsx`.
5. Criar chamadas em `frontend/lib/api.ts`, se necessario.

## Limitacoes Conhecidas E Dividas Tecnicas

### Duplicacao Entre Parsers

Ha parsers no motor novo (`backend/parsers/engine.py`) e parsers legados em `backend/app.py`. Isso aumenta risco de comportamento divergente. A direcao recomendada e mover toda deteccao/parsing para o pacote `backend/parsers`.

### Endpoint De Scan Tem Uso Suspeito De Deduplicacao

`import_scan_folder` chama `existing_db_duplicate_count(conn, acc[0], parsed_rows)` com uma lista, mas a funcao ativa espera uma unica linha. Isso parece bug latente na varredura. Nao foi corrigido na limpeza para nao misturar cleanup com alteracao funcional.

### Migrations Sem Versionamento

`init_db()` faz migrations leves. Funciona para evolucao simples, mas nao documenta versoes nem suporta rollback.

### Tags Em CSV

Tags ficam em `transactions.flags` como string CSV. Isso e simples e compativel com a entrega atual, mas limita consultas mais sofisticadas. Se tags crescerem em complexidade, uma tabela relacional `transaction_tags` sera melhor.

### Foreign Keys Nao Declaradas

As relacoes existem por convencao, nao por constraints SQLite. Isso permite inconsistencias se registros forem apagados manualmente.

### Encoding Em Comentarios Legados

Os textos visiveis do frontend foram revisados para evitar mojibake. Ainda ha comentarios antigos com encoding quebrado em arquivos legados do backend, sem impacto funcional ou visual.

### Tailwind Config Duplicado

Existem `tailwind.config.ts` e `tailwind.config.js`. O build passa, mas a configuracao deve ser consolidada.

### Next.js No Windows

O ambiente Windows ja apresentou `spawn EPERM` ao subir Next.js. Por isso existem:

- iniciador com fallback.
- UI alternativa Flask.
- historico de runtime Node portatil.

### Cofre De Arquivos Ainda E Operacionalmente Sensivel

O cofre usa arquivos fisicos em `backend/data/documents`. Remover arquivos pode remover rastreabilidade e, dependendo do endpoint usado, tambem apagar importacoes associadas.

### Competencia E Uma Decisao Do Commit

O preview sugere competencia, mas o valor definitivo pode ser alterado pelo usuario na confirmacao. Essa decisao nao fica versionada como um campo proprio em `import_previews`; ela e enviada no commit e persistida em `transactions.competence_month`, `imported_files.year/month` e no caminho fisico do cofre. Para auditoria mais forte no futuro, vale registrar a competencia sugerida e a competencia escolhida separadamente.

Mudancas de parser ou de regra de competencia nao rebucketizam importacoes antigas automaticamente. Se um arquivo foi importado com competencia errada, o caminho correto e remover/reimportar ou criar uma rotina de manutencao controlada.

### Base Historica Nao E Imutavel

A base historica pode receber imports de planilha e entradas manuais via classificacao. Isso e bom para aprendizado, mas exige cuidado antes de limpar `classification_history`.

### Testes Automatizados Ausentes

Nao ha suite formal de testes no projeto. Validacao atual depende de:

- `py_compile`.
- `npm run build`.
- testes manuais de importacao.
- chamadas pontuais a endpoints com Flask test client.

Recomendacao:

- Criar fixtures para PDFs/CSVs conhecidos.
- Testar parser Santander conta, Santander cartao, XP cartao e planilhas.
- Testar deduplicacao com parcelas.
- Testar tags automaticas.
- Testar preview/commit sem gravar duplicados no banco.
