# Arquitetura web - Conciliador Pro

Atualizado em 22/07/2026. Para regras de produto, consulte `PROJECT_CONTEXT.md`.

## Topologia

```text
Next.js 15 / Vercel
        | HTTPS + Bearer token
        v
Flask / Gunicorn / Render ------ Flask worker separado
        |                              |
        +---------- PostgreSQL --------+
                    |
             filas persistentes
```

Sem `DATABASE_URL`, backend e worker usam SQLite para desenvolvimento/testes. O
frontend usa proxy local para `http://127.0.0.1:5061` quando
`NEXT_PUBLIC_API_URL` nao esta definida.

## Backend

- `backend/app.py`: fachada compativel com Flask/Gunicorn e imports legados.
- `backend/core/application.py`: nucleo compartilhado ainda em separacao.
- `backend/blueprints/`: 51 dos 64 handlers por dominio. Auth, auditoria, sistema,
  health/reset, relatorios, contas/razoes/categorias, cobertura/cofre e
  conciliacoes e sugestoes possuem implementacao propria. Leitura, confirmacao
  individual/em lote, rejeicao, desvinculo e recalculo historico tambem estao no
  dominio de vinculos. Os 13 handlers de importacao e transacoes continuam no
  nucleo.
- `backend/parsers/engine.py`: parsing e validacao financeira.
- `backend/db.py`: compatibilidade SQLite/PostgreSQL e pool.
- `backend/auth.py`: usuarios, sessoes, rate limit e auditoria.
- `backend/migrations/`: migrations imutaveis com versao/checksum.
- `backend/worker.py`: consumidor persistente de importacoes, base historica,
  sugestoes e recalculo.

O boot aplica o bootstrap idempotente legado e, em seguida, migrations
versionadas. Novas alteracoes de schema devem ser migrations; nao devem ser
adicionadas apenas como `ALTER TABLE` solto no nucleo.

## Jobs

A arquitetura alvo usa `WORKER_MODE=process` e um processo com
`WORKER_PROCESS=1`: o web apenas enfileira e o worker reivindica atomicamente um
job `queued`, muda para `claimed` e executa. A producao atual possui somente o
web service do Render e, por isso, usa `WORKER_MODE=inline`. Em PostgreSQL, um
advisory lock exclusivo impede dois workers de recuperar ou consumir a fila
durante a sobreposicao de processos em um deploy. Somente o worker que obtem
esse lease recupera jobs interrompidos; o web nunca os refila.

SQLite local usa `WORKER_MODE=inline` por padrao. Um teste multi-processo valida
a persistencia da fila e reinicio do web; o CI repete o cenario em PostgreSQL 16.

## Autenticacao e autorizacao

- Senhas PBKDF2-SHA256.
- Token Bearer armazenado como digest no banco e em `sessionStorage` no browser.
- Sessao de 30 dias, renovada somente perto da expiracao.
- `admin`: todas as operacoes.
- `colaborador`: leitura e apenas escritas explicitamente marcadas.
- Escrita e negada por padrao; nao existe permissao inferida por sufixo de URL.

## Observabilidade

- Request log: metodo, path, status, duracao e usuario, sem payload.
- JSON no PostgreSQL/hosted; formato legivel localmente.
- Sentry backend/frontend opcional, desligado quando o DSN esta ausente.
- Jobs longos persistem fase, progresso, mensagem e logs recentes.

## Persistencia de documentos

Documentos sao persistidos em Base64 em `stored_documents`, com fallback local.
Essa escolha permanece ate a tabela se aproximar de 200 MB. Nesse gatilho,
avaliar `bytea` ou object storage. Nao migrar antes da medicao.

## Dividas conhecidas

- Terminar a separacao dos dominios grandes do nucleo.
- Ativar e homologar o worker separado no Render; a fila ja foi homologada com
  web e worker separados no CI/PostgreSQL.
- Avaliar `NUMERIC` e foreign keys depois de auditoria dos dados.
- Remover compatibilidade de token legado apos 30 dias.
