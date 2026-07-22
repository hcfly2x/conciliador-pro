# Matriz de variaveis de ambiente

Atualizado em 22/07/2026. Segredos nunca devem ser adicionados ao repositorio.

## Backend web e worker

| Variavel | Obrigatoria | Padrao | Uso |
|---|---|---|---|
| `DATABASE_URL` | producao/staging | SQLite local | PostgreSQL compartilhado pelo web e worker |
| `ADMIN_USERNAME` | primeiro deploy | vazio | cria o primeiro administrador se nao houver usuarios |
| `ADMIN_PASSWORD` | primeiro deploy | vazio | senha inicial, minimo de 8 caracteres |
| `CORS_ORIGINS` | PostgreSQL hosted | nenhum | origens permitidas, separadas por virgula; `*` e recusado |
| `WORKER_MODE` | hosted | `process` em PostgreSQL, `inline` em SQLite | separa filas do processo web |
| `WORKER_PROCESS` | worker | vazio | identifica inicializacao do processo worker |
| `WORKER_POLL_SECONDS` | nao | `1` | intervalo de polling do worker |
| `WORKER_RUN_ONCE` | somente teste | falso | processa no maximo um job e encerra |
| `TRUSTED_PROXY_COUNT` | hosted | `1` em PostgreSQL | quantidade de proxies confiaveis para IP real |
| `DB_POOL_MAX` | nao | `10` | tamanho maximo do pool PostgreSQL por processo |
| `DB_POOL_FALLBACKS_PER_MINUTE` | nao | `5` | limite de conexoes diretas quando o pool falha |
| `MAX_UPLOAD_MB` | nao | `30` | limite Flask para uploads |
| `SESSION_DAYS` | nao | `30` | validade da sessao |
| `LOGIN_MAX_ATTEMPTS` | nao | `5` | tentativas antes do bloqueio temporario |
| `LOGIN_BLOCK_MINUTES` | nao | `15` | duracao do bloqueio de login |
| `AUTH_DISABLED` | somente dev/teste | falso | desativa autenticacao; proibido em producao |
| `CONCILIADOR_DATA_DIR` | dev/teste | `backend/data` | isola SQLite, uploads, documentos e backups |
| `SENTRY_DSN` | nao | vazio | ativa Sentry backend |
| `SENTRY_ENVIRONMENT` | nao | ambiente inferido | nome do ambiente Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | nao | `0` | amostragem de traces |
| `LOG_LEVEL` | nao | `INFO` | nivel do worker |
| `HOST` / `PORT` | nao | `127.0.0.1:5061` | servidor Flask direto; Render fornece `PORT` |
| `RENDER_GIT_COMMIT` | Render | vazio | commit exposto de forma abreviada no health |

## Frontend

| Variavel | Obrigatoria | Padrao | Uso |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | Vercel | `/api/v1` | URL publica do backend |
| `API_PROXY_TARGET` | dev/E2E | `http://127.0.0.1:5061` | destino do rewrite local |
| `NEXT_PUBLIC_AUTH_DISABLED` | somente dev | falso | acompanha `AUTH_DISABLED` local |
| `NEXT_PUBLIC_USE_MOCK` | somente dev | falso | dados simulados do frontend |
| `NEXT_PUBLIC_SENTRY_DSN` | nao | vazio | Sentry no navegador |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | nao | `NODE_ENV` | ambiente dos eventos do navegador |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | nao | `0` | amostragem de traces do navegador |
| `SENTRY_DSN` | nao | vazio | Sentry no runtime servidor/edge |
| `SENTRY_ENVIRONMENT` | nao | `NODE_ENV` | ambiente servidor/edge |
| `SENTRY_TRACES_SAMPLE_RATE` | nao | `0` | amostragem servidor/edge |
| `SENTRY_ORG`, `SENTRY_PROJECT`, `SENTRY_AUTH_TOKEN` | source maps | vazio | upload de source maps durante build |

## Configuracao minima recomendada

- Render web: `DATABASE_URL`, `CORS_ORIGINS`, `WORKER_MODE=process`,
  `TRUSTED_PROXY_COUNT=1` e os DSNs opcionais.
- Render worker: mesma `DATABASE_URL`, `WORKER_MODE=process` e
  `WORKER_PROCESS=1`.
- Vercel: `NEXT_PUBLIC_API_URL` e, se habilitado, Sentry.
- Credenciais administrativas iniciais devem ser removidas ou rotacionadas
  depois de confirmar o primeiro usuario.
