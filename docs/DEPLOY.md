# Deploy - Conciliador Pro Web

Guia passo a passo para colocar o sistema no ar com banco hosted, sem depender da sua maquina. Ambiente vigente: **Supabase** (PostgreSQL) + **Render** (backend Flask e worker) + **Vercel** (frontend Next.js).

## 1. Banco de dados hosted (Supabase)

1. Crie o projeto e selecione a regiao mais proxima disponivel.
2. Copie a connection string PostgreSQL compativel com o ambiente Render.
3. Nao crie tabelas manualmente: o backend aplica o bootstrap compativel e as
   migrations versionadas na inicializacao.

Neon e Railway sao alternativas equivalentes. Em qualquer provedor, o contrato
da aplicacao e uma `DATABASE_URL` PostgreSQL acessivel pelo web e pelo worker.

## 2. Backend (Render)

1. Suba o projeto para um repositorio GitHub (privado).
2. Em https://render.com, crie um **Web Service** apontando para o repositorio.
3. Configure:
   - Root Directory: `backend`
   - Runtime: Python
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn -b 0.0.0.0:$PORT -w 2 --threads 8 --timeout 300 app:app`
4. Em Environment, adicione:
   - `DATABASE_URL` = connection string do Neon
   - `ADMIN_USERNAME` = seu usuario (ex.: `helcio`)
   - `ADMIN_PASSWORD` = uma senha forte (minimo 8 caracteres)
   - `CORS_ORIGINS` = URL do frontend na Vercel (pode preencher depois do passo 3 e salvar de novo)
   - `WORKER_MODE` = `process`
   - `TRUSTED_PROXY_COUNT` = `1` no Render/Railway
   - `DB_POOL_FALLBACKS_PER_MINUTE` = `5` (limite de conexoes diretas quando o pool falha)
   - `SENTRY_DSN` = DSN do projeto backend (opcional; sem valor, fica desligado)
6. Crie tambem um **Background Worker** com o mesmo root/build e comando
   `WORKER_MODE=process WORKER_PROCESS=1 python worker.py`. Ele consome as filas
   persistidas de importacao, sugestoes e recalculo sem competir com requests web.
7. Deploy. Teste: `https://SEU-SERVICO.onrender.com/api/v1/health` deve responder `{"status": "ok"}`.

O admin e criado automaticamente na primeira subida (somente se ainda nao existir nenhum usuario; depois disso as variaveis ADMIN_* podem ate ser removidas).

Observacao sobre o plano gratuito do Render: o servico hiberna apos inatividade e a primeira requisicao do dia demora ~30-60s. Para uso diario confortavel, o plano Starter resolve.

## 3. Frontend (Vercel)

1. Em https://vercel.com, importe o mesmo repositorio.
2. Configure:
   - Root Directory: `frontend`
   - Framework: Next.js (detectado automaticamente)
3. Em Environment Variables:
   - `NEXT_PUBLIC_API_URL` = `https://SEU-SERVICO.onrender.com/api/v1`
   - `NEXT_PUBLIC_SENTRY_DSN` = DSN do projeto frontend (opcional)
   - `SENTRY_ORG`, `SENTRY_PROJECT` e `SENTRY_AUTH_TOKEN` = apenas se quiser upload de source maps
4. Deploy. Copie a URL final (ex.: `https://conciliador-pro.vercel.app`) e coloque-a no `CORS_ORIGINS` do backend no Render (redeploy automatico).

## 4. Criar o usuario da funcionaria

Entre no app com o admin e crie a colaboradora pela API (ou peca para eu adicionar uma tela de usuarios depois):

```bash
# 1. login (pegue o token da resposta)
curl -X POST https://SEU-SERVICO.onrender.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"helcio","password":"SUA_SENHA"}'

# 2. criar colaboradora
curl -X POST https://SEU-SERVICO.onrender.com/api/v1/auth/users \
  -H "Authorization: Bearer TOKEN_AQUI" \
  -H "Content-Type: application/json" \
  -d '{"username":"funcionaria","password":"senha-dela-8+","role":"colaborador"}'
```

O que cada perfil pode fazer:
- **admin**: tudo - importar, classificar, desbloquear, gerenciar contas/categorias/razoes/usuarios, limpar/resetar.
- **colaborador**: visualizar tudo e classificar (individual, em lote, flags, vincular com historico). Nao importa, nao desbloqueia, nao apaga.

## 5. Backups

- Supabase: configure e verifique a politica de backup/restore do plano contratado.
- Antes de qualquer "Resetar sistema" no modo hosted, crie um backup/branch; o
  app nao gera arquivo `.db` quando utiliza PostgreSQL.
- Os documentos originais sao persistidos na tabela `stored_documents` junto ao
  lote financeiro. A copia no disco do Render e secundaria e pode desaparecer
  entre deploys. Mantenha tambem uma copia externa como contingencia operacional.

## 6. Desenvolvimento local (opcional)

Sem `DATABASE_URL` o backend volta a usar o SQLite local:

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
AUTH_DISABLED=1 .venv/Scripts/python app.py                              # roda em http://127.0.0.1:5061

cd ../frontend
npm install
# .env.local: use API_PROXY_TARGET=http://127.0.0.1:5061 e NEXT_PUBLIC_AUTH_DISABLED=true
# NEXT_PUBLIC_API_URL pode ficar ausente localmente; o proxy do Next encaminha /api/v1.
npm run dev
```

Tambem e possivel apontar o backend local para um PostgreSQL de staging
exportando `DATABASE_URL`; nunca use o banco de producao para testes destrutivos.

O CI possui o job `backend-postgres`, que cria PostgreSQL 16 descartavel, aplica
as migrations e testa web/worker em processos separados com reinicio do web. Esse
teste deve passar antes de implantar a revisao.

## 7. Checklist final

1. `GET /api/v1/health` responde ok.
2. Login com admin funciona no frontend.
3. Colaboradora consegue logar, ver lancamentos e classificar; recebe "apenas administrador" ao tentar importar.
4. Classificar um lancamento e tentar mudar de novo mostra o cadeado; Desbloquear (admin) libera e registra na auditoria (`GET /api/v1/audit?entity_id=...`).
5. Importacao completa: upload -> preview com totais/duplicados -> confirmar -> lancamentos aparecem como pendentes.
6. O Background Worker esta ativo e os jobs deixam `queued` para `completed`.
7. Um erro controlado aparece no projeto Sentry correto, sem dados financeiros no payload.
