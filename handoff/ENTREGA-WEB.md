# Entrega - Conciliador Pro Web (2026-07-13)

## O que foi feito

O projeto foi transformado em uma aplicacao web multiusuario com banco hosted, mantendo intactos os parsers, o fluxo de importacao com validacao visual e as regras de deduplicacao ja validadas.

### Backend
- `backend/db.py` (novo): camada dual de banco. Com `DATABASE_URL` usa Postgres hosted (psycopg3) traduzindo automaticamente o dialeto sqlite do codigo existente; sem ela, segue no SQLite local para dev.
- `backend/auth.py` (novo): usuarios, sessoes por token Bearer, senha com PBKDF2, bootstrap do admin por variaveis de ambiente, trilha de auditoria.
- `backend/app.py`: 
  - guard de autenticacao e papeis em todas as rotas (`admin` faz tudo; `colaborador` le e classifica);
  - CORS controlado por `CORS_ORIGINS`;
  - trava pos-classificacao: salvar classifica e protege (`locked=1`); reclassificar sem desbloquear retorna 423 `TX_LOCKED`; `POST /transactions/<id>/unlock` (admin) desbloqueia com auditoria;
  - `bulk-classify` pula travados (`skipped_locked`), `bulk-vincular` e "limpar classificacoes" nunca tocam travados;
  - auditoria em login, classificacoes, flags, unlock, usuarios e reset;
  - novos endpoints: `auth/login|logout|me|users`, `transactions/<id>/unlock`, `audit`;
  - init serializado por advisory lock (seguro com varios workers gunicorn);
  - `requirements.txt` com psycopg e gunicorn; `Procfile` incluido.

### Frontend
- Pagina `/login`; token e usuario guardados no navegador; `lib/api.ts` envia `Authorization` em todas as chamadas e redireciona para o login em 401.
- `AuthGate` protege todas as rotas; Topbar mostra usuario/perfil e botao sair; acoes administrativas ficam ocultas para colaborador.
- Tabela de lancamentos: lancamento classificado aparece com cadeado, campos desabilitados e (para admin) botao **Desbloquear**; mensagens claras para `TX_LOCKED` e para itens protegidos ignorados no lote.
- Build de producao do Next.js validado (`next build` ok).

### Testes executados neste ambiente
- SQLite e Postgres reais: login, papeis (403 para colaborador em acoes de admin), classificar -> 423 ao reclassificar -> unlock por admin -> reclassificar -> auditoria completa por campo.
- Postgres do zero com 1, 2 e 3 workers gunicorn: schema/migracoes/seed criados sem erro.
- CORS: origem permitida recebe headers; origem desconhecida nao recebe.

## Regras confirmadas
- Lancamentos reais so nascem de importacao; base historica so alimenta sugestoes.
- Cartao = saida por padrao; receita em cartao apenas estorno/reembolso/cashback/credito/devolucao (logica de parsing preservada).
- Preview com totais, duplicados internos (permitidos) e duplicados no banco (bloqueados) antes do commit.
- Classificado/salvo fica protegido; alterar exige desbloqueio explicito e gera auditoria.

## Como colocar no ar
Siga `docs/DEPLOY.md` (Neon + Render + Vercel, ~30 minutos). Arquitetura e limitacoes em `docs/ARQUITETURA-WEB.md`.

## Proximos passos sugeridos (nao bloqueiam o uso)
1. Tela de gerenciamento de usuarios no frontend (hoje a criacao da colaboradora e via API, com curl documentado).
2. Tela de auditoria (endpoint ja existe).
3. Guardar os arquivos originais dos extratos no Postgres ou em storage (hoje os originais nao persistem entre deploys; os dados sim).
