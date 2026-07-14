# Arquitetura Web - Conciliador Pro

Data: 2026-07-13

## Visao geral

A versao web mantem o codigo e as regras de produto que ja funcionavam localmente e troca apenas o que prendia o sistema a uma maquina: o banco passa a ser Postgres hosted, o backend Flask roda em um servico web, o frontend Next.js roda na Vercel, e o acesso passa a exigir login com dois perfis.

```
[Navegador - voce e a funcionaria]
        |
        v
[Frontend Next.js - Vercel]          NEXT_PUBLIC_API_URL
        |
        v  (HTTPS + Bearer token)
[Backend Flask + Gunicorn - Render/Railway]
        |
        v  DATABASE_URL
[Postgres hosted - Neon / Supabase / Railway]
```

## Decisoes

1. **Manter Flask + Next.js.** O backend de ~4000 linhas contem os parsers de extrato/fatura, a deduplicacao e as regras de produto ja validadas. Reescrever seria risco sem beneficio. A adaptacao foi feita por uma camada de banco (`backend/db.py`) e um modulo de autenticacao (`backend/auth.py`).
2. **Postgres hosted em vez de SQLite.** `backend/db.py` detecta `DATABASE_URL`: se presente, usa Postgres (psycopg3) com um adaptador que traduz o SQL no dialeto do sqlite (`?` -> `%s`, `IFNULL` -> `COALESCE`, `PRAGMA table_info` -> `information_schema`, `REAL` -> `DOUBLE PRECISION` em DDL). Sem `DATABASE_URL`, continua usando o SQLite local para desenvolvimento. O schema e as migracoes rodam automaticamente na subida do app.
3. **Autenticacao simples com sessao por token.** Login com usuario/senha (PBKDF2-SHA256), token Bearer com validade de 30 dias, guardado no navegador. Sem dependencias externas de auth.
4. **Dois perfis.** `admin` faz tudo: importar, classificar, desbloquear, gerenciar contas/categorias/razoes/usuarios e acoes destrutivas. `colaborador` le tudo e pode classificar (`classify`, `bulk-classify`, `flags`, `bulk-vincular`); qualquer outra escrita retorna 403. A regra fica no `before_request` do backend, entao vale mesmo que a UI seja contornada.

## Regras de produto preservadas

- Lancamentos reais nascem apenas de extratos/faturas importados; a base historica alimenta somente sugestoes de categoria/subcategoria.
- Cartao de credito e saida por padrao; receita em cartao apenas para estorno, reembolso, cashback, credito ou devolucao.
- Importacao continua com preview + validacao visual (total lido, duplicados internos, duplicados no banco, novos, warnings) antes do commit.
- Duplicados internos do mesmo arquivo continuam permitidos; duplicados contra o banco continuam bloqueados por padrao.

## Protecao pos-classificacao (novo)

- Ao salvar categoria/subcategoria/observacao, o lancamento recebe `locked=1`, `classified_by` e `classified_at`.
- Qualquer nova tentativa de classificar um lancamento travado retorna **423 TX_LOCKED**; a UI desabilita os campos e mostra o cadeado.
- Para alterar, o admin usa o botao **Desbloquear** (endpoint `POST /transactions/<id>/unlock`), que registra auditoria com motivo; depois disso a edicao e permitida e trava novamente ao salvar.
- Lancamentos travados ficam fora de `bulk-classify` (contados em `skipped_locked`), de `bulk-vincular` e de "Limpar classificacoes". `recalculate-probabilities` so mexe em campos de sugestao, nunca em classificacao.

## Auditoria (novo)

Tabela `audit_log` com usuario, acao, entidade, campo, valor anterior, valor novo, detalhe e data/hora. Registrada em: login, classify (por campo alterado), bulk-classify, unlock, flags, criacao/alteracao de usuarios e reset do sistema. Consulta via `GET /api/v1/audit?entity_id=<tx_id>`.

## Novas tabelas e colunas

- `users(id, username, password_hash, role, is_active, created_at)`
- `sessions(token, user_id, created_at, expires_at)`
- `audit_log(id, user_id, username, action, entity, entity_id, field, old_value, new_value, detail, created_at)`
- `transactions` ganha `locked`, `classified_by`, `classified_at`

## Novos endpoints

- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- `GET|POST /api/v1/auth/users`, `PATCH /api/v1/auth/users/<id>` (admin)
- `POST /api/v1/transactions/<id>/unlock` (admin)
- `GET /api/v1/audit`

## Variaveis de ambiente do backend

- `DATABASE_URL` - string do Postgres hosted (ex.: `postgresql://user:senha@host/db?sslmode=require`). Sem ela, usa SQLite local.
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` - criam o primeiro admin quando o banco ainda nao tem usuarios.
- `CORS_ORIGINS` - lista separada por virgula com as origens do frontend (ex.: `https://conciliador.vercel.app`). Padrao `*` (restrinja em producao).
- `AUTH_DISABLED=1` - apenas para desenvolvimento local sem login.
- `PORT` / `HOST` - porta e host do servidor (Render define `PORT` automaticamente).
- `SESSION_DAYS` - validade da sessao (padrao 30).

## Variaveis de ambiente do frontend

- `NEXT_PUBLIC_API_URL` - URL da API, ex.: `https://conciliador-api.onrender.com/api/v1`.
- `NEXT_PUBLIC_AUTH_DISABLED=true` - apenas dev local sem login.

## Limitacoes conhecidas

1. **Arquivos originais em disco sao efemeros no hosting.** Os lancamentos, previews e metadados de importacao ficam no Postgres e persistem. As copias fisicas dos extratos (pasta `data/documents`, tela Arquivos) ficam no disco do servico e somem em cada redeploy, a menos que se contrate um disco persistente (Render Disk / Railway Volume). Recomendado: manter os originais tambem no Google Drive.
2. **Preview -> commit depende do mesmo processo.** Se o backend reiniciar entre o preview e a confirmacao, o app responde `PREVIEW_FILE_MISSING` e basta reenviar o arquivo. Use 1 instancia (padrao dos planos basicos).
3. **Paginas `/ui/*` legadas** (ferramentas locais) ficam indisponiveis no modo hosted; as telas do Next.js as substituem.
4. **Reset do sistema no modo hosted** nao gera arquivo de backup local; faca backup/branch pelo provedor Postgres antes (Neon tem branch com um clique).
